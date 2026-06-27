import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    IdentityInfo,
    UserInfo,
    VictimInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import (
    get_redirect_state,
    get_user_memory_manager,
    is_redirect,
    wrap_model,
)
from agents.bo_facil.flows.verify_identity.messages import (
    BIRTH_CITY_INVALID_MESSAGE,
    BIRTH_CITY_PROMPT,
    BIRTH_YEAR_PROMPT,
    BUTTON_CONFIRM_DATA,
    BUTTON_PROCEED_WITHOUT_CPF,
    BUTTON_RETRY_VERIFICATION,
    BUTTON_UPDATE_DATA,
    CPF_INVALID_11_DIGITS_MESSAGE,
    CPF_REQUEST_MESSAGE_1,
    CPF_REQUEST_MESSAGE_2,
    NAME_REQUEST_MESSAGE,
    SECURITY_VALIDATION_PROMPT,
    VERIFICATION_FAILED_MESSAGE,
    VERIFICATION_NOT_COMPLETED_MESSAGE,
    get_data_confirmation_message,
)
from agents.bo_facil.flows.verify_identity.models import (
    BirthYearAnalysis,
    UserDecision,
)
from agents.bo_facil.flows.verify_identity.prompts import (
    BIRTH_YEAR_ANALYSIS_PROMPT,
    USER_DECISION_ANALYSIS_PROMPT,
)
from agents.bo_facil.flows.verify_identity.utils import (
    call_ibioseg_api,
    clean_cpf,
    generate_birth_year_options,
    get_birth_date,
    validate_city_input,
    validate_cpf_format,
)
from agents.bo_facil.services.govchat.operations import govchat_set_attribute
from core.model_routing import resolve_model

from ...services.classifier import (
    classify_and_interrupt,
    redirect_to_cancel,
    redirect_to_emergency,
    redirect_to_human,
)

logger = logging.getLogger(__name__)


