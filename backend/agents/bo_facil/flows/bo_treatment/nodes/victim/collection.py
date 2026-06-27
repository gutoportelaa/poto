"""Nodes for victim data collection flow.

This flow collects information about the victim of the incident:
- Third-party reporter detection (is reporter != victim?)
- Full name (optional)
- CPF (optional)

No retries — each question is asked once. The flow is always progressive.
"""

import logging
import re

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import BOState, IncidentInfo, VictimInfo, get_state_field
from agents.bo_facil.core.utils import (
    get_redirect_state,
    get_user_memory_manager,
    is_redirect,
    wrap_model,
)
from agents.bo_facil.flows.bo_treatment.messages.victim import (
    VICTIM_CPF_INVALID_MESSAGE,
    VICTIM_CPF_REQUEST_MESSAGE,
    VICTIM_CPF_UNKNOWN_OPTION,
    VICTIM_NAME_REQUEST_MESSAGE,
    VICTIM_NAME_UNKNOWN_OPTION,
)
from agents.bo_facil.flows.bo_treatment.models.victim import (
    ThirdPartyReporterAnalysis,
)
from agents.bo_facil.flows.bo_treatment.prompts.victim import (
    third_party_reporter_analysis_prompt,
)
from agents.bo_facil.flows.bo_treatment.utils import build_conversation_history, is_decline_response
from agents.bo_facil.services.classifier import (
    classify_and_interrupt,
    redirect_to_emergency,
    redirect_to_human,
)
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


# =============================================================================
# THIRD PARTY REPORTER ANALYSIS
# =============================================================================


async def analyze_third_party_reporter_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Analyze if the reporter is a third-party (not the victim).

    This node analyzes the incident description (bo_fact) to determine if
    the person making the report is NOT the victim but rather a witness or
    family member reporting for someone else.

    If is_third_party_reporter=True, the workflow should collect victim data
    (name, CPF) separately from the reporter's data.
    """
    logger.info("[analyze_third_party_reporter_node] Starting third-party reporter analysis")

    # Get victim info
    victim = get_state_field(state, "victim", VictimInfo)

    # Skip if already analyzed
    if victim.analyzed:
        logger.info("[analyze_third_party_reporter_node] Already analyzed, skipping")
        return {"messages": []}

    # Get the incident description
    incident = get_state_field(state, "incident", IncidentInfo)
    incident_description = incident.fact or ""
    if not incident_description:
        logger.warning("[analyze_third_party_reporter_node] No incident description available")
        return {
            "victim": victim.model_copy(update={"is_third_party": False, "analyzed": True}),
            "messages": [],
        }

    # Analyze the incident description
    conversation_history = build_conversation_history(state)
    model_runnable = wrap_model(
        resolve_model("analyze_third_party_reporter", config).with_structured_output(
            ThirdPartyReporterAnalysis
        ),
        third_party_reporter_analysis_prompt.format(
            conversation_history=conversation_history,
            incident_description=incident_description,
        ),
    ).with_config(tags=["skip_stream"], node_name="analyze_third_party_reporter")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result

    is_third_party = analysis.is_third_party_reporter and analysis.confidence >= 0.7

    logger.info(
        f"[analyze_third_party_reporter_node] Analysis complete: "
        f"is_third_party={is_third_party}, confidence={analysis.confidence}, "
        f"reasoning={analysis.reasoning}"
    )

    return {
        "victim": victim.model_copy(update={"is_third_party": is_third_party, "analyzed": True}),
        "messages": [],
    }


# =============================================================================
# CPF HELPERS
# =============================================================================


def _clean_cpf(cpf_input: str) -> str:
    """Remove non-digit characters from CPF input."""
    return re.sub(r"\D", "", cpf_input)


def _validate_cpf_format(cpf: str) -> bool:
    """Validate that CPF has exactly 11 digits."""
    return len(cpf) == 11 and cpf.isdigit()


# Matches formatted CPF: 123.456.789-01, 123 456 789 01, 12345678901, etc.
_CPF_PATTERN = re.compile(
    r"(?<!\d)"  # not preceded by digit
    r"\d{3}[.\s]?\d{3}[.\s]?\d{3}[-.\s]?\d{2}"
    r"(?!\d)"  # not followed by digit
)

# Decline phrases specific to CPF context
_CPF_DECLINE_RE = re.compile(
    r"n[ãa]o\s+(?:me\s+)?(?:sei|tenho|lembro|possuo|recordo|consigo)"
    r"|desconhe[cç]o"
    r"|n[ãa]o\s+(?:sei|tenho)\s+(?:o\s+)?cpf"
    r"|(?:sei|tenho|lembro)\s+n[ãa]o"
    r"|sem\s+(?:o\s+)?cpf"
    r"|n[ãa]o\s+(?:vou\s+)?(?:saber|conseguir)",
    re.IGNORECASE,
)


def _extract_cpf_deterministic(user_input: str) -> str | None:
    """Extract CPF from free-text input using regex patterns."""
    match = _CPF_PATTERN.search(user_input)
    if match:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) == 11:
            return digits

    digits = re.sub(r"\D", "", user_input)
    if len(digits) == 11:
        return digits

    return None


def _is_cpf_decline(user_input: str) -> bool:
    """Check if user indicated they don't know/have the CPF."""
    return bool(_CPF_DECLINE_RE.search(user_input.lower()))


