"""Inactivity workflow - independent graph for handling user inactivity.

This is a standalone graph that can be invoked independently by the service
orchestrator when inactivity is detected.
"""

from langgraph.graph import END, START, StateGraph

from agents.bo_facil.core.states import BOState

from .nodes import inactivity_node

# ===============================
# INACTIVITY WORKFLOW
# ===============================

workflow = StateGraph(BOState)

# Add inactivity node
workflow.add_node("inactivity", inactivity_node)

# Simple flow: START -> inactivity -> END
workflow.add_edge(START, "inactivity")
workflow.add_edge("inactivity", END)

# Compile the workflow (checkpointer and store will be set by service.py)
inactivity_agent = workflow.compile()
inactivity_agent.name = "inactivity-agent"
