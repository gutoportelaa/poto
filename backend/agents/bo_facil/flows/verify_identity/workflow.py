from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore

from agents.bo_facil.core.states import BOState, IdentityInfo, RedirectInfo, get_state_field
from agents.bo_facil.flows.verify_identity.nodes import (
    birth_city_verification_node,
    birth_year_challenge_node,
    collect_unverified_name_node,
    confirm_previous_data_node,
    consult_ibioseg_api_node,
    cpf_failure_decision_node,
    request_cpf_node,
    validate_cpf_format_node,
)


def route_from_entry(state: BOState) -> str:
    """Routing from entry point - check if we have previous data to confirm."""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # If we have biographical data and it was validated before, ask for confirmation
    identity = get_state_field(state, "identity", IdentityInfo)
    if identity.biographical_data and identity.cpf_validated and identity.cpf_input:
        return "confirm_previous_data"

    # Otherwise, start fresh with CPF request
    return "request_cpf"


def route_after_data_confirmation(state: BOState) -> str:
    """Routing after user confirms/rejects previous data."""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # If user confirmed data, skip to end (identity verified)
    identity = get_state_field(state, "identity", IdentityInfo)
    if identity.data_confirmed:
        return "end"

    # If user wants to update data, start fresh CPF request
    return "request_cpf"


def route_after_cpf_request(state: BOState) -> str:
    """Routing after CPF collection"""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Always go to validation after collecting CPF
    return "validate_cpf_format"


def route_after_cpf_validation(state: BOState) -> str:
    """Simplified routing after CPF format validation"""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Normal CPF validation flow
    identity = get_state_field(state, "identity", IdentityInfo)

    if identity.cpf_validated:
        return "consult_api"
    elif identity.cpf_attempts >= 2:
        return "cpf_failure_decision"
    else:
        return "request_cpf"


