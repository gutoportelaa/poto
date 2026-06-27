"""Unified object collection node - hybrid approach combining preserved UX with simplified extraction.

This module implements a hybrid unified collection approach that:
- Preserves: Initial confirmation questions, weapon collection for aggression, decline handling
- Simplifies: Unified extraction from all sources, intelligent single follow-up
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    IncidentInfo,
    ObjectsInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import is_redirect, wrap_model_scratchpad
from agents.bo_facil.flows.bo_treatment.messages.object import (
    OBJECT_DESCRIPTION_AUDIO_HINT,
    OBJECT_DESCRIPTION_REQUEST,
    OBJECT_QUESTION,
    OBJECT_STOLEN_QUESTION,
    OBJECT_USED_DESCRIPTION_REQUEST,
    OBJECT_USED_QUESTION,
)
from agents.bo_facil.flows.bo_treatment.models.object import (
    FollowUpObjectDiff,
    UnifiedObjectExtraction,
    WeaponAnalysis,
)
from agents.bo_facil.flows.bo_treatment.prompts.object import (
    object_used_analysis_prompt,
    unified_extraction_prompt,
)
from agents.bo_facil.flows.bo_treatment.utils import (
    build_conversation_history,
    classify_response,
    soft_handle_redirect,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


def _obj_to_dict(obj: Any) -> dict:
    """Convert object (Pydantic model or dict) to dict."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return dict(obj)
    return {}


def _find_best_match(followup_obj: dict, initial_list: list[dict], matched: set[int]) -> int | None:
    """Find the best matching initial object for a follow-up object.

    Match strategy:
    1. Exact match on type + name substring overlap
    2. Unique match on type alone (if only one unmatched candidate of that type)
    """
    fu_type = followup_obj.get("type", "")
    fu_name = (followup_obj.get("name") or "").lower().strip()

    # Pass 1: type + name overlap
    for i, init_obj in enumerate(initial_list):
        if i in matched:
            continue
        if init_obj.get("type") != fu_type:
            continue
        init_name = (init_obj.get("name") or "").lower().strip()
        if fu_name and init_name and (fu_name in init_name or init_name in fu_name):
            return i

    # Pass 2: unique type match
    candidates = [
        i for i, obj in enumerate(initial_list) if i not in matched and obj.get("type") == fu_type
    ]
    if len(candidates) == 1:
        return candidates[0]

    return None


def _merge_objects(initial: list[dict], followup: list[dict]) -> list[dict]:
    """Merge follow-up extraction into initial objects deterministically.

    - Matched objects: follow-up values fill in or override null/empty fields.
    - Unmatched follow-up objects: added as new.
    - Unmatched initial objects: preserved as-is (never lost).
    """
    result = [dict(obj) for obj in initial]
    matched_indices: set[int] = set()

    for fu_obj in followup:
        idx = _find_best_match(fu_obj, result, matched_indices)
        if idx is not None:
            matched_indices.add(idx)
            # Merge: follow-up fills nulls / overrides with non-empty values
            for key, value in fu_obj.items():
                if value is None or value == "" or value == []:
                    continue
                existing = result[idx].get(key)
                if existing is None or existing == "" or existing == []:
                    result[idx][key] = value
                elif key == "description" and value != existing:
                    # Append novel description info
                    result[idx][key] = value
                # For other fields with existing values, keep existing (initial is the baseline)
        else:
            # New object from follow-up
            result.append(dict(fu_obj))

    return result


def _apply_followup_diff(baseline: list[dict], diff: FollowUpObjectDiff) -> list[dict]:
    """Apply a follow-up diff to baseline objects deterministically.

    - Updates: case-insensitive match by target_name, fill empty/None fields only.
    - Adds: append new objects.
    - Never removes or overwrites existing non-empty values (except description).
    """
    result = [dict(obj) for obj in baseline]

    for update in diff.objects_to_update:
        target = update.target_name.lower()
        for item in result:
            if (item.get("name") or "").lower() == target:
                changes = update.model_dump(exclude={"target_name"}, exclude_none=True)
                for key, value in changes.items():
                    existing = item.get(key)
                    if existing is None or existing == "":
                        item[key] = value
                    elif key == "description" and value != existing:
                        item[key] = value
                break

    for new_obj in diff.objects_to_add:
        result.append(_obj_to_dict(new_obj))

    return result