async def confirm_previous_data_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Confirm previously collected biographical data with birth year security validation."""
    logger.info("[confirm_previous_data_node] Confirming previous biographical data")

    identity = get_state_field(state, "identity", IdentityInfo)
    cpf_input = identity.cpf_input or ""
    birth_city = identity.birth_city_provided or ""
    biographical_data = identity.biographical_data or {}

    # Mask CPF for display (show first 5 digits + *** + last 2 digits)
    masked_cpf = f"{cpf_input[:5]}***{cpf_input[-2:]}" if len(cpf_input) >= 7 else cpf_input

    # Build confirmation message with CPF and birth city
    message = get_data_confirmation_message(masked_cpf, birth_city if birth_city else None)

    buttons = [("confirm_data", BUTTON_CONFIRM_DATA), ("update_data", BUTTON_UPDATE_DATA)]

    response = create_button_message(message, buttons)
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    # Handle redirects
    if redirect_type == "emergency":
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        return redirect_to_human(state)
    elif redirect_type == "cancel":
        return redirect_to_cancel(state)

    # Analyze response
    normalized_input = user_input.lower().strip()
    confirmed = normalized_input == "confirm_data" or any(
        word in normalized_input for word in ["sim", "confirmar", "continuar", "ok"]
    )

    ai_message_1 = AIMessage(content=consolidated_json)
    human_message_1 = HumanMessage(content=user_input)

    if not confirmed:
        logger.info("[confirm_previous_data_node] User wants to update data")
        return {
            "identity": identity.model_copy(
                update={
                    "verified": False,
                    "data_confirmed": False,
                    "cpf_validated": False,
                    "biographical_data": None,
                }
            ),
            "messages": [ai_message_1, human_message_1],
        }

    # User confirmed - now do security validation with birth year
    logger.info("[confirm_previous_data_node] User confirmed, starting security validation")

    # Extract birth year from biographical data
    birth_date = get_birth_date(biographical_data)
    if not birth_date:
        logger.warning(
            "[confirm_previous_data_node] No birth date in biographical data, skipping validation"
        )
        return {
            "identity": identity.model_copy(update={"verified": True, "data_confirmed": True}),
            "messages": [ai_message_1, human_message_1],
        }

    # Extract year from date string (format: "2001-12-26")
    try:
        birth_year = int(birth_date.split("-")[0])
    except (ValueError, IndexError) as e:
        logger.error(f"[confirm_previous_data_node] Error parsing birth date {birth_date}: {e}")
        return {
            "identity": identity.model_copy(update={"verified": True, "data_confirmed": True}),
            "messages": [ai_message_1, human_message_1],
        }

    # Generate birth year options
    year_options = generate_birth_year_options(birth_year)

    # Create security validation challenge
    security_message = SECURITY_VALIDATION_PROMPT
    year_buttons = [(str(year), str(year)) for year in year_options]

    security_response = create_button_message(security_message, year_buttons)
    security_json = to_whatsapp_json(security_response)

    security_input, security_redirect_type, _ = await classify_and_interrupt(
        security_json, state, config, skip_llm=True
    )

    # Handle redirects
    if security_redirect_type == "emergency":
        return redirect_to_emergency(state)
    elif security_redirect_type == "human":
        return redirect_to_human(state)

    # Analyze birth year response
    model_runnable = wrap_model(
        resolve_model("confirm_previous_data", config).with_structured_output(BirthYearAnalysis),
        BIRTH_YEAR_ANALYSIS_PROMPT.format(
            year_options=year_options, user_message=security_input, correct_year=birth_year
        ),
    ).with_config(tags=["skip_stream"], node_name="confirm_previous_data")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result

    logger.info(
        f"[confirm_previous_data_node] Security validation: selected={analysis.selected_year}, correct={analysis.is_correct}"
    )

    ai_message_2 = AIMessage(content=security_json)
    human_message_2 = HumanMessage(content=security_input)

    if analysis.is_correct:
        logger.info("[confirm_previous_data_node] Security validation passed")
        return {
            "identity": identity.model_copy(update={"verified": True, "data_confirmed": True}),
            "messages": [ai_message_1, human_message_1, ai_message_2, human_message_2],
        }
    else:
        logger.info("[confirm_previous_data_node] Security validation failed - resetting identity")
        return {
            "identity": identity.model_copy(
                update={
                    "verified": False,
                    "data_confirmed": False,
                    "cpf_validated": False,
                    "biographical_data": None,
                }
            ),
            "messages": [ai_message_1, human_message_1, ai_message_2, human_message_2],
        }


async def request_cpf_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Request CPF from user."""
    logger.info("[request_cpf_node] Starting CPF request")

    identity = get_state_field(state, "identity", IdentityInfo)
    attempts = identity.cpf_attempts

    # Consolidate all messages into a single response
    if attempts == 0:
        response = create_multi_message(
            [
                {"type": "text", "data": {"body": CPF_REQUEST_MESSAGE_1}},
                {"type": "text", "data": {"body": CPF_REQUEST_MESSAGE_2}},
            ]
        )
    else:
        response = create_text_message(CPF_INVALID_11_DIGITS_MESSAGE)

    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    # Handle redirects
    if redirect_type == "emergency":
        logger.info("[request_cpf_node] Emergency detected during CPF request")
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        logger.info("[request_cpf_node] Human handoff needed during CPF request")
        return redirect_to_human(state)
    elif redirect_type == "cancel":
        logger.info("[request_cpf_node] Cancel requested during CPF request")
        return redirect_to_cancel(state)

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    logger.info("[request_cpf_node] User provided CPF input")

    return {
        "identity": identity.model_copy(update={"cpf_input": user_input}),
        "messages": [ai_message, human_message],
    }


async def validate_cpf_format_node(state: BOState, config: RunnableConfig) -> BOState:
    """Validate CPF format and clean input"""
    logger.info("[validate_cpf_format_node] Starting CPF format validation")

    identity = get_state_field(state, "identity", IdentityInfo)
    cpf_input = identity.cpf_input or ""
    attempts = identity.cpf_attempts + 1

    # Clean and validate CPF
    cleaned_cpf = clean_cpf(cpf_input)
    is_valid = validate_cpf_format(cleaned_cpf)

    logger.info(f"[validate_cpf_format_node] CPF validation result: {is_valid}")

    return {
        "identity": identity.model_copy(
            update={"cpf_validated": is_valid, "cpf_attempts": attempts, "cpf_input": cleaned_cpf}
        )
    }


