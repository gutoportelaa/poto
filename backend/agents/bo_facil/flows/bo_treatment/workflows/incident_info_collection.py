"""Incident info collection workflow.

Uses a 3-node architecture with graph-managed loop:
- send_initial_messages_node: Sends initial BO messages (1 interrupt)
- extract_incident_info_node: Extracts info from conversation (no interrupt)
- incident_followup_node: Asks follow-up questions (1 interrupt)

The graph edges manage the collection loop, not individual nodes.
"""

from langgraph.graph import END, StateGraph

from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    IncidentInfo,
    RedirectInfo,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.nodes.incident_info import (
    extract_incident_info_node,
    incident_followup_node,
    send_initial_messages_node,
)
from agents.bo_facil.flows.bo_treatment.nodes.incident_info.confirm_non_pi_state import (
    confirm_non_pi_state_node,
)
from core.settings import settings


def should_continue_incident_collection(state: BOState) -> str:
    """Route after extraction — decide if more collection is needed."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ("emergency", "human", "cancel"):
        return "workflow_exit"

    incident = get_state_field(state, "incident", IncidentInfo)
    if incident.non_pi_state_detected:
        return "confirm_non_pi_state"

    collection = get_state_field(state, "collection", CollectionStatus)
    if collection.has_fact and collection.has_datetime and collection.has_location:
        return "end"

    total_attempts = (
        collection.fact_attempts + collection.datetime_attempts + collection.location_attempts
    )
    if total_attempts >= settings.MAX_COLLECTION_ATTEMPTS:
        return "end"

    return "incident_followup"


# ===============================
# INCIDENT INFO COLLECTION SUBGRAPH
# ===============================

# Create subgraph with 3 nodes and graph-managed loop
subgraph = StateGraph(BOState)

# Add nodes
subgraph.add_node("send_initial_messages", send_initial_messages_node)
subgraph.add_node("extract_incident_info", extract_incident_info_node)
subgraph.add_node("incident_followup", incident_followup_node)
subgraph.add_node("confirm_non_pi_state", confirm_non_pi_state_node)

# Set entry point
subgraph.set_entry_point("send_initial_messages")

# Flow:
#   send_initial_messages -> extract_incident_info
#                                  |
#                 +----------------+----------------+
#                 |                                 |
#                END                       incident_followup
#                                                  |
#                                                  v
#                                          extract_incident_info (loop back)

subgraph.add_edge("send_initial_messages", "extract_incident_info")

subgraph.add_conditional_edges(
    "extract_incident_info",
    should_continue_incident_collection,
    {
        "end": END,
        "incident_followup": "incident_followup",
        "confirm_non_pi_state": "confirm_non_pi_state",
        "workflow_exit": END,  # Exit on redirect
    },
)

# After followup, loop back to extraction
subgraph.add_edge("incident_followup", "extract_incident_info")
subgraph.add_edge("confirm_non_pi_state", "extract_incident_info")

# Compile the subgraph
incident_info_collection_subgraph = subgraph.compile()
incident_info_collection_subgraph.name = "incident-info-collection-subgraph"
