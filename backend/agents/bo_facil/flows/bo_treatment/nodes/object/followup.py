"""Object follow-up node — deterministic interrupt for object detail collection.

Separated from unified.py to keep interrupt positions deterministic across replays.
The unified node persists needs_followup + followup_question in state; this node
reads those values (deterministic) instead of re-running LLM analysis.
"""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import create_text_message, to_whatsapp_json
from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    ObjectsInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import is_redirect, wrap_model_scratchpad
from agents.bo_facil.flows.bo_treatment.models.object import FollowUpObjectDiff
from agents.bo_facil.flows.bo_treatment.nodes.object.unified import (
    _apply_followup_diff,
    _obj_to_dict,
)
from agents.bo_facil.flows.bo_treatment.prompts.object import followup_diff_prompt
from agents.bo_facil.flows.bo_treatment.utils import is_decline_response, soft_handle_redirect
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


def _finalize(
    objects: ObjectsInfo,
    collection: CollectionStatus,
    messages: list,
    items: list[dict] | None = None,
) -> dict[str, Any]:
    """Build the final state update marking objects as collected."""
    update: dict[str, Any] = {
        "collected": True,
        "details_collected": True,
        "needs_followup": False,
        "followup_question": None,
    }
    if items is not None:
        update["items"] = items
    return {
        "objects": objects.model_copy(update=update),
        "collection": collection.model_copy(
            update={"has_objects": bool(objects.items) or bool(objects.weapons)}
        ),
        "messages": messages,
    }


async def object_followup_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """Follow-up node with exactly 1 interrupt.

    Reads followup_question from persisted state (deterministic),
    asks the user, and applies the diff to existing objects.
    """
    objects = get_state_field(state, "objects", ObjectsInfo)
    collection = get_state_field(state, "collection", CollectionStatus)
    messages: list = []

    # Guard: if followup_question is unexpectedly None, finalize without asking
    if not objects.followup_question:
        logger.warning("[object_followup] No followup_question in state, skipping")
        return _finalize(objects, collection, messages)

    logger.info(f"[object_followup] Asking follow-up: {objects.followup_question}")

    # Single deterministic interrupt: ask the persisted follow-up question
    msg_json = to_whatsapp_json(create_text_message(objects.followup_question))
    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=msg_json), HumanMessage(content=response)])

    if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
        logger.info(f"[object_followup] Redirect detected: {redirect_type}")
        return redirect_result

    # Short-circuit: regex decline detection (no LLM needed)
    if is_decline_response(response):
        logger.info("[object_followup] User declined follow-up (regex), skipping")
        return _finalize(objects, collection, messages)

    # Diff-only extraction: lightweight prompt
    baseline = [_obj_to_dict(obj) for obj in objects.items]
    existing_json = json.dumps(baseline, ensure_ascii=False)

    diff_llm = resolve_model("followup_object_diff", config)
    diff_model = diff_llm.with_structured_output(FollowUpObjectDiff)
    diff_prompt_text = followup_diff_prompt.format(
        existing_objects=existing_json,
        followup_question=objects.followup_question,
        followup_response=response,
    )
    diff_runnable = wrap_model_scratchpad(
        diff_model, diff_prompt_text, node_name="followup_object_diff"
    ).with_config(tags=["skip_stream"])

    try:
        diff_result = await diff_runnable.ainvoke(state, config)
        if is_redirect(diff_result):
            logger.warning("[object_followup] Redirect during diff extraction")
        elif diff_result.user_declined_info:
            logger.info("[object_followup] User declined info (LLM detected), skipping")
        else:
            merged = _apply_followup_diff(baseline, diff_result)
            logger.info(
                f"[object_followup] Diff applied - "
                f"updates={len(diff_result.objects_to_update)}, "
                f"adds={len(diff_result.objects_to_add)}, "
                f"summary={diff_result.diff_summary}"
            )
            return _finalize(objects, collection, messages, items=merged)
    except Exception as e:
        logger.error(f"[object_followup] Diff extraction failed: {e}")
        # Keep existing objects (never lost)

    return _finalize(objects, collection, messages)
