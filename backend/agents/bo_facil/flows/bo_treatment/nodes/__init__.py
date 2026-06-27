"""Node implementations for bo_treatment flows.

Organized by domain:
- core: Orchestration nodes (init, classification, routing, description, edit)
- object/: Object collection nodes
- person/: Person/suspect collection nodes
- victim/: Victim collection nodes
- damage/: Damage collection nodes
- incident_info/: Fact, datetime, location nodes
- edit/: Edit operation nodes
"""

from .core import (
    bo_description_node,
    bo_edit_node,
    bo_treatment_init_node,
    classify_incident_node,
    collect_evidence_node,
    should_collect_object_details,
)
from .damage import (
    analyze_damage_node,
    ask_receipt_node,
    collect_damage_value_node,
    collect_payment_method_node,
    collect_receipt_node,
    confirm_damage_node,
)
from .incident_info import (
    extract_incident_info_node,
    incident_followup_node,
    send_initial_messages_node,
)
from .object import collect_objects_unified_node, object_followup_node
from .person import collect_persons_node
from .victim import (
    analyze_third_party_reporter_node,
    collect_victim_cpf_node,
    collect_victim_name_node,
)

__all__ = [
    # Core orchestration nodes
    "bo_description_node",
    "bo_edit_node",
    "bo_treatment_init_node",
    "classify_incident_node",
    "collect_evidence_node",
    "should_collect_object_details",
    # Object nodes
    "collect_objects_unified_node",
    "object_followup_node",
    # Person nodes
    "collect_persons_node",
    # Damage nodes
    "analyze_damage_node",
    "ask_receipt_node",
    "collect_damage_value_node",
    "collect_payment_method_node",
    "collect_receipt_node",
    "confirm_damage_node",
    # Incident info nodes
    "send_initial_messages_node",
    "extract_incident_info_node",
    "incident_followup_node",
    # Victim nodes
    "analyze_third_party_reporter_node",
    "collect_victim_cpf_node",
    "collect_victim_name_node",
]