async def consult_ibioseg_api_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Consult IBioSeg API for biographical data"""
    logger.info("[consult_ibioseg_api_node] Starting IBioSeg API consultation")

    identity = get_state_field(state, "identity", IdentityInfo)
    cpf = identity.cpf_input or ""

    if not cpf:
        logger.error("[consult_ibioseg_api_node] No CPF provided")
        return {
            "identity": identity.model_copy(update={"biographical_data": {"error": "missing_cpf"}})
        }

    try:
        biographical_data = await call_ibioseg_api(cpf)

        if biographical_data is None:
            logger.warning("[consult_ibioseg_api_node] API returned None")
            biographical_data = {"error": "api_error"}

        logger.info(f"[consult_ibioseg_api_node] API consultation result: {biographical_data}")

        # Save biographical data to persistent store if API call was successful
        if biographical_data and "error" not in biographical_data:
            updated_identity = identity.model_copy(
                update={"biographical_data": biographical_data, "cpf_validated": True}
            )

            # Save to persistent store using UserMemoryManager
            manager = get_user_memory_manager(config, store)
            if manager:
                # Create temporary state for saving
                temp_state = dict(state)
                temp_state["identity"] = updated_identity
                await manager.save_profile_from_state(temp_state)
            logger.info("[consult_ibioseg_api_node] Biographical data saved to persistent store")

            return {"identity": updated_identity}

        return {"identity": identity.model_copy(update={"biographical_data": biographical_data})}

    except Exception as e:
        logger.error(f"[consult_ibioseg_api_node] Error during API call: {str(e)}")
        return {
            "identity": identity.model_copy(update={"biographical_data": {"error": "api_error"}})
        }


async def birth_year_challenge_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Birth year verification challenge"""
    logger.info("[birth_year_challenge_node] Starting birth year challenge")

    identity = get_state_field(state, "identity", IdentityInfo)
    biographical_data = identity.biographical_data or {}

    if "error" in biographical_data:
        logger.error("[birth_year_challenge_node] No valid biographical data available")
        return {"messages": []}

    # Extract birth year from API data
    birth_date = get_birth_date(biographical_data)
    if not birth_date:
        logger.error("[birth_year_challenge_node] No birth date in biographical data")
        return {
            "identity": identity.model_copy(
                update={"biographical_data": {"error": "missing_birth_date"}}
            )
        }

    # Extract year from date string (format: "2001-12-26")
    try:
        birth_year = int(birth_date.split("-")[0])
    except (ValueError, IndexError) as e:
        logger.error(f"[birth_year_challenge_node] Error parsing birth date {birth_date}: {e}")
        return {
            "identity": identity.model_copy(
                update={"biographical_data": {"error": "invalid_birth_date"}}
            )
        }

    # Generate options
    year_options = generate_birth_year_options(birth_year)

    # Create interactive challenge
    message = BIRTH_YEAR_PROMPT
    buttons = [(str(year), str(year)) for year in year_options]

    response = create_button_message(message, buttons)
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    # Handle redirects
    if redirect_type == "emergency":
        logger.info("[birth_year_challenge_node] Emergency detected during birth year challenge")
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        logger.info("[birth_year_challenge_node] Human handoff needed during birth year challenge")
        return redirect_to_human(state)
    elif redirect_type == "cancel":
        logger.info("[birth_year_challenge_node] Cancel requested during birth year challenge")
        return redirect_to_cancel(state)

    # Analyze user response
    model_runnable = wrap_model(
        resolve_model("birth_year_challenge", config).with_structured_output(BirthYearAnalysis),
        BIRTH_YEAR_ANALYSIS_PROMPT.format(
            year_options=year_options, user_message=user_input, correct_year=birth_year
        ),
    ).with_config(tags=["skip_stream"], node_name="birth_year_challenge")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result

    logger.info(
        f"[birth_year_challenge_node] Analysis: selected={analysis.selected_year}, correct={analysis.is_correct}"
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    return {
        "identity": identity.model_copy(
            update={
                "birth_year_selected": analysis.selected_year,
                "verified": analysis.is_correct,
            }
        ),
        "messages": [ai_message, human_message],
    }


async def birth_city_verification_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Birth city collection node - collects and stores city without verification."""
    logger.info("[birth_city_verification_node] Starting birth city collection")

    identity = get_state_field(state, "identity", IdentityInfo)

    # Check if IBioSeg has city data upfront
    biographical_data = identity.biographical_data or {}
    bio = biographical_data if isinstance(biographical_data, dict) else {}
    ibioseg_city = bio.get("birthCity") or bio.get("cityBirth")
    ibioseg_state = bio.get("birthCityState")

    all_messages: list = []
    max_attempts = 3
    user_input = ""

    for attempt in range(max_attempts):
        message = BIRTH_CITY_PROMPT if attempt == 0 else BIRTH_CITY_INVALID_MESSAGE

        response = create_text_message(message)
        consolidated_json = to_whatsapp_json(response)

        user_input, _, _ = await classify_and_interrupt(
            consolidated_json, state, config, skip_llm=True
        )

        all_messages.append(AIMessage(content=consolidated_json))
        all_messages.append(HumanMessage(content=user_input))

        # If IBioSeg has city data, accept any input (we'll use the API data)
        if ibioseg_city:
            break

        # Validate user input looks like a city name
        if validate_city_input(user_input):
            break

        logger.warning(
            f"[birth_city_verification_node] Invalid city input (attempt {attempt + 1}): "
            f"length={len(user_input)}, words={len(user_input.split())}"
        )

    # Determine city value
    if ibioseg_city:
        city = ibioseg_city.strip().title()
        if ibioseg_state:
            city = f"{city} - {ibioseg_state.strip().upper()}"
        logger.info(f"[birth_city_verification_node] Using IBioSeg data: {city}")
    else:
        city = user_input.strip().title()
        # Truncate as safety net after max attempts
        if len(city) > 100:
            city = city[:100]
        logger.info(f"[birth_city_verification_node] Using normalized user input: {city}")

    updated_identity = identity.model_copy(update={"birth_city_provided": city})

    # Save to persistent store using UserMemoryManager
    manager = get_user_memory_manager(config, store)
    if manager:
        temp_state = dict(state)
        temp_state["identity"] = updated_identity
        await manager.save_profile_from_state(temp_state)

    return {"identity": updated_identity, "messages": all_messages}


async def cpf_failure_decision_node(state: BOState, config: RunnableConfig) -> BOState:
    """Handle CPF verification failure and user decision"""
    logger.info("[cpf_failure_decision_node] Handling CPF verification failure")

    identity = get_state_field(state, "identity", IdentityInfo)
    attempts = identity.cpf_attempts

    message = VERIFICATION_NOT_COMPLETED_MESSAGE if attempts >= 2 else VERIFICATION_FAILED_MESSAGE

    buttons = [
        ("retry", BUTTON_RETRY_VERIFICATION),
        ("proceed_without_cpf", BUTTON_PROCEED_WITHOUT_CPF),
    ]

    response = create_button_message(message, buttons)
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    # Handle redirects
    if redirect_type == "emergency":
        logger.info("[cpf_failure_decision_node] Emergency detected during CPF failure decision")
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        logger.info("[cpf_failure_decision_node] Human handoff needed during CPF failure decision")
        return redirect_to_human(state)
    elif redirect_type == "cancel":
        logger.info("[cpf_failure_decision_node] Cancel requested during CPF failure decision")
        return redirect_to_cancel(state)

    # Analyze user decision
    model_runnable = wrap_model(
        resolve_model("cpf_failure_decision", config).with_structured_output(UserDecision),
        USER_DECISION_ANALYSIS_PROMPT.format(user_message=user_input),
    ).with_config(tags=["skip_stream"], node_name="cpf_failure_decision")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    decision = result

    logger.info(f"[cpf_failure_decision_node] User decision: {decision.decision}")

    should_proceed = decision.decision == "proceed_without_cpf"

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if should_proceed:
        updated_identity = identity.model_copy(update={"proceed_without_cpf": True})
    else:
        # Reset identity for retry: clear attempts and validation so user gets a fresh start
        updated_identity = IdentityInfo()

    return {
        "identity": updated_identity,
        "messages": [ai_message, human_message],
    }


async def collect_unverified_name_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Collect full name when identity could not be verified via IBioSeg."""
    logger.info("[collect_unverified_name_node] Starting unverified name collection")

    identity = get_state_field(state, "identity", IdentityInfo)
    victim = get_state_field(state, "victim", VictimInfo)

    response = create_text_message(NAME_REQUEST_MESSAGE)
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    # Handle redirects
    if redirect_type == "emergency":
        logger.info("[collect_unverified_name_node] Emergency detected during name collection")
        return redirect_to_emergency(state)
    elif redirect_type == "human":
        logger.info("[collect_unverified_name_node] Human handoff needed during name collection")
        return redirect_to_human(state)
    elif redirect_type == "cancel":
        logger.info("[collect_unverified_name_node] Cancel requested during name collection")
        return redirect_to_cancel(state)

    name = user_input.strip()
    logger.info(f"[collect_unverified_name_node] Name collected: {name}")

    updated_victim = victim.model_copy(update={"reporter_name": name})
    # biographical_data cleared so transient error dicts don't reach user memory.
    updated_identity = identity.model_copy(
        update={"biographical_data": None, "proceed_without_cpf": True}
    )

    # Flag for human agents: BO will be submitted with a CPF that wasn't
    # verified against IBioSeg or the birth-year/city challenge.
    user = get_state_field(state, "user", UserInfo)
    if user.account_id and user.conversation_id:
        result = await govchat_set_attribute(
            user.account_id, user.conversation_id, "identity_unverified", "true"
        )
        if not result.get("success"):
            logger.warning(
                f"[collect_unverified_name_node] GovChat set_attribute failed: {result.get('error')}"
            )

    manager = get_user_memory_manager(config, store)
    if manager:
        temp_state = dict(state)
        temp_state["victim"] = updated_victim
        temp_state["identity"] = updated_identity
        await manager.save_profile_from_state(temp_state)

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    return {
        "identity": updated_identity,
        "victim": updated_victim,
        "messages": [ai_message, human_message],
    }
