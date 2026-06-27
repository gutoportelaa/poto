"""LLM fallback handling with timeout, automatic retry, and thread degradation.

Circuit breaker and per-thread degradation state live in `circuit_state`,
backed by Redis when configured (shared across workers) or in-process
memory otherwise.
"""

import asyncio
import logging
from typing import Any

import httpx
import openai
from langchain_core.runnables import Runnable, RunnableConfig, RunnableSerializable
from pydantic import BaseModel

from agents.bo_facil.core import circuit_state
from core import runtime_settings, settings
from core.llm import get_model

logger = logging.getLogger(__name__)

# Exceptions that should trigger fallback (transient/recoverable errors)
FALLBACK_EXCEPTIONS = (
    TimeoutError,
    asyncio.TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    ConnectionError,
    OSError,
    openai.APIConnectionError,
    openai.InternalServerError,  # 500
    openai.RateLimitError,  # 429
)


def _get_thread_id(config: RunnableConfig | None) -> str | None:
    """Extract thread_id from LangGraph config."""
    if not config:
        return None
    configurable = config.get("configurable", {})
    return configurable.get("thread_id")


class RunnableWithFallback(RunnableSerializable):
    """Runnable with timeout and fallback. Returns redirect dict if both fail.

    Telemetry: when ``node_name`` (and optionally ``tier``) is passed at
    construction, every primary and fallback call has those values injected
    into ``config.metadata`` before invocation. LangSmith reads metadata
    off the call-time config, so this propagates regardless of whether
    ``inner`` is a ``RunnableBinding``, ``RunnableSequence`` (from
    ``with_structured_output``), or any other Runnable shape — the
    ``with_config`` approach silently loses metadata after
    ``with_structured_output`` and is therefore not reliable.
    """

    inner: Runnable
    node_name: str | None = None
    tier: str | None = None

    class Config:
        arbitrary_types_allowed = True

    async def ainvoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
        thread_id = _get_thread_id(config)
        primary_config = self._inject_metadata(config)

        # Circuit open OR thread degraded → skip primary entirely.
        if await circuit_state.is_circuit_open():
            logger.info("Circuit is open, skipping primary model")
            return await self._try_fallback(input, primary_config)
        if await circuit_state.is_thread_degraded(thread_id):
            logger.info(f"Thread {thread_id} is degraded, skipping primary model")
            return await self._try_fallback(input, primary_config)

        primary_timeout = runtime_settings.resolve("LLM_TIMEOUT")
        try:
            return await asyncio.wait_for(
                self.inner.ainvoke(input, primary_config),
                timeout=primary_timeout,
            )
        except FALLBACK_EXCEPTIONS as e:
            logger.warning(f"Primary model failed with {type(e).__name__}: {e}")
            await circuit_state.mark_thread_degraded(thread_id)
            await circuit_state.record_global_failure()
            return await self._try_fallback(input, primary_config)

    async def _try_fallback(self, input: Any, config: RunnableConfig | None) -> Any:
        if not settings.FALLBACK_MODEL:
            logger.error(
                f"Timeout after {runtime_settings.resolve('LLM_TIMEOUT')}s, no fallback configured"
            )
            return self._redirect_response()

        logger.warning(f"Trying fallback model: {settings.FALLBACK_MODEL}")
        try:
            fallback = get_model(settings.FALLBACK_MODEL)
            schema = getattr(self.inner, "output_schema", None)
            if schema and isinstance(schema, type) and issubclass(schema, BaseModel):
                fallback = fallback.with_structured_output(schema)

            fallback_config = self._inject_metadata(config, extra={"fallback_invoked": True})

            return await asyncio.wait_for(
                fallback.ainvoke(input, fallback_config),
                timeout=runtime_settings.resolve("LLM_FALLBACK_TIMEOUT"),
            )
        except Exception as e:
            logger.error(f"Fallback failed: {type(e).__name__}: {e}")
            return self._redirect_response()

    def _inject_metadata(
        self,
        config: RunnableConfig | None,
        extra: dict | None = None,
    ) -> RunnableConfig:
        """Return a copy of ``config`` with node_name/tier/extra merged into metadata.

        Caller-supplied metadata keys win over our defaults (setdefault semantics)
        but ``extra`` is applied last to allow per-call overrides like
        ``fallback_invoked`` to take precedence over any preserved caller value.
        """
        merged: dict = dict(config or {})
        meta = dict(merged.get("metadata") or {})
        if self.node_name:
            meta.setdefault("node_name", self.node_name)
        if self.tier:
            meta.setdefault("llm_tier", self.tier)
        if extra:
            meta.update(extra)
        merged["metadata"] = meta
        return merged

    def _redirect_response(self) -> dict:
        """Return dict indicating redirect to a human attendant.

        Both the primary and fallback models failed. This is a technical fault,
        NOT an emergency — routing to 190 sends the citizen to an emergency line
        that bounces them back. Degrade to the regular human handoff so an agent
        picks up the conversation (with whatever was already collected).
        """
        from agents.bo_facil.flows.emergency.messages import TECHNICAL_ERROR_MESSAGE

        return {
            "_redirect": True,
            "redirect": {
                "to": "human",
                "reason": "Technical error",
                "custom_message": TECHNICAL_ERROR_MESSAGE,
            },
        }

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> Any:
        return self.inner.invoke(input, config)


async def probe_primary() -> bool:
    """Test primary liveness via ``GET /v1/models`` — zero tokens, no LangSmith pollution.

    Targets ``COMPATIBLE_BASE_URL`` (the openai-compatible proxy where
    outages actually happen in our setup). A 200 means the proxy is up,
    auth works, and the inference fleet is responsive. The check is
    invisible to model dashboards: it never reaches the chat-completion
    endpoint and produces no traces.
    """
    timeout = runtime_settings.resolve("HEALTH_PROBE_TIMEOUT")
    base_url = settings.COMPATIBLE_BASE_URL
    api_key = settings.COMPATIBLE_API_KEY

    if not base_url or not api_key:
        logger.info("Health probe skipped: COMPATIBLE_BASE_URL or COMPATIBLE_API_KEY unset")
        return False

    token = api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else str(api_key)
    url = f"{base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            ok = r.status_code == 200
            if not ok:
                logger.info("Health probe got HTTP %s from %s", r.status_code, url)
            return ok
    except Exception as e:
        logger.info("Health probe failed: %s: %s", type(e).__name__, e)
        return False
