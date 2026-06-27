"""Victim data collection workflow.

Collects victim information when the reporter is a third party:
- Victim's name (optional — user can skip)
- Victim's CPF (optional — user can skip)

No retries — each question is asked once. The flow is always progressive.
"""

from langgraph.graph import END, StateGraph

from agents.bo_facil.core.states import BOState, RedirectInfo, get_state_field
from agents.bo_facil.flows.bo_treatment.nodes.victim import (
    collect_victim_cpf_node,
    collect_victim_name_node,
)


def route_after_victim_name(state: BOState) -> str:
    """Route after victim name collection."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"
    return "collect_cpf"


def route_after_victim_cpf(state: BOState) -> str:
    """Route after victim CPF collection."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human"]:
        return "end"
    return "end"


def victim_collection_complete_node(state: BOState, config, store) -> BOState:
    """Mark victim collection as complete."""
    return {
        "has_victim_data_collected": True,
        "messages": [],
    }


# ===============================
# VICTIM COLLECTION SUBGRAPH
# ===============================

subgraph = StateGraph(BOState)

# Add nodes
subgraph.add_node("collect_name", collect_victim_name_node)
subgraph.add_node("collect_cpf", collect_victim_cpf_node)
subgraph.add_node("complete", victim_collection_complete_node)

# Entry point: name first
subgraph.set_entry_point("collect_name")

# Name → CPF (or end on redirect)
subgraph.add_conditional_edges(
    "collect_name",
    route_after_victim_name,
    {
        "collect_cpf": "collect_cpf",
        "end": "complete",
    },
)

# CPF → complete (always)
subgraph.add_conditional_edges(
    "collect_cpf",
    route_after_victim_cpf,
    {
        "end": "complete",
    },
)

subgraph.add_edge("complete", END)

# Compile the subgraph
victim_collection_subgraph = subgraph.compile()
victim_collection_subgraph.name = "victim-collection-subgraph"
