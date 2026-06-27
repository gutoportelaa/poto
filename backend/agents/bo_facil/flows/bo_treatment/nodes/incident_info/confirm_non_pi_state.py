"""Confirms with the citizen whether to continue when a non-PI state is detected."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    IncidentInfo,
    RedirectInfo,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.messages.common import (
    NON_PI_STATE_QUESTION_TEMPLATE,
)
from agents.bo_facil.flows.bo_treatment.utils import soft_handle_redirect
from agents.bo_facil.services.classifier import classify_and_interrupt

logger = logging.getLogger(__name__)


def _classify_non_pi_choice(response: str | None) -> str:
    """Return 'finalizar' or 'continuar' from a button_id or free text."""
    s = (response or "").strip().lower()
    if not s:
        return "continuar"

    if s == "non_pi_finalizar":
        return "finalizar"
    if s == "non_pi_continuar":
        return "continuar"

    for ch in ",.!?;:":
        s = s.replace(ch, " ")
    tokens = set(s.split())

    if "não" in tokens or "nao" in tokens:
        return "continuar"

    if "finalizar" in tokens:
        return "finalizar"

    return "continuar"


async def confirm_non_pi_state_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """Ask if the citizen wants to continue despite a non-PI state detected.

    Continuar → reset flag, mark acknowledged, return to collection loop.
    Finalizar → set redirect to cancel.
    """
    incident = get_state_field(state, "incident", IncidentInfo)
    detected_state = incident.detected_state or "outro estado"

    body = NON_PI_STATE_QUESTION_TEMPLATE.format(detected_state=detected_state)

    msg = create_button_message(
        body=body,
        buttons=[("non_pi_continuar", "Continuar"), ("non_pi_finalizar", "Finalizar")],
    )
    msg_json = to_whatsapp_json(msg)

    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )

    messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

    if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
        return redirect_result

    choice = _classify_non_pi_choice(response)

    if choice == "finalizar":
        logger.info(
            "[confirm_non_pi_state] User chose Finalizar (state=%s)",
            detected_state,
        )
        return {
            "messages": messages,
            "redirect": RedirectInfo(to="cancel", reason="non_pi_state_finalized"),
        }

    logger.info(
        "[confirm_non_pi_state] User chose Continuar (state=%s), resetting flag",
        detected_state,
    )
    return {
        "messages": messages,
        "incident": incident.model_copy(
            update={
                "non_pi_state_detected": False,
                "detected_state": None,
                "non_pi_state_acknowledged": True,
            }
        ),
    }
