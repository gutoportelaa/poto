"""Workflow for damage data collection.

This subgraph collects financial damage information:
1. Analyzes incident text for damage
2. Confirms with user if damage occurred
3. Collects damage value
4. Collects payment method
5. Optionally collects receipt
"""

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.store.base import BaseStore

from agents.bo_facil.core.states import BOState, DamageInfo, RedirectInfo, get_state_field
from agents.bo_facil.flows.bo_treatment.nodes.damage import (
    analyze_damage_node,
    ask_receipt_node,
    collect_damage_value_node,
    collect_payment_method_node,
    collect_receipt_node,
    confirm_damage_node,
)


def should_continue_after_analysis(state: BOState) -> str:
    """Route after damage analysis."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"

    # Always go to confirmation, even if damage was detected
    return "confirm_damage"


def should_collect_value(state: BOState) -> str:
    """Route after damage confirmation."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"

    # If user confirmed damage, collect value
    damage = get_state_field(state, "damage", DamageInfo)
    if damage.has_damage:
        return "collect_value"

    # No damage - finalize collection
    return "end"  # Goes to finalize via edge mapping


def should_continue_value_collection(state: BOState) -> str:
    """Route after value collection attempt."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"

    damage = get_state_field(state, "damage", DamageInfo)

    # A concrete value was captured → collect the payment method for it
    if damage.value is not None:
        return "collect_payment"

    # Value step settled without a number (declined / unknown / no-damage / max
    # attempts) → finalize, skip payment/receipt. has_damage carries whether a
    # loss is recorded; it no longer drives routing.
    if damage.value_resolved:
        return "end"

    # Otherwise keep collecting (first ask, retry, or re-ask after change_value)
    return "collect_value"


def should_continue_payment_collection(state: BOState) -> str:
    """Route after payment collection."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"

    damage = get_state_field(state, "damage", DamageInfo)

    # Payment informed, or the step is settled (declined) → ask about receipt
    if damage.payment_method is not None or damage.payment_resolved:
        return "ask_receipt"

    # Otherwise keep collecting (first ask, or re-ask after change_payment)
    return "collect_payment"


def should_collect_receipt(state: BOState) -> str:
    """Route after receipt question."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "finalize"

    damage = get_state_field(state, "damage", DamageInfo)
    if damage.wants_receipt:
        return "collect_receipt"

    return "finalize"


async def finalize_damage_collection_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Mark damage collection as complete."""
    import logging

    from agents.bo_facil.core.tools.context_extractor import extract_context_from_history

    logger = logging.getLogger(__name__)

    # Early return if redirect is set (avoids unnecessary LLM calls)
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        logger.info(f"[finalize_damage_collection] Redirect detected ({redirect.to}), skipping")
        return {
            "damage": get_state_field(state, "damage", DamageInfo).model_copy(
                update={"collected": True}
            ),
            "messages": [],
        }

    damage = get_state_field(state, "damage", DamageInfo)
    last_idx = state.get("last_extraction_index", 0)
    messages = state.get("messages", [])
    result = {
        "damage": damage.model_copy(update={"collected": True}),
        "messages": [],
        "last_extraction_index": len(messages),
    }

    if len(messages) > last_idx:
        from agents.bo_facil.core.utils import now_brazil

        existing_scratchpad = state.get("scratchpad", "")
        # Pass existing scratchpad as context for rewriting with damage details
        rewritten_scratchpad = await extract_context_from_history(
            messages,
            start_index=last_idx,
            existing_scratchpad=existing_scratchpad,
            current_datetime=now_brazil().isoformat(),
            config=config,
        )
        if rewritten_scratchpad:
            result["scratchpad"] = rewritten_scratchpad
            logger.info("[finalize_damage_collection] Rewrote scratchpad with damage context")

    return result


# ===============================
# DAMAGE COLLECTION SUBGRAPH
# ===============================

subgraph = StateGraph(BOState)

# Add nodes
subgraph.add_node("analyze_damage", analyze_damage_node)
subgraph.add_node("confirm_damage", confirm_damage_node)
subgraph.add_node("collect_value", collect_damage_value_node)
subgraph.add_node("collect_payment", collect_payment_method_node)
subgraph.add_node("ask_receipt", ask_receipt_node)
subgraph.add_node("collect_receipt", collect_receipt_node)
subgraph.add_node("finalize", finalize_damage_collection_node)

# Set entry point
subgraph.set_entry_point("analyze_damage")

# Add edges
subgraph.add_conditional_edges(
    "analyze_damage",
    should_continue_after_analysis,
    {"confirm_damage": "confirm_damage", "end": END},
)

subgraph.add_conditional_edges(
    "confirm_damage",
    should_collect_value,
    {"collect_value": "collect_value", "end": "finalize"},
)

subgraph.add_conditional_edges(
    "collect_value",
    should_continue_value_collection,
    {"collect_value": "collect_value", "collect_payment": "collect_payment", "end": "finalize"},
)

subgraph.add_conditional_edges(
    "collect_payment",
    should_continue_payment_collection,
    {"collect_payment": "collect_payment", "ask_receipt": "ask_receipt", "end": "finalize"},
)

subgraph.add_conditional_edges(
    "ask_receipt",
    should_collect_receipt,
    {"collect_receipt": "collect_receipt", "finalize": "finalize"},
)

subgraph.add_edge("collect_receipt", "finalize")
subgraph.add_edge("finalize", END)

# Compile the subgraph
damage_collection_subgraph = subgraph.compile()
damage_collection_subgraph.name = "damage-collection-subgraph"
