from langgraph.graph import END, StateGraph

from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    CompletionInfo,
    DamageInfo,
    IncidentInfo,
    RedirectInfo,
    VictimInfo,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.nodes import (
    bo_description_node,
    bo_edit_node,
    bo_treatment_init_node,
    classify_incident_node,
    collect_evidence_node,
    collect_persons_node,
    extract_incident_info_node,
    incident_followup_node,
    object_followup_node,
    send_initial_messages_node,
    should_collect_object_details,
)
from agents.bo_facil.flows.bo_treatment.nodes.incident_info.confirm_non_pi_state import (
    confirm_non_pi_state_node,
)
from agents.bo_facil.flows.bo_treatment.nodes.object.unified import collect_objects_unified_node
from agents.bo_facil.flows.bo_treatment.nodes.victim import (
    analyze_third_party_reporter_node,
)
from agents.bo_facil.flows.bo_treatment.workflows import (
    damage_collection_subgraph,
    victim_collection_subgraph,
)
from core.settings import settings

# Incident type codes that require specific collection phases
OBJECT_RELATED_CODES = {
    "1101",  # Furto (theft)
    "76",  # Roubo (robbery)
    "86",  # Lesão Corporal (aggression)
    "110",  # Dano (property damage)
}

DAMAGE_RELATED_CODES = {
    "131",  # Estelionato (fraud)
    "10061",  # Crime Cibernético (cybercrime)
}


def _route_to_next_collection_phase(state: BOState) -> str:
    """Route to the next collection phase based on incident type.

    Used after victim analysis/collection to determine whether to collect
    objects, damage, or skip directly to persons.

    Returns:
        "collect_objects" - Incident requires object collection
        "collect_damage" - Incident requires damage collection (no objects)
        "collect_persons" - Skip to person collection
    """
    incident = get_state_field(state, "incident", IncidentInfo)
    codes = incident.type_codes or []

    if any(code in OBJECT_RELATED_CODES for code in codes):
        return "collect_objects"

    if any(code in DAMAGE_RELATED_CODES for code in codes):
        return "collect_damage"

    return "collect_persons"


def workflow_exit_node(state: BOState, config) -> BOState:
    """Handle emergency, human handoff, and cancel redirects."""
    redirect = get_state_field(state, "redirect", RedirectInfo)

    if redirect.to == "emergency":
        return {"requires_fallback": True, "messages": []}
    elif redirect.to == "human":
        return {"requires_human_intervention": True, "needs_human_handoff": True, "messages": []}
    elif redirect.to == "cancel":
        return {"messages": []}

    return {"messages": []}


def should_continue_incident_collection(state: BOState) -> str:
    """Route after extraction - decide if more collection is needed.

    This is the main routing function for the incident info collection loop.
    It checks:
    1. Redirects (emergency/human)
    2. If fact collected but not yet classified -> classify immediately
    3. Collection completeness (fact + datetime + location) with classification done
    4. Max attempts limit

    Returns:
        "classify_incident" - Fact collected, needs classification
        "analyze_third_party" - All data collected and classified
        "incident_followup" - More data needed
        "workflow_exit" - Redirect detected
    """
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    collection = get_state_field(state, "collection", CollectionStatus)
    incident = get_state_field(state, "incident", IncidentInfo)

    if incident.non_pi_state_detected:
        return "confirm_non_pi_state"

    # Classify immediately after fact is collected (before location/datetime)
    # This is mandatory for cybercrime detection
    if collection.has_fact and not incident.type_codes:
        return "classify_incident"

    # All fields collected and classified -> proceed to next phase
    if collection.has_fact and collection.has_datetime and collection.has_location:
        return "analyze_third_party"

    # Check max attempts limit
    total_attempts = (
        collection.fact_attempts + collection.datetime_attempts + collection.location_attempts
    )
    if total_attempts >= settings.MAX_COLLECTION_ATTEMPTS:
        # Route to followup which handles the redirect to handoff
        return "incident_followup"

    return "incident_followup"


