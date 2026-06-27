import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agents.bo_facil.core.messages import create_multi_message, to_whatsapp_json
from agents.bo_facil.core.states import BOState, HandoffInfo, RedirectInfo, get_state_field
from agents.bo_facil.flows.emergency.messages import (
    EMERGENCY_DETECTED_PART1,
    EMERGENCY_DETECTED_PART2,
)
from agents.bo_facil.flows.human_handoff.messages import NAME_REQUEST
from core.settings import settings

logger = logging.getLogger(__name__)


async def emergency_fallback_node(state: BOState, config: RunnableConfig) -> BOState:
    """
    Handle emergency situations by showing emergency message and collecting name.

    This follows the Typebot flow:
    1. Show emergency detection message + collect name in single interrupt
    2. Set is_related=True (user came from emergency flow, has context)
    3. Set team_id to 190 emergency team
    4. Workflow routes to human_handoff node which assigns to team
    """
    logger.info("[emergency_fallback_node] Handling emergency situation")

    # Check for custom message in redirect (e.g., from technical error)
    redirect = get_state_field(state, "redirect", RedirectInfo)
    custom_message = redirect.custom_message

    # Build message parts
    if custom_message:
        # Use custom message (technical error) + standard emergency message
        logger.info("[emergency_fallback_node] Using custom message from redirect")
        message_parts = [
            {"type": "text", "data": {"body": custom_message}},
            {"type": "text", "data": {"body": EMERGENCY_DETECTED_PART2}},
            {"type": "text", "data": {"body": NAME_REQUEST}},
        ]
    else:
        # Standard emergency messages
        message_parts = [
            {"type": "text", "data": {"body": EMERGENCY_DETECTED_PART1}},
            {"type": "text", "data": {"body": EMERGENCY_DETECTED_PART2}},
            {"type": "text", "data": {"body": NAME_REQUEST}},
        ]

    combined_msg = create_multi_message(message_parts)
    combined_json = to_whatsapp_json(combined_msg)

    # Collect name via plain interrupt (no reclassification - already in emergency flow)
    name = interrupt(combined_json)

    logger.info(f"[emergency_fallback_node] Name collected: {name}")

    return {
        "messages": [AIMessage(content=combined_json), HumanMessage(content=name)],
        "handoff": HandoffInfo(
            name=name,
            is_related=True,
            team_id=settings.GOVCHAT_TEAM_ID_EMERGENCY,
        ),
        # Clear redirect so handoff doesn't think it's still in emergency redirect
        "redirect": RedirectInfo(),
    }
