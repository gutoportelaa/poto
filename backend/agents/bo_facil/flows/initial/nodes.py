import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    ClassificationInfo,
    RedirectInfo,
    UserInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import get_last_user_message
from agents.bo_facil.flows.initial.messages import (
    BUTTON_ATENDIMENTO_190,
    BUTTON_BO_FACIL,
    BUTTON_DENUNCIA_ANONIMA,
    MENU_OPTIONS_PROMPT,
    SERVICE_MENU_PROMPT,
    SERVICES_AVAILABLE_MESSAGE,
    WELCOME_MESSAGE,
)
from agents.bo_facil.services.govchat.operations import govchat_resolve

from ...services.classifier import (
    api_classifier_service,
    classify_and_interrupt,
    redirect_to_cancel,
    redirect_to_emergency,
    redirect_to_human,
)

logger = logging.getLogger(__name__)

# Inactivity button IDs — stale clicks after conversation was already closed
_INACTIVITY_BUTTON_IDS = {"inactivity_continue", "inactivity_menu", "inactivity_close"}


async def choose_service_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Interactive service choice with direct button mapping.

    Uses simple conditional logic to map button responses to service types,
    eliminating LLM overhead and improving reliability.
    """
    # Detect stale inactivity button clicks (conversation was already closed by timeout)
    user_message = get_last_user_message(state)
    if user_message and any(btn_id in user_message for btn_id in _INACTIVITY_BUTTON_IDS):
        logger.info(
            f"[choose_service_node] Stale inactivity button detected: '{user_message}' — resolving"
        )
        user = get_state_field(state, "user", UserInfo)
        await govchat_resolve(user.account_id, user.conversation_id)
        farewell_json = to_whatsapp_json(
            create_text_message(
                'Esta conversa já foi encerrada. Sempre que precisar, envie um "oi".'
            )
        )
        return {
            "messages": [HumanMessage(content=user_message), AIMessage(content=farewell_json)],
            "redirect": RedirectInfo(to="closed"),
        }

    # Get current redirect state
    redirect = get_state_field(state, "redirect", RedirectInfo)

    # Clear any stale redirect from previous flow
    if redirect.to:
        logger.info(f"[choose_service_node] Clearing stale redirect: {redirect.to}")

    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")
    if user_message and len(state.get("messages", [])) <= 1:
        try:
            is_emergency, needs_human = await api_classifier_service.classify_both(
                user_message, user_id
            )
            if is_emergency:
                return redirect_to_emergency(state)
            if needs_human:
                return redirect_to_human(state)
        except Exception:
            pass

    # Show service options with multiple messages like Typebot
    message_json = to_whatsapp_json(
        create_multi_message(
            [
                {"type": "text", "data": {"body": WELCOME_MESSAGE}},
                {"type": "text", "data": {"body": SERVICES_AVAILABLE_MESSAGE}},
                {"type": "text", "data": {"body": SERVICE_MENU_PROMPT}},
                {
                    "type": "buttons",
                    "data": {
                        "body": MENU_OPTIONS_PROMPT,
                        "buttons": [
                            ("bo_facil", BUTTON_BO_FACIL),
                            ("atendimento_190", BUTTON_ATENDIMENTO_190),
                            ("denuncia_anonima", BUTTON_DENUNCIA_ANONIMA),
                        ],
                    },
                },
            ]
        )
    )

    user_input, redirect_type, _ = await classify_and_interrupt(message_json, state, config)

    # Handle redirects
    if redirect_type == "emergency":
        return redirect_to_emergency(state)
    if redirect_type == "human":
        return redirect_to_human(state)
    if redirect_type == "cancel":
        return redirect_to_cancel(state)

    # Direct mapping from button IDs to classification types
    classification_type = _map_user_choice_to_service_type(user_input)

    logger.info(
        f"[choose_service_node] User input: '{user_input}' -> classification: '{classification_type}'"
    )

    # Get current classification to preserve other fields
    classification = get_state_field(state, "classification", ClassificationInfo)

    return {
        "classification": classification.model_copy(update={"type": classification_type}),
        "redirect": RedirectInfo(),  # Clear redirect
        "messages": [AIMessage(content=message_json), HumanMessage(content=user_input)],
    }


def _map_user_choice_to_service_type(user_input: str) -> str:
    """Map user input to service classification type based on button content.

    Matches exactly against canonical button labels/IDs (case-insensitive,
    accent-insensitive, whitespace-collapsed). Free-form text that merely
    contains a service keyword as a substring (e.g. a narrative mentioning
    "denúncia") falls through to ``bo_facil`` so users telling their story
    are not silently routed to the anonymous-tip flow.

    Args:
        user_input: User's text input (may be button ID or free text)

    Returns:
        Classification type (defaults to "bo_facil")
    """
    import re
    import unicodedata

    normalized = user_input.lower().strip()
    cleaned = re.sub(r"[^\w\s]", "", normalized)
    cleaned = " ".join(cleaned.split())
    cleaned_ascii = "".join(
        c for c in unicodedata.normalize("NFD", cleaned) if unicodedata.category(c) != "Mn"
    )

    # Atendimento Urgente: button label, button ID, and the explicit "190" code
    if cleaned_ascii in {
        "atendimento urgente",
        "atendimento_190",
        "atendimento 190",
        "ligar 190",
        "190",
    }:
        return "atendimento_190"

    # Denúncia Anônima: button label and button ID
    if cleaned_ascii in {"denuncia anonima", "denuncia_anonima"}:
        return "denuncia_anonima"

    # Default to bo_facil (BO Fácil button label/ID, or any free-form text)
    return "bo_facil"
