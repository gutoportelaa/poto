"""Initial messages node - sends BO warning and welcome messages.

This node sends the initial messages when starting BO treatment and waits
for the user's first response. It has a single interrupt point.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_multi_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.messages import (
    BO_WARNING_MESSAGE,
    INITIAL_BO_MESSAGE_1,
    INITIAL_BO_MESSAGE_2,
)
from agents.bo_facil.flows.bo_treatment.utils import soft_handle_redirect
from agents.bo_facil.services.classifier import classify_and_interrupt

logger = logging.getLogger(__name__)


async def send_initial_messages_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """Send initial BO messages and wait for user's first response.

    This node:
    1. Checks if we already have any collected data (skip if resuming)
    2. Sends BO_WARNING_MESSAGE + INITIAL_BO_MESSAGE
    3. Waits for user response via classify_and_interrupt
    4. Returns messages for the conversation

    Returns:
        State update with messages (AIMessage + HumanMessage).
    """
    logger.info("[send_initial_messages] Starting initial messages node")

    collection = get_state_field(state, "collection", CollectionStatus)

    # Check if we already have any data collected (resuming from interrupt)
    if collection.has_fact or collection.has_datetime or collection.has_location:
        logger.info("[send_initial_messages] Data already collected, skipping initial messages")
        return {"messages": []}

    # Check if we already have attempts (meaning we've been here before)
    total_attempts = (
        collection.fact_attempts + collection.datetime_attempts + collection.location_attempts
    )
    if total_attempts > 0:
        logger.info("[send_initial_messages] Attempts > 0, skipping initial messages")
        return {"messages": []}

    # Send initial messages
    initial_msg = create_multi_message(
        [
            {"type": "text", "data": {"body": BO_WARNING_MESSAGE}},
            {"type": "text", "data": {"body": INITIAL_BO_MESSAGE_1}},
            {"type": "text", "data": {"body": INITIAL_BO_MESSAGE_2}},
        ]
    )
    msg_json = to_whatsapp_json(initial_msg)

    # One interrupt - wait for user response
    response, redirect_type, _ = await classify_and_interrupt(msg_json, state, config)

    messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

    if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
        return redirect_result

    logger.info(f"[send_initial_messages] First response received: {response[:100]}...")

    return {"messages": messages}
