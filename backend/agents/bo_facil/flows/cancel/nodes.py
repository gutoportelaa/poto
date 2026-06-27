"""Cancel flow node — farewell and conversation resolution."""

import logging

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import create_multi_message, to_whatsapp_json
from agents.bo_facil.core.states import BOState, CompletionInfo, UserInfo, get_state_field
from agents.bo_facil.services.govchat.operations import govchat_resolve

from .messages import MSG_CANCEL_FAREWELL_1, MSG_CANCEL_FAREWELL_2

logger = logging.getLogger(__name__)


async def cancel_flow_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Send farewell message and resolve GovChat conversation."""
    user = get_state_field(state, "user", UserInfo)

    farewell_msg = create_multi_message([
        {"type": "text", "data": {"body": MSG_CANCEL_FAREWELL_1}},
        {"type": "text", "data": {"body": MSG_CANCEL_FAREWELL_2}},
    ])
    farewell_json = to_whatsapp_json(farewell_msg)

    result = await govchat_resolve(user.account_id, user.conversation_id)
    if not result.get("success"):
        logger.warning(f"[cancel_flow_node] GovChat resolve failed: {result.get('error')}")

    logger.info("[cancel_flow_node] Conversation cancelled and resolved")

    return {
        "completion": CompletionInfo(completed=True),
        "messages": [AIMessage(content=farewell_json)],
    }