def route_after_classification(state: BOState) -> str:
    """Route after classification - continue collecting or proceed.

    After classifying the incident type, check if we still need
    location/datetime data before proceeding to the next phase.

    Returns:
        "incident_followup" - Still need location/datetime
        "analyze_third_party" - All data collected, proceed
        "workflow_exit" - Redirect detected
    """
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    collection = get_state_field(state, "collection", CollectionStatus)

    # All fields collected -> proceed
    if collection.has_datetime and collection.has_location:
        return "analyze_third_party"

    # Max attempts reached - route to followup which handles the redirect
    total_attempts = (
        collection.fact_attempts + collection.datetime_attempts + collection.location_attempts
    )
    if total_attempts >= settings.MAX_COLLECTION_ATTEMPTS:
        return "incident_followup"

    return "incident_followup"


def should_collect_victim_data(state: BOState) -> str:
    """Route after third party analysis to victim collection, objects, damage, or persons.

    Routes based on:
    1. Third-party reporter needs victim data collection
    2. Incident type determines next collection phase (objects/damage/persons)
    """
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # If reporter is third party and victim data not yet collected
    victim = get_state_field(state, "victim", VictimInfo)

    if victim.is_third_party and not victim.collected:
        return "collect_victim_data"

    return _route_to_next_collection_phase(state)


def route_after_victim_collection(state: BOState) -> str:
    """Route after victim collection based on incident type."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    return _route_to_next_collection_phase(state)


def should_collect_damage(state: BOState) -> str:
    """Route after object details to damage collection."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    # Skip if damage already collected
    damage = get_state_field(state, "damage", DamageInfo)
    if damage.collected:
        return "collect_persons"

    # Only collect damage for specific crime types that involve financial loss
    incident = get_state_field(state, "incident", IncidentInfo)
    requires_damage = any(code in DAMAGE_RELATED_CODES for code in incident.type_codes)

    if requires_damage:
        return "collect_damage"

    # Skip damage collection for other crimes
    return "collect_persons"


def route_after_damage(state: BOState) -> str:
    """Route after damage collection to person collection."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    return "collect_persons"


def route_after_persons(state: BOState) -> str:
    """Route after person collection to summary."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    return "generate_summary"


