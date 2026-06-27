"""Extraction node - extracts incident info from conversation (NO interrupt).

This node analyzes the existing conversation and extracts fact, datetime,
and location information. It does NOT make any interrupt calls - it only
reads and analyzes what's already there.
"""

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    IncidentInfo,
    RedirectInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import is_redirect, now_brazil, wrap_model_scratchpad
from agents.bo_facil.flows.bo_treatment.location_extractor import extract_location_data
from agents.bo_facil.flows.bo_treatment.location_extractor.normalize import normalize_text
from agents.bo_facil.flows.bo_treatment.models import UnifiedIncidentExtraction
from agents.bo_facil.flows.bo_treatment.models.common import (
    DatetimeExtraction,
    FactExtraction,
    LocationExtraction,
)
from agents.bo_facil.flows.bo_treatment.prompts.common import (
    datetime_extraction_prompt,
    fact_extraction_prompt,
    location_extraction_prompt,
)
from agents.bo_facil.flows.bo_treatment.utils import (
    build_conversation_history,
    resolve_temporal_from_messages,
    resolve_temporal_references,
    validate_extracted_datetime,
)
from agents.bo_facil.flows.bo_treatment.utils.uf_detector import detect_uf_in_location
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


_COORDINATE_PATTERN = re.compile(
    r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$",
)


