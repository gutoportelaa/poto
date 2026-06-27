import logging
from typing import Literal

from .states import (
    BOState,
    ClassificationInfo,
    CompletionInfo,
    IdentityInfo,
    RedirectInfo,
    get_state_field,
)

logger = logging.getLogger(__name__)


def route_after_service_choice(
    state: BOState,
) -> Literal[
    "bo_treatment", "anonymous_report", "emergency_fallback", "human_handoff", "cancel_flow", "__end__"
]:
    """Route based on service classification type or redirect override."""
    # Check for redirect override first
    redirect = state.get("redirect", RedirectInfo())
    redirect_to = redirect.to if isinstance(redirect, RedirectInfo) else redirect.get("to")

    if redirect_to == "closed":
        logger.info("[route_after_service_choice] Conversation already closed - ending")
        return "__end__"
    elif redirect_to == "emergency":
        logger.info(
            "[route_after_service_choice] Emergency redirect - routing to emergency fallback"
        )
        return "emergency_fallback"
    elif redirect_to == "human":
        logger.info("[route_after_service_choice] Human redirect - routing to human handoff")
        return "human_handoff"
    elif redirect_to == "cancel":
        logger.info("[route_after_service_choice] Cancel redirect - routing to cancel flow")
        return "cancel_flow"

    # Normal service classification routing
    classification = state.get("classification", ClassificationInfo())
    classification_type = (
        classification.type
        if isinstance(classification, ClassificationInfo)
        else classification.get("type")
    )

    if classification_type == "bo_facil":
        route = "bo_treatment"
    elif classification_type == "denuncia_anonima":
        route = "anonymous_report"
    elif classification_type == "atendimento_190":
        route = "emergency_fallback"
    elif classification_type == "atendimento_humano":
        route = "human_handoff"
    else:
        route = "bo_treatment"  # Default to BO treatment

    logger.info(f"[route_after_service_choice] Routing to {route}")
    return route


def route_after_identity_verification(
    state: BOState,
) -> Literal["generate_pdf", "emergency_fallback", "human_handoff", "cancel_flow"]:
    """Route after identity verification with redirect override support."""
    # Check for redirect override first
    redirect = state.get("redirect", RedirectInfo())
    redirect_to = redirect.to if isinstance(redirect, RedirectInfo) else redirect.get("to")

    if redirect_to == "emergency":
        logger.info(
            "[route_after_identity_verification] Emergency redirect - routing to emergency fallback"
        )
        return "emergency_fallback"
    elif redirect_to == "human":
        logger.info("[route_after_identity_verification] Human redirect - routing to human handoff")
        return "human_handoff"
    elif redirect_to == "cancel":
        logger.info("[route_after_identity_verification] Cancel redirect - routing to cancel flow")
        return "cancel_flow"

    # Normal flow continues to PDF generation
    identity = state.get("identity", IdentityInfo())
    if isinstance(identity, IdentityInfo):
        identity_verified = identity.verified
        should_proceed = identity.proceed_without_cpf
    else:
        identity_verified = identity.get("verified", False)
        should_proceed = identity.get("proceed_without_cpf", False)

    logger.info(
        f"[route_after_identity_verification] Identity verified: {identity_verified}, Proceed without CPF: {should_proceed} - routing to generate_pdf"
    )
    return "generate_pdf"


def route_after_bo_treatment(
    state: BOState,
) -> Literal["verify_identity", "emergency_fallback", "human_handoff", "cancel_flow"]:
    """Route after BO treatment with redirect override support."""
    # Check for redirect override first
    redirect = state.get("redirect", RedirectInfo())
    redirect_to = redirect.to if isinstance(redirect, RedirectInfo) else redirect.get("to")

    if redirect_to == "emergency":
        logger.info("[route_after_bo_treatment] Emergency redirect - routing to emergency fallback")
        return "emergency_fallback"
    elif redirect_to == "human":
        logger.info("[route_after_bo_treatment] Human redirect - routing to human handoff")
        return "human_handoff"
    elif redirect_to == "cancel":
        logger.info("[route_after_bo_treatment] Cancel redirect - routing to cancel flow")
        return "cancel_flow"

    # Normal flow continues to identity verification
    logger.info("[route_after_bo_treatment] BO treatment completed - routing to verify_identity")
    return "verify_identity"


def route_after_generate_pdf(
    state: BOState,
) -> Literal[
    "choose_service", "emergency_fallback", "human_handoff", "cancel_flow", "generate_pdf", "__end__"
]:
    """Route after PDF generation - handles 'help more' restart flow."""
    redirect = state.get("redirect", RedirectInfo())
    redirect_to = redirect.to if isinstance(redirect, RedirectInfo) else redirect.get("to")

    if redirect_to == "initial":
        logger.info(
            "[route_after_generate_pdf] User wants more help - routing back to choose_service"
        )
        return "choose_service"
    elif redirect_to == "emergency":
        logger.info("[route_after_generate_pdf] Emergency redirect - routing to emergency fallback")
        return "emergency_fallback"
    elif redirect_to == "human":
        logger.info("[route_after_generate_pdf] Human redirect - routing to human handoff")
        return "human_handoff"
    elif redirect_to == "cancel":
        logger.info("[route_after_generate_pdf] Cancel redirect - routing to cancel flow")
        return "cancel_flow"

    # Self-loop: PDF generated but flow not completed → re-enter for phase 2 (show success + ask)
    completion = get_state_field(state, "completion", CompletionInfo)
    if completion.pdf_generated and not completion.completed:
        logger.info("[route_after_generate_pdf] PDF generated, re-entering for phase 2")
        return "generate_pdf"

    # Normal flow ends
    logger.info("[route_after_generate_pdf] Flow completed - ending")
    return "__end__"


def route_after_anonymous_report(
    state: BOState,
) -> Literal["cancel_flow", "__end__"]:
    """Route after anonymous report — handles cancel redirect."""
    redirect = state.get("redirect", RedirectInfo())
    redirect_to = redirect.to if isinstance(redirect, RedirectInfo) else redirect.get("to")

    if redirect_to == "cancel":
        logger.info("[route_after_anonymous_report] Cancel redirect - routing to cancel flow")
        return "cancel_flow"

    return "__end__"
