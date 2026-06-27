"""Human handoff node for transferring users to human agents."""

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agents.bo_facil.core.messages import (
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    HandoffInfo,
    RedirectInfo,
    UserInfo,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.messages import (
    MAX_ATTEMPTS_MESSAGE_1,
    MAX_ATTEMPTS_MESSAGE_2,
)
from agents.bo_facil.flows.human_handoff.messages import (
    DESCRIPTION_REQUEST,
    HANDOFF_INTRO_1,
    HANDOFF_INTRO_2,
    HANDOFF_MESSAGE,
    NAME_REQUEST,
)
from agents.bo_facil.services.govchat.operations import govchat_assign_team
from core.settings import settings

logger = logging.getLogger(__name__)




async def human_handoff_node(state: BOState, config: RunnableConfig) -> BOState:
    """
    Handle human handoff following Typebot DIRECT flow.

    Flow:
    1. Ask for full name
    2. Check if isRelated (came from another flow with context)
       - If yes: skip description
       - If no: ask for brief description
    3. Handoff message
    4. Assign to team (mocked)
    """
    logger.info("[human_handoff_node] Starting human handoff flow")

    messages = []
    handoff = get_state_field(state, "handoff", HandoffInfo)
    user = get_state_field(state, "user", UserInfo)
    redirect = get_state_field(state, "redirect", RedirectInfo)

    # Fast path: max attempts exceeded - combine all messages and skip data collection
    if redirect.reason == "max_attempts_exceeded":
        logger.info("[human_handoff_node] Max attempts exceeded - fast path")
        combined = create_multi_message([
            {"type": "text", "data": {"body": MAX_ATTEMPTS_MESSAGE_1}},
            {"type": "text", "data": {"body": MAX_ATTEMPTS_MESSAGE_2}},
            {"type": "text", "data": {"body": HANDOFF_MESSAGE}},
        ])
        messages.append(AIMessage(content=to_whatsapp_json(combined)))

        team_id = handoff.team_id or settings.GOVCHAT_TEAM_ID_HANDOFF
        result = await govchat_assign_team(user.account_id, user.conversation_id, team_id)
        if not result.get("success"):
            logger.warning(f"[human_handoff_node] GovChat assign_team failed: {result.get('error')}")
        else:
            logger.info(f"[human_handoff_node] Assigned to team {team_id}")

        return {
            "handoff": handoff.model_copy(update={"completed": True}),
            "messages": messages,
        }

    # Step 1: Build intro from origin context + name request
    if not handoff.name:
        # Use custom_message from redirect origin when available, otherwise default intro
        custom = redirect.custom_message
        if isinstance(custom, list):
            intro_parts = [{"type": "text", "data": {"body": msg}} for msg in custom]
        elif custom:
            intro_parts = [{"type": "text", "data": {"body": custom}}]
        else:
            intro_parts = [
                {"type": "text", "data": {"body": HANDOFF_INTRO_1}},
                {"type": "text", "data": {"body": HANDOFF_INTRO_2}},
            ]

        combined_msg = create_multi_message([
            *intro_parts,
            {"type": "text", "data": {"body": NAME_REQUEST}},
        ])
        combined_json = to_whatsapp_json(combined_msg)

        # Plain interrupt - no reclassification in terminal handoff flow
        name = interrupt(combined_json)
        messages.extend([AIMessage(content=combined_json), HumanMessage(content=name)])

        handoff = handoff.model_copy(update={"name": name})
        logger.info(f"[human_handoff_node] Name collected: {name}")

    # Step 2: Check if came from another flow (isRelated)
    is_related = handoff.is_related

    if not is_related and not handoff.description:
        # Collect description
        desc_msg = create_text_message(DESCRIPTION_REQUEST)
        desc_json = to_whatsapp_json(desc_msg)

        # Plain interrupt - no reclassification in terminal handoff flow
        description = interrupt(desc_json)
        messages.extend([AIMessage(content=desc_json), HumanMessage(content=description)])

        handoff = handoff.model_copy(update={"description": description})
        logger.info("[human_handoff_node] Description collected")
    else:
        logger.info("[human_handoff_node] Skipping description (isRelated=true)")

    # Step 3: Handoff message
    handoff_msg = create_text_message(HANDOFF_MESSAGE)
    messages.append(AIMessage(content=to_whatsapp_json(handoff_msg)))

    # Step 4: Assign to team
    conversation_id = user.conversation_id
    account_id = user.account_id
    team_id = handoff.team_id or settings.GOVCHAT_TEAM_ID_HANDOFF  # Default: team 190

    result = await govchat_assign_team(account_id, conversation_id, team_id)
    if not result.get("success"):
        logger.warning(f"[human_handoff_node] GovChat assign_team failed: {result.get('error')}")
    else:
        logger.info(f"[human_handoff_node] Assigned to team {team_id}")

    return {
        "handoff": handoff.model_copy(update={"completed": True}),
        "messages": messages,
    }