# Procedure type constants
ROBBERY_THEFT_CODES = {"1101", "76", 1101, 76}
AGGRESSION_CODES = {"86", 86}


async def _ask_yes_no(
    question: str,
    yes_id: str,
    no_id: str,
    state: BOState,
    config: RunnableConfig,
    messages: list,
) -> tuple[str, str | None, bool, bool, bool]:
    """
    Ask yes/no question with buttons (PRESERVED from current implementation).

    Returns:
        (response, redirect_type, declined, confirmed, is_direct_answer)
    """
    msg = create_button_message(body=question, buttons=[(yes_id, "Sim"), (no_id, "Não")])
    msg_json = to_whatsapp_json(msg)

    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=msg_json), HumanMessage(content=response)])

    if redirect_type:
        return response, redirect_type, False, False, False

    declined, confirmed, is_direct = classify_response(response, no_id, yes_id)
    return response, None, declined, confirmed, is_direct


async def _get_description(
    request_msg: str,
    is_direct: bool,
    direct_response: str,
    state: BOState,
    config: RunnableConfig,
    messages: list,
    audio_hint: str | None = None,
) -> tuple[str, str | None]:
    """
    Get description - use direct response or ask (PRESERVED from current implementation).

    Args:
        request_msg: Main description request message.
        audio_hint: Optional audio hint (sent as separate bubble).

    Returns:
        (description, redirect_type)
    """
    if is_direct:
        return direct_response, None

    parts = [{"type": "text", "data": {"body": request_msg}}]
    if audio_hint:
        parts.append({"type": "text", "data": {"body": audio_hint}})
    desc_msg = create_multi_message(parts) if len(parts) > 1 else create_text_message(request_msg)
    desc_json = to_whatsapp_json(desc_msg)

    description, redirect_type, _ = await classify_and_interrupt(
        desc_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=desc_json), HumanMessage(content=description)])

    return description, redirect_type


async def _parse_weapons(description: str, state: BOState, config: RunnableConfig) -> list[dict]:
    """Parse weapon description with LLM (PRESERVED from current implementation)."""
    try:
        llm = resolve_model("parse_weapons", config)
        model = llm.with_structured_output(WeaponAnalysis)
        conversation_history = build_conversation_history(state)

        runnable = wrap_model_scratchpad(
            model,
            object_used_analysis_prompt.format(
                user_response=description,
                conversation_history=conversation_history,
            ),
            node_name="parse_weapons",
        ).with_config(tags=["skip_stream"])

        result = await runnable.ainvoke(state, config)
        if is_redirect(result):
            return []

        analysis = result
        if analysis and analysis.weapons:
            return [w.model_dump() for w in analysis.weapons]
    except Exception as e:
        logger.error(f"[_parse_weapons] Error: {e}", exc_info=True)

    return []


def _extract_all_context(state: BOState) -> dict[str, Any]:
    """
    Extract ALL context sources for unified analysis.

    Returns:
        {
          "current_message": str,
          "conversation_history": str,
          "scratchpad": str,
          "existing_objects": str (JSON)
        }
    """
    messages = state.get("messages", [])

    # Get last user message
    current_message = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # Full conversation history (Bot + User messages)
    conversation_history = build_conversation_history(state)

    # Scratchpad context
    scratchpad = state.get("scratchpad", "")

    # Existing objects (if any)
    objects_info = get_state_field(state, "objects", ObjectsInfo)
    existing_objects_list = []
    for obj in objects_info.items:
        if hasattr(obj, "model_dump"):
            existing_objects_list.append(obj.model_dump())
        elif isinstance(obj, dict):
            existing_objects_list.append(obj)

    existing_objects = (
        json.dumps(existing_objects_list, ensure_ascii=False) if existing_objects_list else "[]"
    )

    return {
        "current_message": current_message,
        "conversation_history": conversation_history,
        "scratchpad": scratchpad,
        "existing_objects": existing_objects,
    }


