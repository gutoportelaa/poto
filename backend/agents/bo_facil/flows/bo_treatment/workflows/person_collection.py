"""Person collection workflow."""

from langgraph.graph import END, StateGraph

from agents.bo_facil.core.states import BOState
from agents.bo_facil.flows.bo_treatment.nodes.person import collect_persons_node

# ===============================
# PERSON COLLECTION SUBGRAPH
# ===============================

# Create subgraph
subgraph = StateGraph(BOState)

# Add single node that handles the entire collection flow
subgraph.add_node("collect_persons", collect_persons_node)

# Set entry point
subgraph.set_entry_point("collect_persons")

subgraph.add_edge("collect_persons", END)

# Compile the subgraph
person_collection_subgraph = subgraph.compile()
person_collection_subgraph.name = "person-collection-subgraph"
