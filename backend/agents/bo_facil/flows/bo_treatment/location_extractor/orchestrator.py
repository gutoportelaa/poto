"""Orchestrator — runs the 3-layer cascade and returns the best LocationData.

Layer 1 (geocoder with V1/V3) → Layer 2 (regex parser) → Layer 3 (LLM parser).

Each layer can be disabled via parameter for testing.
"""

from __future__ import annotations

import logging

from .geocoder_pipeline import GeocoderFn, geocode_with_validation
from .llm_parser import LLMParserFn, parse_location_llm
from .models import LocationData
from .normalize import is_coordinates_only, parse_coordinates
from .regex_parser import parse_location_regex

logger = logging.getLogger(__name__)


async def extract_location_data(
    text: str,
    *,
    original_user_text: str | None = None,
    geocoder: GeocoderFn | None = None,
    llm_call: LLMParserFn | None = None,
    enable_llm: bool = True,
    fuzzy: bool = False,
) -> LocationData:
    """Run the three-layer cascade and return the best result.

    Args:
        text: Normalized location text from the upstream LLM (used by Layer 1
            because Lambda prefers clean input).
        original_user_text: Raw user message. Used as a safety net when the
            upstream LLM drops or abstracts information — Layers 1b/2/3
            retry on the original text so we can recover names like
            "Conceição do Canindé" that the LLM may have replaced with
            generic categories like "a cidade".
        geocoder: Optional injectable geocoder (for tests).
        llm_call: Optional injectable LLM caller (for tests).
        enable_llm: If False, skip Layer 3 (useful for offline tests).
        fuzzy: If True, enable V2 fuzzy matching across layers.

    Returns:
        LocationData with structured/coordinates/source. source="none"
        means no layer was able to extract anything reliable.
    """
    if not text or not text.strip():
        return LocationData(source="none")

    text = text.strip()
    raw = original_user_text.strip() if original_user_text else None
    # Skip raw fallback when it's identical to the normalized text.
    if raw == text:
        raw = None

    # Coordinates entry point — try forward directly, no fallback path needed
    if is_coordinates_only(text):
        result = await geocode_with_validation(text, geocoder=geocoder, fuzzy=fuzzy)
        if result.source == "none":
            # Geocoder couldn't resolve coords — at least keep the coords themselves
            coords = parse_coordinates(text)
            return LocationData(structured=None, coordinates=coords, source="none")
        return result

    # Layer 1: geocoder on normalized text
    layer1 = await geocode_with_validation(text, geocoder=geocoder, fuzzy=fuzzy)
    if layer1.source != "none":
        return layer1

    # Layer 1b: retry geocoder on raw user text (may contain names the LLM dropped)
    if raw:
        logger.info(
            f"[orchestrator] Layer 1 failed on {text!r}; retrying with raw user text"
        )
        layer1b = await geocode_with_validation(raw, geocoder=geocoder, fuzzy=fuzzy)
        if layer1b.source != "none":
            return layer1b

    # Layers 2 and 3 operate on the raw user text when available — the
    # normalized LLM output may have discarded information we need here.
    fallback_input = raw or text

    # Layer 2: regex parser
    regex_result = parse_location_regex(fallback_input)
    if regex_result is not None:
        return LocationData(
            structured=regex_result,
            coordinates=None,
            source="regex",
        )

    # Layer 3: LLM parser (optional)
    if enable_llm:
        llm_result = await parse_location_llm(
            fallback_input, llm_call=llm_call, fuzzy=fuzzy
        )
        if llm_result is not None:
            return LocationData(
                structured=llm_result,
                coordinates=None,
                source="llm",
            )

    return LocationData(source="none")