async def collect_objects_unified_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """
    HYBRID unified node for complete object collection (replaces 7 old nodes).

    PRESERVED UX ELEMENTS:
    - Initial confirmation questions (procedure-based)
    - Separate weapon collection for aggression
    - Decline handling
    - Scratchpad priority

    NEW SIMPLIFIED EXTRACTION:
    - Single unified LLM analysis (replaces 5+ calls)
    - One intelligent follow-up (replaces 3-5 fixed questions)
    - Context-aware extraction from all sources

    Flow:
    1. Check procedure type (aggression vs robbery/theft)
    2. Check scratchpad for existing data (reuse existing logic)
    3. [PRESERVED] Ask initial confirmation question
    4. [PRESERVED] For aggression: collect weapons first
    5. [NEW] Unified extraction of objects from all sources
    6. [NEW] One intelligent follow-up if needed
    7. Update state and finish

    Expected: 3-4 LLM calls, 2-3 user questions (vs 6-10 calls, 4-6 questions)
    """
    logger.info("[collect_objects_unified] Starting unified object collection")

    # ========================================
    # STEP 0: Determine procedure type (PRESERVED)
    # ========================================
    incident = get_state_field(state, "incident", IncidentInfo)
    codes = incident.type_codes or []
    procedure_code = codes[0] if codes else None

    is_aggression = procedure_code in AGGRESSION_CODES
    is_robbery_theft = procedure_code in ROBBERY_THEFT_CODES

    logger.info(
        f"[collect_objects_unified] Procedure: {procedure_code} "
        f"(aggression={is_aggression}, robbery/theft={is_robbery_theft})"
    )

    # ========================================
    # STEP 1: Check scratchpad (PRESERVED)
    # ========================================
    # For now, we skip scratchpad extraction since it's complex
    # and the unified extraction will handle scratchpad content via _extract_all_context
    scratchpad_objects = []
    scratchpad_weapons = []

    messages = []
    final_weapons = list(scratchpad_weapons) if is_aggression else []

    # ========================================
    # STEP 2: For aggression, collect weapons first (PRESERVED)
    # ========================================
    if is_aggression and not scratchpad_weapons:
        # Ask confirmation
        response, redirect, declined, confirmed, is_direct = await _ask_yes_no(
            OBJECT_USED_QUESTION,
            "object_used_yes",
            "object_used_no",
            state,
            config,
            messages,
        )
        if redirect_result := await soft_handle_redirect(redirect, state, messages, config):
            return redirect_result

        if not declined:
            # Get weapon description
            weapon_desc = response if is_direct else None
            if not weapon_desc:
                weapon_desc, redirect = await _get_description(
                    OBJECT_USED_DESCRIPTION_REQUEST, False, "", state, config, messages
                )
                if redirect_result := await soft_handle_redirect(redirect, state, messages, config):
                    return redirect_result

            # Parse weapons (keep existing logic)
            final_weapons = await _parse_weapons(weapon_desc, state, config)
            logger.info(f"[collect_objects_unified] Extracted {len(final_weapons)} weapon(s)")

    # ========================================
    # STEP 3: Ask confirmation about objects (PRESERVED)
    # ========================================
    if not scratchpad_objects:
        # Choose question based on procedure type
        question = OBJECT_STOLEN_QUESTION if is_aggression else OBJECT_QUESTION
        yes_id = "objects_stolen_yes" if is_aggression else "objects_add_yes"
        no_id = "objects_stolen_no" if is_aggression else "objects_add_no"

        response, redirect, declined, confirmed, is_direct = await _ask_yes_no(
            question, yes_id, no_id, state, config, messages
        )
        if redirect_result := await soft_handle_redirect(redirect, state, messages, config):
            return redirect_result

        # If user declined, finish early
        if declined:
            objects_info = get_state_field(state, "objects", ObjectsInfo)
            collection_status = get_state_field(state, "collection", CollectionStatus)
            logger.info("[collect_objects_unified] User declined object collection")
            return {
                "objects": objects_info.model_copy(
                    update={
                        "items": [],
                        "weapons": final_weapons,
                        "collected": True,
                        "details_collected": True,
                    }
                ),
                "collection": collection_status.model_copy(
                    update={
                        "has_objects": True,
                    }
                ),
                "messages": messages,
            }

        # Get description
        description, redirect = await _get_description(
            OBJECT_DESCRIPTION_REQUEST,
            is_direct,
            response,
            state,
            config,
            messages,
            audio_hint=OBJECT_DESCRIPTION_AUDIO_HINT,
        )
        if redirect_result := await soft_handle_redirect(redirect, state, messages, config):
            return redirect_result
    else:
        # Use scratchpad objects directly
        description = ""
        logger.info(
            f"[collect_objects_unified] Using {len(scratchpad_objects)} objects from scratchpad"
        )

    # ========================================
    # STEP 4: UNIFIED EXTRACTION (NEW)
    # ========================================
    # Gather all context sources
    context = _extract_all_context(state)
    # Override current message with description if we just asked
    if description:
        context["current_message"] = description

    logger.info(
        f"[collect_objects_unified] Extracting from all sources - "
        f"msg_len={len(context['current_message'])}, "
        f"history_len={len(context['conversation_history'])}"
    )

    # Single unified extraction (replaces 5+ LLM calls)
    llm = resolve_model("unified_object_extraction", config)
    model = llm.with_structured_output(UnifiedObjectExtraction)

    prompt_text = unified_extraction_prompt.format(**context)

    # Use wrap_model_scratchpad pattern for proper invocation
    runnable = wrap_model_scratchpad(
        model, prompt_text, node_name="unified_object_extraction"
    ).with_config(tags=["skip_stream"])

    try:
        result = await runnable.ainvoke(state, config)
        if is_redirect(result):
            logger.warning("[collect_objects_unified] Redirect detected during extraction")
            extraction = UnifiedObjectExtraction(
                stolen_objects=[],
                weapons=[],
                completeness_level="minimal",
                needs_followup=False,
                extraction_summary="Extraction interrupted by redirect",
                confidence=0.0,
            )
        else:
            extraction = result
    except Exception as e:
        logger.error(f"[collect_objects_unified] LLM extraction failed: {e}")
        # Fallback to minimal extraction
        extraction = UnifiedObjectExtraction(
            stolen_objects=[],
            weapons=[],
            completeness_level="minimal",
            needs_followup=False,
            extraction_summary=f"Extraction failed: {str(e)}",
            confidence=0.0,
        )

    logger.info(
        f"[collect_objects_unified] Initial extraction complete - "
        f"objects={len(extraction.stolen_objects)}, "
        f"weapons={len(extraction.weapons)}, "
        f"completeness={extraction.completeness_level}, "
        f"needs_followup={extraction.needs_followup}, "
        f"confidence={extraction.confidence}"
    )

    # ========================================
    # STEP 5: Update state and finish
    # Follow-up is handled by a separate node (object_followup_node)
    # to keep interrupt positions deterministic across replays.
    # ========================================
    objects_info = get_state_field(state, "objects", ObjectsInfo)
    collection_status = get_state_field(state, "collection", CollectionStatus)

    # Convert extracted objects to dict format
    objects_list = [_obj_to_dict(obj) for obj in extraction.stolen_objects]

    # Use weapons from aggression flow if available, otherwise from extraction
    if final_weapons:
        weapons_list = final_weapons
    else:
        weapons_list = [_obj_to_dict(w) for w in extraction.weapons]

    logger.info(
        f"[collect_objects_unified] Completed - "
        f"extracted {len(objects_list)} objects, {len(weapons_list)} weapons. "
        f"Summary: {extraction.extraction_summary}"
    )

    needs_followup = extraction.needs_followup and bool(extraction.followup_question)

    return {
        "objects": objects_info.model_copy(
            update={
                "items": objects_list,
                "weapons": weapons_list,
                "collected": not needs_followup,
                "details_collected": not needs_followup,
                "needs_followup": needs_followup,
                "followup_question": extraction.followup_question if needs_followup else None,
            }
        ),
        "collection": collection_status.model_copy(
            update={
                "has_objects": len(objects_list) > 0 or len(weapons_list) > 0,
            }
        ),
        "messages": messages,
    }