def _extract_coordinates(text: str) -> tuple[float, float] | None:
    """Extract latitude/longitude from a coordinate-only message.

    Supports the format sent by the WhatsApp bridge: "-5.0892, -42.8019"

    Returns:
        (latitude, longitude) if valid coordinates, None otherwise.
    """
    match = _COORDINATE_PATTERN.match(text.strip())
    if not match:
        return None
    try:
        lat = float(match.group(1))
        lng = float(match.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return (lat, lng)
    except ValueError:
        pass
    return None


def _build_address_from_geocoded(geocoded: dict) -> str:
    """Build a human-readable address from geocoding API response data."""
    parts = []
    if geocoded.get("Rua"):
        rua = geocoded["Rua"]
        if geocoded.get("Número"):
            rua += f", {geocoded['Número']}"
        parts.append(rua)
    if geocoded.get("Bairro"):
        parts.append(geocoded["Bairro"])
    if geocoded.get("Cidade"):
        parts.append(geocoded["Cidade"])
    if geocoded.get("Estado"):
        parts.append(geocoded["Estado"])
    return ", ".join(parts)


_VALID_UFS = frozenset(
    {
        "AC",
        "AL",
        "AP",
        "AM",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MT",
        "MS",
        "MG",
        "PA",
        "PB",
        "PR",
        "PE",
        "PI",
        "RJ",
        "RN",
        "RS",
        "RO",
        "RR",
        "SC",
        "SP",
        "SE",
        "TO",
    }
)


def apply_uf_detection(
    incident: IncidentInfo,
    state_uf: str | None = None,
) -> IncidentInfo:
    """Return a new IncidentInfo with non_pi_state_detected/detected_state set.

    Priority:
      1. `state_uf` argument (authoritative — from the extractor LLM).
      2. `detect_uf_in_location(incident.location)` regex fallback.

    Invalid `state_uf` values (not in the 27 Brazilian states) are rejected and
    fall through to the regex fallback. The geocoder-derived UF is NOT trusted
    here (it hallucinates UF for vague landmarks).

    No-op when `incident.non_pi_state_acknowledged` is True.
    """
    if incident.non_pi_state_acknowledged:
        return incident

    detected_uf: str | None = None

    if state_uf:
        candidate = state_uf.strip().upper()
        if candidate in _VALID_UFS:
            detected_uf = candidate

    if detected_uf is None and incident.location:
        detected_uf = detect_uf_in_location(incident.location)

    if detected_uf and detected_uf != "PI":
        return incident.model_copy(
            update={
                "non_pi_state_detected": True,
                "detected_state": detected_uf,
            }
        )

    return incident


def _extract_all_context(state: BOState) -> dict[str, Any]:
    """Extract ALL context sources for unified analysis."""
    messages = state.get("messages", [])

    # Get last user message
    current_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # Conversation histories — tailored per extraction type to reduce token usage.
    # Fact needs more context (user may describe across multiple messages).
    # Datetime/location are usually concentrated in recent messages.
    conversation_history_full = build_conversation_history(state, max_messages=12)
    conversation_history_short = build_conversation_history(state, max_messages=6)

    # Scratchpad context
    scratchpad = state.get("scratchpad", "")

    # Existing incident data
    incident = get_state_field(state, "incident", IncidentInfo)
    collection = get_state_field(state, "collection", CollectionStatus)
    existing_data = {
        "fact": incident.fact,
        "datetime": incident.datetime,
        "location": incident.location,
    }

    # Previous followup question to avoid repeating
    previous_followup = collection.fact_followup_question or ""

    # Resolve temporal references deterministically
    now = now_brazil()
    temporal_hints = resolve_temporal_references(current_message, now)
    if not temporal_hints.has_datetime:
        temporal_hints = resolve_temporal_from_messages(messages, now)

    return {
        "current_message": current_message,
        "conversation_history_full": conversation_history_full,
        "conversation_history_short": conversation_history_short,
        "scratchpad": scratchpad,
        "existing_data": json.dumps(existing_data, ensure_ascii=False),
        "current_datetime": now.isoformat(),
        "temporal_hints": temporal_hints.to_prompt_hint(),
        "previous_followup_question": previous_followup,
    }


async def _safe_llm_call(
    state, config, model, prompt_text, timeout: float = 15.0, node_name: str | None = None
):
    """Run a single LLM call with error handling and timeout. Returns None on failure."""
    import asyncio

    runnable = wrap_model_scratchpad(model, prompt_text, node_name=node_name).with_config(
        tags=["skip_stream"]
    )
    try:
        result = await asyncio.wait_for(
            runnable.ainvoke(state, config),
            timeout=timeout,
        )
        if is_redirect(result):
            logger.warning("[_safe_llm_call] Redirect detected, skipping")
            return None
        return result
    except TimeoutError:
        logger.warning(f"[_safe_llm_call] LLM call timed out after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"[_safe_llm_call] LLM call failed: {e}")
        return None


async def _run_sequential_extraction(
    state: BOState,
    config: RunnableConfig,
    context: dict[str, Any],
    collection: CollectionStatus,
) -> UnifiedIncidentExtraction:
    """Run up to 3 focused LLM calls in parallel, skipping already-collected fields."""
    import asyncio

    result = UnifiedIncidentExtraction()
    llm = resolve_model("extract_incident_info", config)

    # Build tasks for uncollected fields (run in parallel)
    tasks = {}

    if not collection.has_fact:
        prompt = fact_extraction_prompt.format(
            current_message=context["current_message"],
            conversation_history=context["conversation_history_full"],
            scratchpad=context["scratchpad"],
            previous_followup_question=context["previous_followup_question"],
        )
        tasks["fact"] = _safe_llm_call(
            state,
            config,
            llm.with_structured_output(FactExtraction),
            prompt,
            node_name="extract_fact",
        )

    if not collection.has_datetime:
        prompt = datetime_extraction_prompt.format(
            current_message=context["current_message"],
            conversation_history=context["conversation_history_short"],
            current_datetime=context["current_datetime"],
            temporal_hints=context["temporal_hints"],
        )
        tasks["datetime"] = _safe_llm_call(
            state,
            config,
            llm.with_structured_output(DatetimeExtraction),
            prompt,
            node_name="extract_datetime",
        )

    if not collection.has_location:
        prompt = location_extraction_prompt.format(
            current_message=context["current_message"],
            history=context["conversation_history_short"],
            scratchpad=context["scratchpad"],
        )
        tasks["location"] = _safe_llm_call(
            state,
            config,
            llm.with_structured_output(LocationExtraction),
            prompt,
            node_name="extract_location",
        )

    if not tasks:
        return result

    # Run all pending extractions in parallel
    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for key, res in zip(keys, results):
        if isinstance(res, Exception):
            logger.error(f"[_run_sequential_extraction] {key} extraction failed: {res}")
            continue
        if res is None:
            continue

        if key == "fact":
            result.has_fact = res.has_fact
            result.fact = res.fact
            result.is_fact_explained = res.is_fact_explained
            result.followup_question = res.followup_question
            if hasattr(res, "is_non_bo_intent"):
                result.is_non_bo_intent = res.is_non_bo_intent
                result.non_bo_intent_type = getattr(res, "non_bo_intent_type", None)
            if hasattr(res, "is_non_registrable"):
                result.is_non_registrable = res.is_non_registrable
        elif key == "datetime":
            result.has_datetime = res.has_datetime
            result.datetime = res.datetime
        elif key == "location":
            result.has_location = res.has_location
            result.location = res.location
            result.state_mentioned = res.state_mentioned
            result.state_uf = res.state_uf

    return result


def _apply_geocoded_data(geocoded: dict, updates: dict) -> None:
    """Extract lat/lng and structured data from geocoding result into updates dict."""
    for key in ("latitude", "Latitude"):
        val = geocoded.get(key)
        if val is not None and "latitude" not in updates:
            try:
                updates["latitude"] = float(val)
            except (ValueError, TypeError):
                pass
    for key in ("longitude", "Longitude"):
        val = geocoded.get(key)
        if val is not None and "longitude" not in updates:
            try:
                updates["longitude"] = float(val)
            except (ValueError, TypeError):
                pass
    updates["geocoded_data"] = dict(geocoded)


def _merge_location_fragments(previous: str | None, new: str | None) -> str | None:
    """Combine a location fragment captured on an earlier turn with a newer one.

    Users frequently give the street on one turn ("Rua Valdivino Tito") and the
    city on the next ("Teresina"). Geocoding only the latest message resolves to
    the city centroid and fabricates a wrong street/bairro; combining the two
    recovers the real address.

    Returns the richer combined string, avoiding duplication when one already
    contains the other (accent/case-insensitive substring match). The newer
    fragment is appended after the older one, matching the natural
    specific→general order (street given before city).
    """
    prev = (previous or "").strip()
    cur = (new or "").strip()
    if not prev:
        return cur or None
    if not cur:
        return prev or None
    np = normalize_text(prev)
    nc = normalize_text(cur)
    if np in nc:
        return cur
    if nc in np:
        return prev
    return f"{prev}, {cur}"


async def _accept_location(
    text: str | None,
    incident_updates: dict[str, Any],
    collection_updates: dict[str, Any],
    *,
    is_coordinates: bool = False,
    original_user_text: str | None = None,
) -> None:
    """Accept location and extract structured data via the 3-layer orchestrator.

    Always sets has_location=True and preserves the raw user text in
    incident.location. Structured data (municipio, uf, bairro, logradouro)
    and coordinates are populated by the orchestrator — sourced from the
    geocoder (with V1/V3 validation), regex parser, or LLM parser.

    When `original_user_text` is provided, the orchestrator uses it as a
    fallback when the normalized `text` fails — this recovers names that
    the upstream LLM may have dropped during normalization.
    """
    if text:
        incident_updates["location"] = text
        # Keep reference_point mirrored to location for backward compat with
        # the legacy builder fallback. Raw coords are not mirrored here — the
        # builder sanitizes coordinate-only strings before sending.
        if not is_coordinates:
            incident_updates["reference_point"] = text
    collection_updates["has_location"] = True

    if not text:
        return

    try:
        data = await extract_location_data(text, original_user_text=original_user_text)
    except Exception as e:
        logger.error(
            f"[_accept_location] orchestrator failed for {text!r}: {e}",
            exc_info=True,
        )
        return

    incident_updates["structured"] = data.structured
    incident_updates["coordinates"] = list(data.coordinates) if data.coordinates else None

    if data.structured or data.coordinates:
        collection_updates["location_geocoded"] = True

    # If input was coordinates and structured data is available, replace the
    # user-facing location text with a readable address (preserves old UX).
    if is_coordinates and data.structured:
        parts = [
            data.structured.logradouro,
            data.structured.bairro,
            data.structured.municipio,
            data.structured.uf,
        ]
        built = ", ".join(p for p in parts if p)
        if built:
            incident_updates["location"] = built
            incident_updates["reference_point"] = built
    elif is_coordinates and not data.structured:
        # Coordinates couldn't be resolved — don't send raw coords as ref point
        incident_updates["reference_point"] = None

    logger.info(
        f"[_accept_location] source={data.source} "
        f"municipio={data.structured.municipio if data.structured else None}"
    )


async def extract_incident_info_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """Extract incident information from existing conversation (NO interrupt).

    This node:
    1. Extracts all context from messages, scratchpad, and existing data
    2. Runs unified LLM extraction
    3. Updates incident and collection state based on extraction results
    4. Returns state update WITHOUT making any interrupt calls

    The graph routing will decide next steps based on collection completeness.

    Returns:
        State update with incident and collection updates (no messages).
    """
    logger.info("[extract_incident_info] Starting extraction (no interrupt)")

    # Early return if redirect is set (avoids unnecessary LLM calls)
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        logger.info(
            f"[extract_incident_info] Redirect detected ({redirect.to}), skipping extraction"
        )
        return {"messages": []}

    incident = get_state_field(state, "incident", IncidentInfo)
    collection = get_state_field(state, "collection", CollectionStatus)

    # Check what we already have
    has_fact = collection.has_fact
    has_datetime = collection.has_datetime
    has_location = collection.has_location

    logger.info(
        f"[extract_incident_info] Current state - "
        f"has_fact={has_fact}, has_datetime={has_datetime}, has_location={has_location}"
    )

    # If everything is already collected, return early
    if has_fact and has_datetime and has_location:
        logger.info("[extract_incident_info] All fields already collected")
        return {"messages": []}

    # Extract context and run sequential LLM calls (skip already-collected fields)
    context = _extract_all_context(state)
    extraction = await _run_sequential_extraction(state, config, context, collection)

    logger.info(
        f"[extract_incident_info] Extraction result - "
        f"fact={extraction.has_fact}, datetime={extraction.has_datetime}, "
        f"location={extraction.has_location}"
    )

    # Build updates
    incident_updates: dict[str, Any] = {}
    collection_updates: dict[str, Any] = {}

    # Detect non-BO intent (user wants something other than registering a BO)
    if not has_fact and extraction.is_non_bo_intent:
        collection_updates["non_bo_intent_detected"] = True
        collection_updates["non_bo_intent_type"] = extraction.non_bo_intent_type or "outro"
        logger.info(
            f"[extract_incident_info] Non-BO intent detected: type={extraction.non_bo_intent_type}"
        )

    # Apply extraction results (only for fields not yet collected)
    if not has_fact and extraction.has_fact and extraction.is_non_registrable:
        # Non-criminal fact: accept it but flag for soft redirect in followup
        incident_updates["fact"] = extraction.fact
        collection_updates["has_fact"] = True
        collection_updates["non_registrable_detected"] = True
        logger.info(f"[extract_incident_info] Non-criminal fact accepted: {extraction.fact}")
    elif not has_fact and extraction.has_fact and extraction.is_fact_explained and extraction.fact:
        incident_updates["fact"] = extraction.fact
        collection_updates["has_fact"] = True
    elif not has_fact and extraction.has_fact and not extraction.is_fact_explained:
        # Safety net: after 1+ followup attempts, accept the fact even if LLM
        # still marks is_fact_explained=false — the user already elaborated
        if collection.fact_attempts >= 2 and extraction.fact:
            logger.info(
                f"[extract_incident_info] Accepting fact after {collection.fact_attempts} "
                f"followup attempt(s) despite is_fact_explained=false"
            )
            incident_updates["fact"] = extraction.fact
            collection_updates["has_fact"] = True
        else:
            if extraction.followup_question:
                collection_updates["fact_followup_question"] = extraction.followup_question
            logger.info(
                f"[extract_incident_info] Fact not well explained, "
                f"attempts={collection.fact_attempts}, "
                f"followup_question={extraction.followup_question}"
            )
    elif not has_fact and not extraction.has_fact:
        # No fact detected at all (gibberish/irrelevant input) - store followup question for varied messaging
        if extraction.followup_question:
            collection_updates["fact_followup_question"] = extraction.followup_question

    # Compute temporal hints for Layer 3 fallback (independent of prompt context)
    now = now_brazil()
    temporal_hints = resolve_temporal_from_messages(state.get("messages", []), now)

    if not has_datetime and extraction.has_datetime and extraction.datetime:
        # Layer 1: LLM extracted datetime successfully
        incident_updates["datetime"] = extraction.datetime
        collection_updates["has_datetime"] = True
    elif (
        not has_datetime
        and not extraction.has_datetime
        and extraction.datetime
        and " " in extraction.datetime
    ):
        # Layer 2: LLM provided a valid datetime string but marked has_datetime=False.
        # Accept it if it contains both date and time (space-separated).
        logger.info(
            f"[extract_incident_info] Accepting datetime from fallback L2: {extraction.datetime}"
        )
        incident_updates["datetime"] = extraction.datetime
        collection_updates["has_datetime"] = True
    elif not has_datetime and temporal_hints.has_datetime:
        # Layer 3: Code resolved datetime deterministically, LLM failed
        logger.info(
            f"[extract_incident_info] Accepting datetime from temporal fallback L3: "
            f"{temporal_hints.resolved_datetime}"
        )
        incident_updates["datetime"] = temporal_hints.resolved_datetime
        collection_updates["has_datetime"] = True

    # Validate extracted datetime is not in the future
    if collection_updates.get("has_datetime") and incident_updates.get("datetime"):
        validated_dt, is_valid = validate_extracted_datetime(incident_updates["datetime"], now)
        if not is_valid:
            logger.warning(
                f"[extract_incident_info] Rejecting future datetime: {incident_updates['datetime']}"
            )
            del incident_updates["datetime"]
            collection_updates["has_datetime"] = False
            collection_updates["datetime_future_rejected"] = True
        elif validated_dt != incident_updates["datetime"]:
            logger.info(
                f"[extract_incident_info] Clamped future time to now: "
                f"{incident_updates['datetime']} → {validated_dt}"
            )
            incident_updates["datetime"] = validated_dt

    if not has_location:
        coords = _extract_coordinates(context["current_message"])

        if coords:
            lat, lng = coords
            incident_updates["latitude"] = lat
            incident_updates["longitude"] = lng
            await _accept_location(
                f"{lat}, {lng}",
                incident_updates,
                collection_updates,
                is_coordinates=True,
            )

        elif extraction.has_location and extraction.location:
            # Prompt's single criterion: text contains a proper-name place.
            # Accept and let the 3-layer orchestrator handle structuring —
            # V1/V3 validation catches geocoder hallucinations downstream.
            # Combine with any partial fragment captured on a prior turn (e.g.
            # the user gave the street first, then only the city) so the
            # geocoder receives the full address — geocoding the city alone
            # resolves to the centroid and fabricates a wrong street/bairro.
            # Pass the raw user message so the orchestrator can retry on it
            # if the LLM's normalized output dropped proper names.
            combined = _merge_location_fragments(incident.location, extraction.location)
            await _accept_location(
                combined,
                incident_updates,
                collection_updates,
                original_user_text=context["current_message"],
            )

        elif extraction.location:
            # Partial: city/UF still missing so we can't geocode confidently
            # yet, but keep the street/bairro fragment for the next turn so it
            # isn't lost when the user finally provides the city. has_location
            # stays False — the followup will still ask for the city.
            draft = _merge_location_fragments(incident.location, extraction.location)
            if draft and draft != incident.location:
                incident_updates["location"] = draft
                logger.info(f"[extract_incident_info] Stored partial location draft: {draft!r}")

        # else: no place pista at all in the message → followup will ask

    # Build result
    result: dict[str, Any] = {"messages": []}
    final_incident = incident.model_copy(update=incident_updates) if incident_updates else incident

    # Always re-evaluate non-PI flag (no-op if already acknowledged or PI).
    state_uf = extraction.state_uf if extraction else None
    final_incident = apply_uf_detection(final_incident, state_uf=state_uf)

    if final_incident is not incident:
        result["incident"] = final_incident

    if collection_updates:
        result["collection"] = collection.model_copy(update=collection_updates)

    logger.info(
        f"[extract_incident_info] Completed - "
        f"incident_updates={list(incident_updates.keys())}, "
        f"collection_updates={list(collection_updates.keys())}"
    )

    return result