# =============================================================================
# NAME COLLECTION (asked first, no retry)
# =============================================================================


async def collect_victim_name_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Collect victim's full name. Asked once, no retry."""
    logger.info("[collect_victim_name_node] Starting victim name collection")

    response = create_button_message(
        body=VICTIM_NAME_REQUEST_MESSAGE,
        buttons=[("unknown_name", VICTIM_NAME_UNKNOWN_OPTION)],
    )
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    if redirect_type == "emergency":
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        return redirect_to_human(state)

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    victim = get_state_field(state, "victim", VictimInfo)
    user_input_lower = user_input.lower().strip()

    # User doesn't know the name
    if user_input_lower == "unknown_name" or is_decline_response(user_input):
        logger.info("[collect_victim_name_node] User doesn't know victim's name")
        return {
            "victim": victim.model_copy(update={"name": None, "name_unknown": True}),
            "messages": [ai_message, human_message],
        }

    name = user_input.strip()
    logger.info(f"[collect_victim_name_node] Victim name collected: {name}")

    state["victim_name"] = name
    manager = get_user_memory_manager(config, store)
    if manager:
        await manager.save_profile_from_state(state)

    return {
        "victim": victim.model_copy(update={"name": name}),
        "messages": [ai_message, human_message],
    }


# =============================================================================
# CPF COLLECTION (asked once, no retry)
# =============================================================================


async def collect_victim_cpf_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Collect victim's CPF. Asked once, no retry."""
    logger.info("[collect_victim_cpf_node] Starting victim CPF collection")

    response = create_button_message(
        body=VICTIM_CPF_REQUEST_MESSAGE,
        buttons=[("unknown_cpf", VICTIM_CPF_UNKNOWN_OPTION)],
    )
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    if redirect_type == "emergency":
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        return redirect_to_human(state)

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    victim = get_state_field(state, "victim", VictimInfo)
    user_input_lower = user_input.lower().strip()

    # User doesn't know the CPF
    if (
        user_input_lower == "unknown_cpf"
        or is_decline_response(user_input)
        or _is_cpf_decline(user_input)
    ):
        logger.info("[collect_victim_cpf_node] User doesn't know victim's CPF")
        return {
            "victim": victim.model_copy(update={"cpf": None, "cpf_unknown": True}),
            "messages": [ai_message, human_message],
        }

    # Try to extract CPF
    cleaned_cpf = _extract_cpf_deterministic(user_input)

    if cleaned_cpf:
        logger.info(f"[collect_victim_cpf_node] Valid CPF collected: {cleaned_cpf[:3]}***")

        state["victim_cpf"] = cleaned_cpf
        manager = get_user_memory_manager(config, store)
        if manager:
            await manager.save_profile_from_state(state)

        return {
            "victim": victim.model_copy(update={"cpf": cleaned_cpf, "cpf_unknown": False}),
            "messages": [ai_message, human_message],
        }

    # Invalid format — retry once
    logger.info("[collect_victim_cpf_node] Invalid CPF format, retrying once")

    retry_response = create_button_message(
        body=f"{VICTIM_CPF_INVALID_MESSAGE}\n\n{VICTIM_CPF_REQUEST_MESSAGE}",
        buttons=[("unknown_cpf", VICTIM_CPF_UNKNOWN_OPTION)],
    )
    retry_json = to_whatsapp_json(retry_response)

    retry_input, retry_redirect, _ = await classify_and_interrupt(
        retry_json, state, config, skip_llm=True
    )

    if retry_redirect == "emergency":
        return redirect_to_emergency(state)
    elif retry_redirect == "human":
        return redirect_to_human(state)

    retry_ai = AIMessage(content=retry_json)
    retry_human = HumanMessage(content=retry_input)

    # Check decline on retry
    if (
        retry_input.lower().strip() == "unknown_cpf"
        or is_decline_response(retry_input)
        or _is_cpf_decline(retry_input)
    ):
        logger.info("[collect_victim_cpf_node] User declined on retry")
        return {
            "victim": victim.model_copy(update={"cpf": None, "cpf_unknown": True}),
            "messages": [ai_message, human_message, retry_ai, retry_human],
        }

    # Try again
    retry_cpf = _extract_cpf_deterministic(retry_input)
    if retry_cpf:
        logger.info(f"[collect_victim_cpf_node] Valid CPF on retry: {retry_cpf[:3]}***")

        state["victim_cpf"] = retry_cpf
        manager = get_user_memory_manager(config, store)
        if manager:
            await manager.save_profile_from_state(state)

        return {
            "victim": victim.model_copy(update={"cpf": retry_cpf, "cpf_unknown": False}),
            "messages": [ai_message, human_message, retry_ai, retry_human],
        }

    # Still invalid — proceed without
    logger.info("[collect_victim_cpf_node] CPF still invalid after retry, proceeding without")
    return {
        "victim": victim.model_copy(update={"cpf": None, "cpf_unknown": True}),
        "messages": [ai_message, human_message, retry_ai, retry_human],
    }
