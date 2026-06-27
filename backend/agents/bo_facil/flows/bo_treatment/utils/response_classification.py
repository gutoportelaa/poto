"""Centralized response classification utilities for BO treatment nodes.

Consolidates decline/confirm detection, response classification, and redirect
handling that was previously duplicated across object, person, damage, and
incident_info nodes.
"""

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.bo_facil.core.messages import create_button_message, to_whatsapp_json
from agents.bo_facil.core.states import BOState
from agents.bo_facil.services.classifier import (
    classify_and_interrupt,
    redirect_to_cancel,
    redirect_to_emergency,
    redirect_to_human,
)

logger = logging.getLogger(__name__)

DECLINE_WORDS: set[str] = {"não", "nao", "n", "no"}
CONFIRM_WORDS: set[str] = {"sim", "s", "yes", "confirmar", "confirmo"}

# Matches Portuguese decline phrases in normal and inverted order
DECLINE_PHRASE_RE = re.compile(
    r"n[ãa]o\s+(?:me\s+)?(?:sei|tenho|lembro|possuo|conhe[cç]o)"
    r"|(?:sei|tenho|lembro|possuo|conhe[cç]o)\s+n[ãa]o"
    r"|sem\s+essa\s+informa[cç][ãa]o"
    r"|n[ãa]o\s+sei\s+informar",
    re.IGNORECASE,
)

# "não sei o CEP", "não lembro o número" → user cooperating, not declining
# Negative lookahead excludes "informar" which is a hard decline ("não sei informar")
PARTIAL_DECLINE_RE = re.compile(
    r"n[ãa]o\s+(?:me\s+)?(?:sei|tenho|lembro|possuo|conhe[cç]o)\s+(?!informar\b)\S",
    re.IGNORECASE,
)


def is_decline_response(response: str) -> bool:
    """Check if user's response indicates they don't have the requested info."""
    lower = response.lower().strip()
    if lower in DECLINE_WORDS:
        return True
    if DECLINE_PHRASE_RE.search(lower):
        # "não sei o CEP" has context → not a hard decline
        if PARTIAL_DECLINE_RE.search(lower):
            return False
        return True
    return False


def classify_response(
    response: str,
    no_button_id: str,
    yes_button_id: str,
) -> tuple[bool, bool, bool]:
    """Classify user response as declined, confirmed, or direct answer.

    Returns:
        (declined, confirmed, is_direct_answer)
    """
    lower = response.lower().strip()
    declined = lower in DECLINE_WORDS or no_button_id in response
    confirmed = lower in CONFIRM_WORDS or yes_button_id in response
    is_direct = not declined and not confirmed and len(lower) >= 2
    return declined, confirmed, is_direct


def handle_redirect(
    redirect_type: str | None,
    state: BOState,
    messages: list,
) -> dict[str, Any] | None:
    """Convert redirect type to proper state update with messages.

    Returns None if no redirect needed, otherwise returns the state update dict.
    """
    if not redirect_type:
        return None

    if redirect_type == "emergency":
        result = redirect_to_emergency(state)
        result["messages"] = messages
        return result
    elif redirect_type == "human":
        result = redirect_to_human(state)
        result["messages"] = messages
        return result
    elif redirect_type == "cancel":
        result = redirect_to_cancel(state)
        result["messages"] = messages
        return result

    logger.warning(f"[handle_redirect] Unknown redirect type: {redirect_type}")
    return None


SOFT_REDIRECT_EMERGENCY_MESSAGE = (
    "Parece que você precisa de atendimento de emergência. "
    "Deseja ser transferido para o 190?"
)

SOFT_REDIRECT_HUMAN_MESSAGE = (
    "Deseja ser transferido para um atendente humano?"
)


async def soft_handle_redirect(
    redirect_type: str | None,
    state: BOState,
    messages: list,
    config: RunnableConfig,
) -> dict[str, Any] | None:
    """Like handle_redirect but asks user for confirmation first.

    Shows a confirmation message with buttons before redirecting.
    If user declines, returns None so the caller can continue the normal flow.
    """
    if not redirect_type:
        return None

    if redirect_type == "emergency":
        confirmation_msg = SOFT_REDIRECT_EMERGENCY_MESSAGE
    elif redirect_type == "human":
        confirmation_msg = SOFT_REDIRECT_HUMAN_MESSAGE
    elif redirect_type == "cancel":
        # Cancel confirmation already handled inside classify_and_interrupt
        return handle_redirect(redirect_type, state, messages)
    else:
        logger.warning(f"[soft_handle_redirect] Unknown redirect type: {redirect_type}")
        return None

    msg = create_button_message(
        body=confirmation_msg,
        buttons=[("soft_redirect_yes", "Sim"), ("soft_redirect_no", "Não")],
    )
    msg_json = to_whatsapp_json(msg)
    response, new_redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages = [*messages, AIMessage(content=msg_json), HumanMessage(content=response)]

    # If the confirmation response itself triggers a redirect, apply immediately
    if new_redirect_type:
        return handle_redirect(new_redirect_type, state, messages)

    lower = response.lower().strip()
    wants_redirect = (
        "soft_redirect_yes" in response
        or lower in CONFIRM_WORDS
        or lower == "sim"
    )

    if wants_redirect:
        return handle_redirect(redirect_type, state, messages)

    logger.info(f"[soft_handle_redirect] User declined {redirect_type} redirect, continuing")
    return None
