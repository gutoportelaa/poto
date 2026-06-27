"""Incident info collection nodes (fact, datetime, location).

Uses a 3-node architecture with graph-managed loop:
- send_initial_messages_node: Sends initial BO messages (1 interrupt)
- extract_incident_info_node: Extracts info from conversation (no interrupt)
- incident_followup_node: Asks follow-up questions (1 interrupt)

The graph edges manage the collection loop, not individual nodes.
"""

from .extraction import extract_incident_info_node
from .followup import incident_followup_node
from .initial import send_initial_messages_node

__all__ = [
    "send_initial_messages_node",
    "extract_incident_info_node",
    "incident_followup_node",
]
