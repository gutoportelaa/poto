"""CAMADA 3 — LLM parser as last-resort fallback.

Uses MunicipioExtraction (Pydantic) to extract municipio + uf from messy free text.
Always runs V1 substring validation on the LLM output to prevent hallucination.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from langchain.prompts import SystemMessagePromptTemplate
from pydantic import BaseModel, Field

from .models import StructuredLocation
from .normalize import STATE_TO_UF, VALID_UFS, normalize_state, normalize_text
from .validation import fuzzy_match_in_text

logger = logging.getLogger(__name__)


class MunicipioExtraction(BaseModel):
    """Pydantic schema for the LLM parser structured output."""

    municipio: str | None = Field(
        default=None,
        description=(
            "City name as mentioned in the text (name only, without UF). "
            "null if no city is explicitly mentioned. "
            "NEVER infer the city from neighborhood, street, or ZIP code."
        ),
    )
    uf: str | None = Field(
        default=None,
        description=(
            "Two-letter Brazilian state code mentioned in the text (e.g. 'PI', 'RS'). "
            "Accept both the code and the full state name ('Piauí' → 'PI'). "
            "null if no state is mentioned. NEVER infer UF from the city name."
        ),
    )


# Type for an injectable LLM call (for testability)
LLMParserFn = Callable[[str], Awaitable[MunicipioExtraction | None]]


municipio_extraction_prompt = SystemMessagePromptTemplate.from_template(
    """Extract municipio (city) and UF (Brazilian state code) from the text below.

STRICT RULES:
1. Extract ONLY what is EXPLICITLY mentioned in the text.
2. Return null for any field NOT mentioned.
3. NEVER infer city from neighborhood, street, or ZIP code.
4. NEVER infer UF from city name.
5. UF must be a valid 2-letter Brazilian state code (PI, RS, SP, etc.).
6. If the text mentions multiple cities, pick the FIRST one.

EXAMPLES:
"Caxingó, Piauí" → municipio="Caxingó", uf="PI"
"Av Frei Serafim, Teresina, PI" → municipio="Teresina", uf="PI"
"em Porto Alegre" → municipio="Porto Alegre", uf=null
"no Rio Grande do Sul" → municipio=null, uf="RS"
"em casa" → municipio=null, uf=null
"bairro Centro" → municipio=null, uf=null

═══════════════════════════════════════
TEXTO: {text}
═══════════════════════════════════════
"""
)


async def parse_location_llm(
    text: str,
    *,
    llm_call: LLMParserFn | None = None,
    fuzzy: bool = False,
    timeout: float = 10.0,
) -> StructuredLocation | None:
    """CAMADA 3 — LLM parser with V1 post-validation.

    Args:
        text: Free-form location text.
        llm_call: Injectable LLM caller for testability.
        fuzzy: Enable V2 fuzzy matching for typo tolerance.
        timeout: Max seconds for the LLM call.

    Returns:
        StructuredLocation with municipio and/or uf if extraction passes V1.
        None if extraction failed or post-validation rejected the result.
    """
    if not text or not text.strip():
        return None

    caller = llm_call or _real_llm_call

    try:
        result = await asyncio.wait_for(caller(text), timeout=timeout)
    except TimeoutError:
        logger.warning(f"[llm_parser] timeout after {timeout}s for {text!r}")
        return None
    except Exception as e:
        logger.warning(f"[llm_parser] LLM call failed: {e}")
        return None

    if result is None:
        return None

    municipio = result.municipio.strip() if result.municipio else None
    uf_raw = result.uf.strip() if result.uf else None
    uf = normalize_state(uf_raw) if uf_raw else None

    if uf and uf not in VALID_UFS:
        uf = None

    # Post-validation: substring check (V1 logic adapted for parser)
    text_norm = normalize_text(text)

    if municipio:
        cidade_norm = normalize_text(municipio)
        if cidade_norm not in text_norm:
            if not (fuzzy and fuzzy_match_in_text(municipio, text)):
                logger.info(
                    f"[llm_parser] V1 rejected municipio={municipio!r} (not in text {text!r})"
                )
                municipio = None

    if uf:
        import re

        if not re.search(rf"\b{uf}\b", text, re.IGNORECASE):
            estado_full_norm = next(
                (normalize_text(name) for name, code in STATE_TO_UF.items() if code == uf),
                None,
            )
            if not (estado_full_norm and estado_full_norm in text_norm):
                logger.info(f"[llm_parser] V1 rejected uf={uf!r} (not in text {text!r})")
                uf = None

    if not municipio and not uf:
        return None

    return StructuredLocation(municipio=municipio, uf=uf)


# ---------------------------------------------------------------------------
# Real LLM caller (production default) — uses the configured "simple" tier.
# ---------------------------------------------------------------------------


async def _real_llm_call(text: str) -> MunicipioExtraction | None:
    """Default LLM caller using the simple-tier model."""
    from core.llm import get_model
    from core.settings import settings

    # Use a fixed lightweight model — this is a parsing task, not reasoning.
    # Default to OpenAI gpt-4o-mini if available, else fall back to default model.
    model_name = "gpt-4o-mini"
    try:
        model = get_model(model_name)
    except Exception:
        model = get_model(settings.DEFAULT_MODEL)

    structured = model.with_structured_output(MunicipioExtraction)
    prompt = municipio_extraction_prompt.format(text=text)
    invoke_config = {
        "metadata": {"node_name": "location_municipio_extraction", "llm_tier": "fixed"}
    }
    result = await structured.ainvoke([prompt], invoke_config)
    return result if isinstance(result, MunicipioExtraction) else None
