"""Workflow definitions (LangGraph subgraphs) for bo_treatment.

Each workflow defines a StateGraph with nodes and edges.
Compiled subgraphs are exported for use in the main workflow.
"""

from .damage_collection import damage_collection_subgraph
from .incident_info_collection import incident_info_collection_subgraph
from .person_collection import person_collection_subgraph
from .victim_collection import victim_collection_subgraph

__all__ = [
    "person_collection_subgraph",
    "damage_collection_subgraph",
    "incident_info_collection_subgraph",
    "victim_collection_subgraph",
]