def route_after_api_consultation(state: BOState) -> str:
    """Route after IBioSeg — any error goes to the silent fallback."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    identity = get_state_field(state, "identity", IdentityInfo)
    biographical_data = identity.biographical_data or {}
    if "error" in biographical_data:
        return "collect_unverified_name"

    return "birth_year_challenge"


def route_after_birth_year_challenge(state: BOState) -> str:
    """Simplified routing after birth year challenge"""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Normal birth year challenge flow
    identity = get_state_field(state, "identity", IdentityInfo)

    if identity.verified:
        return "birth_city_verification"
    else:
        return "cpf_failure_decision"


def route_after_birth_city_verification(state: BOState) -> str:
    """Simplified routing after birth city verification"""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Normal birth city verification flow
    identity = get_state_field(state, "identity", IdentityInfo)

    if identity.verified:
        return "end"
    else:
        return "cpf_failure_decision"


def route_after_user_decision(state: BOState) -> str:
    """Simplified routing after user decision on failure"""
    # Check for redirect override first
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Normal user decision flow
    identity = get_state_field(state, "identity", IdentityInfo)

    if identity.proceed_without_cpf:
        return "collect_unverified_name"
    else:
        return "request_cpf"


def workflow_exit_node(state: BOState, config) -> BOState:
    """Generic exit node that handles emergency, human handoff, and cancel based on redirect_to"""
    _ = config  # Mark as used to avoid warnings
    redirect = get_state_field(state, "redirect", RedirectInfo)

    if redirect.to == "emergency":
        return {"requires_fallback": True, "messages": []}
    elif redirect.to == "human":
        return {"requires_human_intervention": True, "needs_human_handoff": True, "messages": []}
    elif redirect.to == "cancel":
        return {"messages": []}
    else:
        # Fallback - should not happen in normal flow
        return {"messages": []}


async def entry_router_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """
    Entry router - restores biographical data before routing.

    This is the SINGLE point where user data is restored from persistent storage.
    All subsequent nodes should rely on the state being already populated.
    """
    import logging

    from agents.bo_facil.core.utils import get_config_info, get_user_memory_manager

    logger = logging.getLogger(__name__)
    logger.info("[entry_router_node] Initializing verify_identity workflow")

    # Get user memory manager for centralized data restoration
    manager = get_user_memory_manager(config, store)

    if manager:
        # Restore biographical data from previous sessions
        restored_fields = await manager.restore_to_state(state)
        user_id, _, _ = get_config_info(config)

        logger.info(f"[entry_router_node] Biographical data restoration for user {user_id}")
        logger.info(f"[entry_router_node] Restored fields: {list(restored_fields.keys())}")
        identity = get_state_field(state, "identity", IdentityInfo)
        logger.info(
            f"[entry_router_node] State after restore: "
            f"cpf_input={'***' if identity.cpf_input else None}, "
            f"cpf_validated={identity.cpf_validated}, "
            f"has_biographical_data={bool(identity.biographical_data)}"
        )
        # Return restored identity so LangGraph propagates the state update
        return {"messages": [], "identity": identity}
    else:
        logger.warning("[entry_router_node] No user_id in config, skipping restoration")

    return {"messages": []}


# Create the verify_identity subgraph
subgraph = StateGraph(BOState)

# Add nodes
subgraph.add_node("entry_router", entry_router_node)
subgraph.add_node("confirm_previous_data", confirm_previous_data_node)
subgraph.add_node("request_cpf", request_cpf_node)
subgraph.add_node("validate_cpf_format", validate_cpf_format_node)
subgraph.add_node("consult_api", consult_ibioseg_api_node)
subgraph.add_node("birth_year_challenge", birth_year_challenge_node)
subgraph.add_node("birth_city_verification", birth_city_verification_node)
subgraph.add_node("cpf_failure_decision", cpf_failure_decision_node)
subgraph.add_node("collect_unverified_name", collect_unverified_name_node)
subgraph.add_node("workflow_exit", workflow_exit_node)

# Set entry point to router
subgraph.set_entry_point("entry_router")

# Add conditional edges with explicit mappings
# Entry router decides between confirming previous data or requesting new CPF
subgraph.add_conditional_edges(
    "entry_router",
    route_from_entry,
    {
        "confirm_previous_data": "confirm_previous_data",
        "request_cpf": "request_cpf",
        "workflow_exit": "workflow_exit",
    },
)

# After data confirmation, either proceed or start fresh
subgraph.add_conditional_edges(
    "confirm_previous_data",
    route_after_data_confirmation,
    {"end": END, "request_cpf": "request_cpf", "workflow_exit": "workflow_exit"},
)

subgraph.add_conditional_edges(
    "request_cpf",
    route_after_cpf_request,
    {"workflow_exit": "workflow_exit", "validate_cpf_format": "validate_cpf_format"},
)
subgraph.add_conditional_edges(
    "validate_cpf_format",
    route_after_cpf_validation,
    {
        "consult_api": "consult_api",
        "cpf_failure_decision": "cpf_failure_decision",
        "request_cpf": "request_cpf",
    },
)
subgraph.add_conditional_edges(
    "consult_api",
    route_after_api_consultation,
    {
        "workflow_exit": "workflow_exit",
        "birth_year_challenge": "birth_year_challenge",
        "collect_unverified_name": "collect_unverified_name",
    },
)
subgraph.add_conditional_edges(
    "birth_year_challenge",
    route_after_birth_year_challenge,
    {
        "workflow_exit": "workflow_exit",
        "birth_city_verification": "birth_city_verification",
        "cpf_failure_decision": "cpf_failure_decision",
    },
)
subgraph.add_conditional_edges(
    "birth_city_verification",
    route_after_birth_city_verification,
    {"workflow_exit": "workflow_exit", "cpf_failure_decision": "cpf_failure_decision", "end": END},
)
subgraph.add_conditional_edges(
    "cpf_failure_decision",
    route_after_user_decision,
    {
        "workflow_exit": "workflow_exit",
        "request_cpf": "request_cpf",
        "collect_unverified_name": "collect_unverified_name",
    },
)

subgraph.add_edge("collect_unverified_name", END)

# Add end edges
subgraph.add_edge("workflow_exit", END)

# Compile the subgraph
verify_identity_subgraph = subgraph.compile()
verify_identity_subgraph.name = "verify-identity-subgraph"
