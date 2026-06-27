"""Classification utilities for interrupt handling and state management.

Uses policy-based classification pipeline (Chain of Responsibility pattern).
"""

import asyncio
import logging
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from agents.bo_facil.core.messages import create_button_message, to_whatsapp_json
from agents.bo_facil.core.states import BOState, RedirectInfo
from agents.bo_facil.flows.cancel.messages import MSG_CANCEL_CONFIRMATION

from .models import ClassificationClass, ClassificationStrategy, HybridClassificationResult
from .pipeline import ClassifierPipeline
from .policies.post.audit_policy import AuditPolicy
from .policies.post.confidence_policy import ConfidencePolicy
from .policies.post.fallback_policy import FallbackPolicy
from .policies.pre.api_policy import ApiPolicy
from .policies.pre.regex_policy import RegexPolicy

logger = logging.getLogger(__name__)

RedirectType = Literal["emergency", "human", "cancel"]

# Singleton pipeline instance (double-checked locking)
_pipeline: ClassifierPipeline | None = None
_pipeline_lock = asyncio.Lock()


async def _get_pipeline() -> ClassifierPipeline:
    """Get or create the singleton classifier pipeline.

    Uses double-checked locking: fast path without lock when already
    initialized, async lock only on first creation to prevent races.

    Returns:
        ClassifierPipeline instance with pre and post policies
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    async with _pipeline_lock:
        if _pipeline is None:
            logger.info("[Pipeline] Initializing classifier pipeline")
            _pipeline = ClassifierPipeline(
                pre_policies=[
                    RegexPolicy(),
                    ApiPolicy(),
                ],
                post_policies=[
                    ConfidencePolicy(),
                    FallbackPolicy(),
                    AuditPolicy(),
                ],
            )
    return _pipeline


async def classify_and_interrupt(
    message_content: str,
    state: BOState,
    config: RunnableConfig | dict | None = None,
    strategy: ClassificationStrategy | None = None,
    skip_llm: bool = False,
    expecting_media: bool = False,
) -> tuple[str, RedirectType | None, HybridClassificationResult | None]:
    """Unified classification with interrupt handling using policy pipeline.

    Handles media URLs, cancel confirmation, and emergency/human detection
    transparently — callers only see the final (user_input, redirect_type, result).

    Media handling depends on ``expecting_media``:
      - ``False`` (default): a media URL is an *unexpected* mid-flow upload. It
        is acknowledged with ``MEDIA_FIRST_MESSAGE`` ("Recebido! ... digite
        pronto"), extra files are collected, and the original question is
        re-asked once the user finishes.
      - ``True``: the calling node explicitly asked for files and owns its own
        instruction copy, so files are collected *silently* (no acknowledgment)
        and the terminating non-media message falls through to classification —
        the node proceeds instead of re-asking. Emergency/human/cancel detection
        still runs on that final message.

    Args:
        message_content: WhatsApp JSON message to send for interrupt
        state: Current BO state
        config: LangGraph config with thread_id and model
        strategy: Classification strategy (ignored, kept for backward compatibility)
        skip_llm: Whether to skip LLM classification
        expecting_media: Whether the calling node explicitly asked for files

    Returns:
        tuple[user_input, redirect_type, classification_result]
    """
    from .media import MEDIA_FIRST_MESSAGE, MEDIA_SUBSEQUENT_MESSAGE, is_media_url

    # Get configurable for user_id
    # IMPORTANT: Prioritize thread_id over user_id to ensure thread isolation
    # This prevents false positives when the same user has multiple conversations
    configurable = config.get("configurable", {}) if config else {}
    user_id = configurable.get("thread_id") or configurable.get("user_id")

    # Use policy-based pipeline
    pipeline = await _get_pipeline()

    while True:
        # Get user input via interrupt
        user_input = interrupt(message_content)

        # Media URL detection: bridge sends photos/videos/documents as URLs.
        if is_media_url(user_input):
            if expecting_media:
                # The node asked for files and owns its instruction copy, so
                # collect silently (no acknowledgment) and let the terminating
                # non-media message fall through to classification — the node
                # proceeds instead of re-asking.
                logger.info(
                    "[ClassifyAndInterrupt] Media URL detected (expected), collecting silently"
                )
                while is_media_url(user_input):
                    logger.debug(
                        f"[ClassifyAndInterrupt] Additional media URL: {user_input[:80]}..."
                    )
                    user_input = interrupt(MEDIA_SUBSEQUENT_MESSAGE)
                # fall through to classify the terminating message and proceed
            else:
                # Unexpected mid-flow upload: acknowledge with the full message,
                # collect extra files, then re-ask the original question.
                logger.info("[ClassifyAndInterrupt] Media URL detected, starting media collection")
                user_input = interrupt(MEDIA_FIRST_MESSAGE)
                while is_media_url(user_input):
                    logger.debug(
                        f"[ClassifyAndInterrupt] Additional media URL: {user_input[:80]}..."
                    )
                    user_input = interrupt(MEDIA_SUBSEQUENT_MESSAGE)
                # Non-URL received (e.g. "pronto") — discard and re-ask
                logger.debug(
                    "[ClassifyAndInterrupt] Media collection done, re-asking original question"
                )
                continue

        try:
            result = await pipeline.classify(
                message=user_input,
                state=state,
                config=config,
                user_id=user_id,
                skip_llm=skip_llm,
            )

            if result.is_emergency():
                logger.info(
                    f"[ClassifyAndInterrupt] Emergency detected "
                    f"(confidence={result.confidence:.2f})"
                )
                return user_input, "emergency", result

            if result.needs_human_handoff():
                logger.info(
                    f"[ClassifyAndInterrupt] Human handoff needed "
                    f"(confidence={result.confidence:.2f})"
                )
                return user_input, "human", result

            if result.is_cancel():
                logger.info("[ClassifyAndInterrupt] Cancel intent detected, asking confirmation")
                confirmed = await _confirm_cancel(pipeline, state, config, user_id)
                if confirmed is True:
                    return user_input, "cancel", result
                if isinstance(confirmed, tuple):
                    # Confirmation response triggered emergency/human
                    return confirmed
                # User declined — re-ask original question
                logger.info("[ClassifyAndInterrupt] User declined cancel, continuing flow")
                continue

            logger.debug("[ClassifyAndInterrupt] Continuing normal flow")
            return user_input, None, result

        except GraphInterrupt:
            raise
        except Exception as e:
            logger.error(f"[ClassifyAndInterrupt] Classification error: {e}", exc_info=True)
            # Fail safe to human on error
            fail_safe_result = HybridClassificationResult(
                final_class="human",
                confidence=0.0,
                strategy_used=ClassificationStrategy.HYBRID,
                api_result=None,
                llm_result=None,
                reasoning=f"Fail safe: {str(e)}",
            )
            return user_input, "human", fail_safe_result


async def _confirm_cancel(
    pipeline: ClassifierPipeline,
    state: BOState,
    config: RunnableConfig | dict | None,
    user_id: str | None,
) -> bool | tuple[str, RedirectType, HybridClassificationResult]:
    """Ask user to confirm cancellation.

    Returns:
        True if confirmed, False if declined.
        If the confirmation response triggers emergency/human, returns
        the (user_input, redirect_type, result) tuple directly.
    """
    confirm_msg = create_button_message(
        body=MSG_CANCEL_CONFIRMATION,
        buttons=[("cancel_confirm_yes", "Sim, encerrar"), ("cancel_confirm_no", "Não, continuar")],
    )
    confirm_json = to_whatsapp_json(confirm_msg)
    response = interrupt(confirm_json)

    # Classify confirmation response to catch emergency/human during cancel
    try:
        confirm_result = await pipeline.classify(
            message=response,
            state=state,
            config=config,
            user_id=user_id,
            skip_llm=True,
        )
        if confirm_result.is_emergency():
            logger.info("[ConfirmCancel] Emergency detected during cancel confirmation")
            return response, "emergency", confirm_result
        if confirm_result.needs_human_handoff():
            logger.info("[ConfirmCancel] Human handoff detected during cancel confirmation")
            return response, "human", confirm_result
    except Exception:
        logger.warning("[ConfirmCancel] Classification failed during confirmation", exc_info=True)

    # Check if user confirmed (handles button ID, button text, and free-text responses)
    # Same confirm words used in response_classification.py (can't import due to circular dep)
    confirm_words = {"sim", "s", "yes", "confirmar", "confirmo"}
    lower = response.lower().strip()
    first_word = lower.split(",")[0].strip().split()[0] if lower else ""
    if "cancel_confirm_yes" in response or first_word in confirm_words:
        logger.info("[ConfirmCancel] User confirmed cancellation")
        return True

    logger.info("[ConfirmCancel] User declined cancellation")
    return False


def redirect_to_emergency(state: BOState, reason: str | None = None) -> dict:
    """Create state update for emergency redirect.

    Args:
        state: Current state (for merging)
        reason: Optional reason for redirect

    Returns:
        State update dict
    """
    logger.info("[RedirectToEmergency] Redirecting to emergency services")
    current = state.get("redirect", RedirectInfo())
    if isinstance(current, dict):
        current = RedirectInfo(**current)

    return {
        "redirect": current.model_copy(
            update={
                "to": "emergency",
                "reason": reason or "Emergência detectada automaticamente",
            }
        )
    }


def redirect_to_human(
    state: BOState, reason: str | None = None, custom_message: str | None = None
) -> dict:
    """Create state update for human handoff redirect.

    Args:
        state: Current state (for merging)
        reason: Optional reason for redirect
        custom_message: Optional custom message for handoff

    Returns:
        State update dict
    """
    logger.info("[RedirectToHuman] Redirecting to human agent")
    current = state.get("redirect", RedirectInfo())
    if isinstance(current, dict):
        current = RedirectInfo(**current)

    return {
        "redirect": current.model_copy(
            update={
                "to": "human",
                "reason": reason or "Atendimento humano necessário",
                "custom_message": custom_message,
            }
        )
    }


def redirect_to_cancel(state: BOState, reason: str | None = None) -> dict:
    """Create state update for user-requested cancellation.

    Args:
        state: Current state (for merging)
        reason: Optional reason for redirect

    Returns:
        State update dict
    """
    logger.info("[RedirectToCancel] User requested cancellation")
    current = state.get("redirect", RedirectInfo())
    if isinstance(current, dict):
        current = RedirectInfo(**current)

    return {
        "redirect": current.model_copy(
            update={
                "to": "cancel",
                "reason": reason or "Usuário solicitou cancelamento",
            }
        )
    }
