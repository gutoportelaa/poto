"""Inactivity closed workflow - independent graph for closing inactive conversations.

This is a standalone graph that can be invoked independently by the service
orchestrator when a conversation should be closed due to prolonged inactivity.
"""

from langgraph.graph import END, START, StateGraph

from agents.bo_facil.core.states import BOState

from .nodes import inactivity_closed_node

# ===============================
# INACTIVITY CLOSED WORKFLOW
# ===============================

workflow = StateGraph(BOState)

# Add inactivity_closed node
workflow.add_node("inactivity_closed", inactivity_closed_node)

# Simple flow: START -> inactivity_closed -> END
workflow.add_edge(START, "inactivity_closed")
workflow.add_edge("inactivity_closed", END)

# Compile the workflow (checkpointer and store will be set by service.py)
inactivity_closed_agent = workflow.compile()
inactivity_closed_agent.name = "inactivity-closed-agent"
