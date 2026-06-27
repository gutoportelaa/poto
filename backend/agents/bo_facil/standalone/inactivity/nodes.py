"""Nodes for inactivity flow - handles user inactivity with options."""

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import BOState, UserInfo, get_state_field
from agents.bo_facil.services.classifier import classify_and_interrupt
from agents.bo_facil.services.govchat.operations import govchat_resolve
from agents.bo_facil.standalone.inactivity.messages import (
    BTN_CLOSE,
    BTN_CONTINUE,
    BTN_MENU,
    MSG_FAREWELL,
    MSG_INACTIVITY_WARNING,
    MSG_NOT_UNDERSTOOD,
)

logger = logging.getLogger(__name__)

# Button IDs
ID_CONTINUE = "inactivity_continue"
ID_MENU = "inactivity_menu"
ID_CLOSE = "inactivity_close"

# Max attempts before auto-closing
MAX_ATTEMPTS = 3


def _classify_inactivity_response(response: str) -> str:
    """
    Classify user response to inactivity prompt.

    Returns:
        "continue" | "menu" | "close" | "unknown"
    """
    response_lower = response.lower().strip()

    # Check for button IDs first
    if ID_CONTINUE in response:
        return "continue"
    if ID_MENU in response:
        return "menu"
    if ID_CLOSE in response:
        return "close"

    # Check for text patterns
    if any(word in response_lower for word in ["continuar", "continue", "sim", "yes"]):
        return "continue"
    if any(word in response_lower for word in ["menu", "início", "inicio", "voltar"]):
        return "menu"
    if any(word in response_lower for word in ["encerrar", "fechar", "sair", "não", "nao", "no"]):
        return "close"

    return "unknown"


async def inactivity_node(state: BOState, config: RunnableConfig, *, store: BaseStore) -> BOState:
    """
    Handle user inactivity with options to continue, go to menu, or close.

    Flow (matching Typebot "Inatividade"):
    1. Show inactivity warning with 3 button options
    2. If "Continuar" clicked → redirect to continue current flow
    3. If "Menu" clicked → redirect to menu
    4. If "Encerrar" clicked → farewell message + resolve conversation
    5. If unknown response → show error message and loop back (max 3 attempts)
    """
    logger.info("[inactivity_node] Starting inactivity flow")

    user = get_state_field(state, "user", UserInfo)
    conversation_id = user.conversation_id
    account_id = user.account_id
    messages = []

    # Get current attempt count
    attempt = state.get("inactivity_attempt", 0)

    while attempt < MAX_ATTEMPTS:
        # Show warning message with buttons (or error message on retry)
        if attempt > 0:
            # Show "not understood" message before showing buttons again
            error_msg = create_text_message(MSG_NOT_UNDERSTOOD)
            error_json = to_whatsapp_json(error_msg)
            messages.append(AIMessage(content=error_json))

        # Create button message
        button_msg = create_button_message(
            body=MSG_INACTIVITY_WARNING,
            buttons=[
                (ID_CONTINUE, BTN_CONTINUE),
                (ID_MENU, BTN_MENU),
                (ID_CLOSE, BTN_CLOSE),
            ],
        )
        button_json = to_whatsapp_json(button_msg)

        # Wait for user response
        user_response, redirect_type, _ = await classify_and_interrupt(
            button_json, state, config, skip_llm=True
        )
        messages.extend([AIMessage(content=button_json), HumanMessage(content=user_response)])

        if redirect_type:
            logger.info(f"[inactivity_node] Redirect detected: {redirect_type}")
            return {"redirect_to": redirect_type, "messages": messages, "inactivity_attempt": 0}

        # Classify response
        choice = _classify_inactivity_response(user_response)
        logger.info(f"[inactivity_node] User choice: {choice}")

        if choice == "continue":
            # User chose to continue - handled externally by bridge
            # Just end the flow without special behavior
            logger.info(
                "[inactivity_node] User chose to continue - ending flow (handled by bridge)"
            )
            return {
                "messages": messages,
                "inactivity_attempt": 0,
            }

        elif choice == "menu":
            # User chose menu - handled externally by bridge (new session)
            # Just end the flow without special behavior
            logger.info("[inactivity_node] User chose menu - ending flow (handled by bridge)")
            return {
                "messages": messages,
                "inactivity_attempt": 0,
            }

        elif choice == "close":
            # User wants to close - send farewell and resolve
            logger.info("[inactivity_node] User chose to close")

            farewell_msg = create_text_message(MSG_FAREWELL)
            farewell_json = to_whatsapp_json(farewell_msg)
            messages.append(AIMessage(content=farewell_json))

            # Resolve conversation
            await govchat_resolve(account_id, conversation_id)

            logger.info(f"[inactivity_node] Conversation {conversation_id} closed by user")

            return {
                "messages": messages,
                "inactivity_attempt": 0,
                "conversation_resolved": True,
            }

        else:
            # Unknown response - increment attempt and loop
            attempt += 1
            logger.info(f"[inactivity_node] Unknown response, attempt {attempt}/{MAX_ATTEMPTS}")

    # Max attempts reached - auto close
    logger.info("[inactivity_node] Max attempts reached, auto-closing")

    farewell_msg = create_text_message(MSG_FAREWELL)
    farewell_json = to_whatsapp_json(farewell_msg)
    messages.append(AIMessage(content=farewell_json))

    await govchat_resolve(account_id, conversation_id)

    return {
        "messages": messages,
        "inactivity_attempt": 0,
        "conversation_resolved": True,
    }
