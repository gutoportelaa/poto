"""Object collection nodes.

- unified: Unified object collection node (combines collection and details in single pass)
- followup: Deterministic follow-up node for object detail collection
"""

from .followup import object_followup_node
from .unified import collect_objects_unified_node

__all__ = [
    "collect_objects_unified_node",
    "object_followup_node",
]