def route_after_summary(state: BOState) -> str:
    """Route from summary display to edit or end."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        return "workflow_exit"

    completion = get_state_field(state, "completion", CompletionInfo)
    if completion.completed:
        return "collect_evidence"

    if completion.wants_edit:
        return "bo_edit"

    return "generate_summary"


# ===============================
# BO TREATMENT SUBGRAPH
# ===============================

# Create subgraph
subgraph = StateGraph(BOState)

# Add nodes - incident info collection uses 3 nodes with graph-managed loop
subgraph.add_node("init", bo_treatment_init_node)
subgraph.add_node("send_initial_messages", send_initial_messages_node)
subgraph.add_node("extract_incident_info", extract_incident_info_node)
subgraph.add_node("incident_followup", incident_followup_node)
subgraph.add_node("classify_incident", classify_incident_node)
subgraph.add_node("confirm_non_pi_state", confirm_non_pi_state_node)
subgraph.add_node("analyze_third_party", analyze_third_party_reporter_node)
subgraph.add_node("collect_victim_data", victim_collection_subgraph)
subgraph.add_node("collect_objects", collect_objects_unified_node)
subgraph.add_node("object_followup", object_followup_node)
subgraph.add_node("collect_damage", damage_collection_subgraph)
subgraph.add_node("collect_persons", collect_persons_node)
subgraph.add_node("generate_summary", bo_description_node)
subgraph.add_node("bo_edit", bo_edit_node)
subgraph.add_node("collect_evidence", collect_evidence_node)
subgraph.add_node("workflow_exit", workflow_exit_node)


# Set entry point - init restores biographical data first
subgraph.set_entry_point("init")

# ===============================
# INCIDENT INFO COLLECTION LOOP
# ===============================
# Flow:
#   init -> send_initial_messages -> extract_incident_info
#                                         |
#                  +----------+-----------+-----------+
#                  |          |           |           |
#           classify   incident_followup  analyze  workflow_exit
#              |              |          third_party
#              |              v
#              |       extract_incident_info (loop back)
#              |
#              +---> incident_followup (if location/datetime needed)
#              +---> analyze_third_party (if all done)
#
# Key: classification runs immediately after fact collection,
# before location/datetime, to enable cybercrime detection.

subgraph.add_edge("init", "send_initial_messages")
subgraph.add_edge("send_initial_messages", "extract_incident_info")

# After extraction: classify (fact collected), followup (need more data),
# analyze_third_party (all done), or workflow_exit (redirect)
subgraph.add_conditional_edges(
    "extract_incident_info",
    should_continue_incident_collection,
    {
        "classify_incident": "classify_incident",
        "incident_followup": "incident_followup",
        "analyze_third_party": "analyze_third_party",
        "confirm_non_pi_state": "confirm_non_pi_state",
        "workflow_exit": "workflow_exit",
    },
)

# After followup, loop back to extraction
subgraph.add_edge("incident_followup", "extract_incident_info")

subgraph.add_edge("confirm_non_pi_state", "extract_incident_info")

# ===============================
# REST OF THE WORKFLOW
# ===============================

# After classification: continue collecting location/datetime or proceed
subgraph.add_conditional_edges(
    "classify_incident",
    route_after_classification,
    {
        "incident_followup": "incident_followup",
        "analyze_third_party": "analyze_third_party",
        "workflow_exit": "workflow_exit",
    },
)

# After third party analysis, route based on victim needs and incident type
subgraph.add_conditional_edges(
    "analyze_third_party",
    should_collect_victim_data,
    {
        "collect_victim_data": "collect_victim_data",
        "collect_objects": "collect_objects",
        "collect_damage": "collect_damage",
        "collect_persons": "collect_persons",
        "workflow_exit": "workflow_exit",
    },
)

# After victim collection, route based on incident type
subgraph.add_conditional_edges(
    "collect_victim_data",
    route_after_victim_collection,
    {
        "collect_objects": "collect_objects",
        "collect_damage": "collect_damage",
        "collect_persons": "collect_persons",
        "workflow_exit": "workflow_exit",
    },
)

subgraph.add_conditional_edges(
    "collect_objects",
    should_collect_object_details,
    {
        "object_followup": "object_followup",
        "collect_damage": "collect_damage",
        "collect_persons": "collect_persons",
        "workflow_exit": "workflow_exit",
    },
)

subgraph.add_conditional_edges(
    "object_followup",
    should_collect_damage,
    {
        "collect_damage": "collect_damage",
        "collect_persons": "collect_persons",
        "workflow_exit": "workflow_exit",
    },
)

subgraph.add_conditional_edges(
    "collect_damage",
    route_after_damage,
    {
        "collect_persons": "collect_persons",
        "workflow_exit": "workflow_exit",
    },
)

subgraph.add_conditional_edges(
    "collect_persons",
    route_after_persons,
    {
        "generate_summary": "generate_summary",
        "workflow_exit": "workflow_exit",
    },
)

subgraph.add_conditional_edges(
    "generate_summary",
    route_after_summary,
    {
        "generate_summary": "generate_summary",
        "bo_edit": "bo_edit",
        "collect_evidence": "collect_evidence",
        "workflow_exit": "workflow_exit",
    },
)
subgraph.add_edge("bo_edit", "generate_summary")
subgraph.add_edge("collect_evidence", END)
subgraph.add_edge("workflow_exit", END)

# Compile the subgraph
bo_treatment_subgraph = subgraph.compile()
bo_treatment_subgraph.name = "bo-treatment-subgraph"
