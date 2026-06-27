from langgraph.graph import END, StateGraph

from agents.bo_facil.core.routing import (
    route_after_anonymous_report,
    route_after_bo_treatment,
    route_after_generate_pdf,
    route_after_identity_verification,
    route_after_service_choice,
)
from agents.bo_facil.core.states import BOState
from agents.bo_facil.flows.anonymous.nodes import anonymous_report_node
from agents.bo_facil.flows.bo_treatment.workflow import bo_treatment_subgraph
from agents.bo_facil.flows.cancel.nodes import cancel_flow_node
from agents.bo_facil.flows.emergency.nodes import emergency_fallback_node
from agents.bo_facil.flows.human_handoff.nodes import human_handoff_node
from agents.bo_facil.flows.initial.nodes import choose_service_node
from agents.bo_facil.flows.post_bo.nodes import generate_pdf_node
from agents.bo_facil.flows.verify_identity.workflow import verify_identity_subgraph

# ===============================
# MAIN WORKFLOW ORCHESTRATION
# ===============================

workflow = StateGraph(BOState)

# Add main flow nodes
workflow.add_node("emergency_fallback", emergency_fallback_node)
workflow.add_node("choose_service", choose_service_node)
workflow.add_node("anonymous_report", anonymous_report_node)
workflow.add_node("cancel_flow", cancel_flow_node)

# Add subgraphs
workflow.add_node("verify_identity", verify_identity_subgraph)
workflow.add_node("bo_treatment", bo_treatment_subgraph)

# Add standalone nodes
workflow.add_node("generate_pdf", generate_pdf_node)
workflow.add_node("human_handoff", human_handoff_node)

# Set entry point
workflow.set_entry_point("choose_service")

# Add conditional routing
workflow.add_conditional_edges("choose_service", route_after_service_choice)
workflow.add_conditional_edges("verify_identity", route_after_identity_verification)
workflow.add_conditional_edges("bo_treatment", route_after_bo_treatment)

# Emergency fallback leads to human handoff (following Typebot DIRECT flow)
# After showing emergency message, collect name and assign to 190 team
workflow.add_edge("emergency_fallback", "human_handoff")

# Conditional routing for generate_pdf (handles "help more" restart)
workflow.add_conditional_edges("generate_pdf", route_after_generate_pdf)

# Conditional routing for anonymous_report (handles cancel redirect)
workflow.add_conditional_edges("anonymous_report", route_after_anonymous_report)

# End nodes
workflow.add_edge("cancel_flow", END)
workflow.add_edge("human_handoff", END)

# Compile the workflow
bo_facil_agent = workflow.compile()
bo_facil_agent.name = "bo-facil-agent"
