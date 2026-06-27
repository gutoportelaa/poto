"""Nodes for inactivity closed flow - closes conversation due to inactivity."""

import logging

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import create_multi_message, to_whatsapp_json
from agents.bo_facil.core.states import BOState, UserInfo, get_state_field
from agents.bo_facil.services.govchat.operations import govchat_resolve
from agents.bo_facil.standalone.inactivity_closed.messages import (
    MSG_INACTIVITY_CLOSED_1,
    MSG_INACTIVITY_CLOSED_2,
)

logger = logging.getLogger(__name__)


async def inactivity_closed_node(
    state: BOState, config: RunnableConfig, *, store: BaseStore
) -> BOState:
    """
    Handle conversation closure due to inactivity.

    Flow (matching Typebot "Encerrado - Inatividade"):
    1. Send inactivity closure message
    2. Call toggle_status API to resolve conversation
    """
    logger.info("[inactivity_closed_node] Starting inactivity closure flow")

    user = get_state_field(state, "user", UserInfo)
    conversation_id = user.conversation_id
    account_id = user.account_id

    if not conversation_id or not account_id:
        logger.warning(
            "[inactivity_closed_node] Missing IDs — "
            f"conversation_id={conversation_id}, account_id={account_id}. "
            "govchat_resolve will be skipped."
        )

    # Send closure messages
    closure_msg = create_multi_message([
        {"type": "text", "data": {"body": MSG_INACTIVITY_CLOSED_1}},
        {"type": "text", "data": {"body": MSG_INACTIVITY_CLOSED_2}},
    ])
    closure_json = to_whatsapp_json(closure_msg)

    # Resolve conversation
    await govchat_resolve(account_id, conversation_id)

    logger.info(f"[inactivity_closed_node] Conversation {conversation_id} closed due to inactivity")

    return {
        "messages": [AIMessage(content=closure_json)],
        "conversation_resolved": True,
    }
