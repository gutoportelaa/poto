"""Nodes for damage data collection flow.

This flow collects financial damage information:
- Whether damage occurred (via LLM analysis or user input)
- Damage value
- Payment method used
- Optional payment receipt attachment
"""

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
from agents.bo_facil.core.states import BOState, DamageInfo, get_state_field
from agents.bo_facil.core.utils import (
    get_redirect_state,
    get_user_memory_manager,
    is_redirect,
    wrap_model,
)
from agents.bo_facil.flows.bo_treatment.messages import (
    DAMAGE_ASK_MESSAGE,
    DAMAGE_DETECTED_CONFIRM_MESSAGE,
    DAMAGE_NO_OPTION,
    DAMAGE_VALUE_CONFIRM_MESSAGE,
    DAMAGE_VALUE_EXAMPLE,
    DAMAGE_VALUE_INVALID_MESSAGE,
    DAMAGE_VALUE_REQUEST_MESSAGE,
    DAMAGE_YES_OPTION,
    PAYMENT_METHOD_EXAMPLES,
    PAYMENT_METHOD_REQUEST_MESSAGE,
    RECEIPT_ASK_MESSAGE,
    RECEIPT_REQUEST_MESSAGE,
    RECEIPT_SKIP_OPTION,
)
from agents.bo_facil.flows.bo_treatment.models import (
    DamageAnalysis,
    DamageConfirmation,
    DamageValueExtraction,
)
from agents.bo_facil.flows.bo_treatment.prompts import (
    confirmation_analysis_prompt,
    damage_analysis_prompt,
    damage_value_extraction_prompt,
)
from agents.bo_facil.flows.bo_treatment.utils import (
    CONFIRM_WORDS,
    DECLINE_WORDS,
    build_conversation_history,
    is_decline_response,
    soft_handle_redirect,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model
from core.settings import settings

logger = logging.getLogger(__name__)


async def _save_profile(state: BOState, config: RunnableConfig, store: BaseStore) -> None:
    """Persist the user profile from state, if a memory manager is configured."""
    manager = get_user_memory_manager(config, store)
    if manager:
        await manager.save_profile_from_state(state)


async def analyze_damage_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Analyze incident text to detect financial damage.

    This node runs at the start of damage collection to detect if there's
    financial damage mentioned in the incident text.
    """
    logger.info("[analyze_damage_node] Analyzing incident text for damage")

    damage = get_state_field(state, "damage", DamageInfo)

    # Get incident text from scratchpad or bo_fact
    incident_text = state.get("scratchpad", "") or state.get("bo_fact", "")

    if not incident_text:
        logger.warning("[analyze_damage_node] No incident text available for analysis")
        return {"messages": []}

    conversation_history = build_conversation_history(state)
    model_runnable = wrap_model(
        resolve_model("analyze_damage", config).with_structured_output(DamageAnalysis),
        damage_analysis_prompt.format(
            conversation_history=conversation_history,
            incident_text=incident_text,
        ),
    ).with_config(tags=["skip_stream"], node_name="analyze_damage")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result

    logger.info(
        f"[analyze_damage_node] Analysis result: has_damage={analysis.has_damage}, "
        f"value={analysis.damage_value}, payment={analysis.payment_method}"
    )

    return {
        "damage": damage.model_copy(
            update={
                "detected": analysis.has_damage,
                "detected_value": analysis.damage_value,
                "detected_payment": analysis.payment_method,
            }
        ),
        "messages": [],
    }


async def confirm_damage_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Confirm with user if there was financial damage.

    If damage was detected in analysis, asks for confirmation.
    If not detected, asks if damage occurred.
    """
    logger.info("[confirm_damage_node] Starting damage confirmation")

    damage = get_state_field(state, "damage", DamageInfo)

    # Choose message based on whether damage was detected
    if damage.detected:
        message = DAMAGE_DETECTED_CONFIRM_MESSAGE
    else:
        message = DAMAGE_ASK_MESSAGE

    response = create_button_message(
        body=message,
        buttons=[
            ("yes_damage", DAMAGE_YES_OPTION),
            ("no_damage", DAMAGE_NO_OPTION),
        ],
    )
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if redirect_result := await soft_handle_redirect(
        redirect_type, state, [ai_message, human_message], config
    ):
        return redirect_result

    # Check button clicks (both button IDs and display text)
    user_input_lower = user_input.lower().strip()

    if user_input_lower == "yes_damage" or user_input_lower in CONFIRM_WORDS:
        has_damage = True
    elif user_input_lower == "no_damage" or user_input_lower in DECLINE_WORDS:
        has_damage = False
    else:
        # Use LLM to analyze text response
        conversation_history = build_conversation_history(state)
        model_runnable = wrap_model(
            resolve_model("damage_confirmation", config).with_structured_output(DamageConfirmation),
            confirmation_analysis_prompt.format(
                user_input=user_input,
                conversation_history=conversation_history,
            ),
        ).with_config(tags=["skip_stream"], node_name="damage_confirmation")

        result = await model_runnable.ainvoke(state, config)
        if is_redirect(result):
            return get_redirect_state(result)
        confirmation = result
        has_damage = confirmation.confirmed

    logger.info(f"[confirm_damage_node] User confirmed damage: {has_damage}")

    # Save to persistent store
    manager = get_user_memory_manager(config, store)
    if manager:
        await manager.save_profile_from_state(state)

    return {
        "damage": damage.model_copy(
            update={
                "has_damage": has_damage,
                "confirmed": True,
            }
        ),
        "messages": [ai_message, human_message],
    }


async def collect_damage_value_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Collect or confirm the damage value."""
    logger.info("[collect_damage_value_node] Starting damage value collection")

    damage = get_state_field(state, "damage", DamageInfo)
    attempts = damage.value_attempts
    max_attempts = settings.MAX_COLLECTION_ATTEMPTS
    detected_value = damage.detected_value

    # If we have a detected value and this is the first attempt, ask for confirmation
    if detected_value is not None and attempts == 0:
        formatted_value = (
            f"{detected_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        message = DAMAGE_VALUE_CONFIRM_MESSAGE.format(value=formatted_value)

        response = create_button_message(
            body=message,
            buttons=[
                ("confirm_value", DAMAGE_YES_OPTION),
                ("change_value", DAMAGE_NO_OPTION),
            ],
        )
    elif attempts > 0:
        # Retry message
        response = create_text_message(DAMAGE_VALUE_INVALID_MESSAGE)
    else:
        # No detected value - ask for input
        response = create_multi_message(
            [
                {"type": "text", "data": {"body": DAMAGE_VALUE_REQUEST_MESSAGE}},
                {"type": "text", "data": {"body": DAMAGE_VALUE_EXAMPLE}},
            ]
        )

    consolidated_json = to_whatsapp_json(response)
    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if redirect_result := await soft_handle_redirect(
        redirect_type, state, [ai_message, human_message], config
    ):
        return redirect_result

    user_input_lower = user_input.lower().strip()
    declined = is_decline_response(user_input)

    def _value_settled(*, no_damage: bool):
        """Finalize the value step without a number.

        Damage was already confirmed upstream. `no_damage=True` means the user
        now states there was no financial loss at all (flip has_damage off);
        otherwise the loss stands with an unknown value.
        """
        update = {"value": None, "value_attempts": 0, "value_resolved": True}
        if no_damage:
            update["has_damage"] = False
        return {
            "damage": damage.model_copy(update=update),
            "messages": [ai_message, human_message],
        }

    # Check if user confirmed detected value (button ID or display text)
    if (
        user_input_lower == "confirm_value" or user_input_lower in CONFIRM_WORDS
    ) and detected_value is not None:
        logger.info(f"[collect_damage_value_node] User confirmed value: {detected_value}")

        await _save_profile(state, config, store)

        return {
            "damage": damage.model_copy(
                update={"value": detected_value, "value_attempts": 0, "value_resolved": True}
            ),
            "messages": [ai_message, human_message],
        }

    # User rejected a DETECTED value → clear it and ask once for the real value.
    # (Only meaningful when there is a detected value to change.)
    if user_input_lower == "change_value" or (declined and detected_value is not None):
        return {
            "damage": damage.model_copy(
                update={"detected_value": None, "value_attempts": 0, "value_resolved": False}
            ),
            "messages": [ai_message, human_message],
        }

    # Hard refusal to state any amount ("não", "não sei informar") → respect it
    # immediately. The damage stays confirmed; we just proceed without a value
    # instead of re-asking forever or erasing the loss.
    if declined:
        logger.info("[collect_damage_value_node] User declined to state the amount; value unknown")
        await _save_profile(state, config, store)
        return _value_settled(no_damage=False)

    # Try to extract a value (or detect an explicit "no damage") from free text
    model_runnable = wrap_model(
        resolve_model("damage_value_extraction", config).with_structured_output(
            DamageValueExtraction
        ),
        damage_value_extraction_prompt.format(user_input=user_input),
    ).with_config(tags=["skip_stream"], node_name="damage_value_extraction")

    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    extraction = result

    # A concrete value wins, even if the model also flagged no_damage.
    if extraction.is_valid and extraction.extracted_value is not None:
        logger.info(f"[collect_damage_value_node] Extracted value: {extraction.extracted_value}")

        await _save_profile(state, config, store)

        return {
            "damage": damage.model_copy(
                update={
                    "value": extraction.extracted_value,
                    "value_attempts": 0,
                    "value_resolved": True,
                }
            ),
            "messages": [ai_message, human_message],
        }

    # Explicit "there was no financial loss" → contradicts the earlier confirm
    if getattr(extraction, "no_damage", False):
        logger.info("[collect_damage_value_node] User stated there was no damage; finalizing")
        await _save_profile(state, config, store)
        return _value_settled(no_damage=True)

    # Couldn't parse a value and it's not an explicit denial → retry up to the cap
    new_attempts = attempts + 1
    logger.warning(
        f"[collect_damage_value_node] Invalid value, attempt {new_attempts}/{max_attempts}"
    )

    if new_attempts >= max_attempts:
        logger.info("[collect_damage_value_node] Max attempts reached; value unknown")
        await _save_profile(state, config, store)
        return _value_settled(no_damage=False)

    return {
        "damage": damage.model_copy(update={"value_attempts": new_attempts}),
        "messages": [ai_message, human_message],
    }


async def collect_payment_method_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Collect the payment method used."""
    logger.info("[collect_payment_method_node] Starting payment method collection")

    damage = get_state_field(state, "damage", DamageInfo)
    detected_payment = damage.detected_payment

    # If we have a detected payment method, ask for confirmation
    if detected_payment:
        message = f"A forma de pagamento utilizada foi {detected_payment}?"
        response = create_button_message(
            body=message,
            buttons=[
                ("confirm_payment", DAMAGE_YES_OPTION),
                ("change_payment", DAMAGE_NO_OPTION),
            ],
        )
    else:
        response = create_multi_message(
            [
                {"type": "text", "data": {"body": PAYMENT_METHOD_REQUEST_MESSAGE}},
                {"type": "text", "data": {"body": PAYMENT_METHOD_EXAMPLES}},
            ]
        )

    consolidated_json = to_whatsapp_json(response)
    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if redirect_result := await soft_handle_redirect(
        redirect_type, state, [ai_message, human_message], config
    ):
        return redirect_result

    user_input_lower = user_input.lower().strip()
    declined = is_decline_response(user_input)

    # Check if user confirmed detected payment (button ID or display text)
    if (
        user_input_lower == "confirm_payment" or user_input_lower in CONFIRM_WORDS
    ) and detected_payment:
        logger.info(f"[collect_payment_method_node] User confirmed payment: {detected_payment}")

        await _save_profile(state, config, store)

        return {
            "damage": damage.model_copy(
                update={"payment_method": detected_payment, "payment_resolved": True}
            ),
            "messages": [ai_message, human_message],
        }

    # User rejected a DETECTED payment → clear it and ask once for the real one.
    # (Only meaningful when there is a detected payment to change.)
    if user_input_lower == "change_payment" or (declined and detected_payment):
        return {
            "damage": damage.model_copy(
                update={"detected_payment": None, "payment_resolved": False}
            ),
            "messages": [ai_message, human_message],
        }

    # User refuses to inform a payment method (no detected value to change) →
    # respect the refusal: skip it and proceed instead of re-asking forever.
    if declined:
        logger.info("[collect_payment_method_node] User declined to inform payment method")
        return {
            "damage": damage.model_copy(update={"payment_method": None, "payment_resolved": True}),
            "messages": [ai_message, human_message],
        }

    # Use user input as payment method
    payment_method = user_input.strip()
    logger.info(f"[collect_payment_method_node] Payment method: {payment_method}")

    await _save_profile(state, config, store)

    return {
        "damage": damage.model_copy(
            update={"payment_method": payment_method, "payment_resolved": True}
        ),
        "messages": [ai_message, human_message],
    }


async def ask_receipt_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Ask if user wants to attach a payment receipt."""
    logger.info("[ask_receipt_node] Asking about receipt attachment")

    damage = get_state_field(state, "damage", DamageInfo)

    response = create_button_message(
        body=RECEIPT_ASK_MESSAGE,
        buttons=[
            ("yes_receipt", DAMAGE_YES_OPTION),
            ("no_receipt", DAMAGE_NO_OPTION),
        ],
    )
    consolidated_json = to_whatsapp_json(response)

    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if redirect_result := await soft_handle_redirect(
        redirect_type, state, [ai_message, human_message], config
    ):
        return redirect_result

    user_input_lower = user_input.lower().strip()

    wants_receipt = user_input_lower == "yes_receipt" or user_input_lower in CONFIRM_WORDS

    if (
        not wants_receipt
        and user_input_lower != "no_receipt"
        and user_input_lower not in DECLINE_WORDS
    ):
        # Analyze text response
        conversation_history = build_conversation_history(state)
        model_runnable = wrap_model(
            resolve_model("damage_confirmation", config).with_structured_output(DamageConfirmation),
            confirmation_analysis_prompt.format(
                user_input=user_input,
                conversation_history=conversation_history,
            ),
        ).with_config(tags=["skip_stream"], node_name="damage_confirmation")

        result = await model_runnable.ainvoke(state, config)
        if is_redirect(result):
            return get_redirect_state(result)
        confirmation = result
        wants_receipt = confirmation.confirmed

    logger.info(f"[ask_receipt_node] User wants to attach receipt: {wants_receipt}")

    return {
        "damage": damage.model_copy(update={"wants_receipt": wants_receipt}),
        "messages": [ai_message, human_message],
    }


async def collect_receipt_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Collect the payment receipt image."""
    logger.info("[collect_receipt_node] Collecting receipt image")

    damage = get_state_field(state, "damage", DamageInfo)

    response = create_button_message(
        body=RECEIPT_REQUEST_MESSAGE,
        buttons=[("skip_receipt", RECEIPT_SKIP_OPTION)],
    )
    consolidated_json = to_whatsapp_json(response)

    # expecting_media=True: the node asked for files, so classify_and_interrupt
    # collects them silently and proceeds when the user finishes (e.g. "pronto")
    # instead of re-asking. The files themselves are auto-attached to the BO by
    # the bridge, so there is nothing to capture here.
    user_input, redirect_type, _ = await classify_and_interrupt(
        consolidated_json, state, config, skip_llm=True, expecting_media=True
    )

    ai_message = AIMessage(content=consolidated_json)
    human_message = HumanMessage(content=user_input)

    if redirect_result := await soft_handle_redirect(
        redirect_type, state, [ai_message, human_message], config
    ):
        return redirect_result

    user_input_lower = user_input.lower().strip()

    if user_input_lower == "skip_receipt" or user_input_lower in DECLINE_WORDS:
        logger.info("[collect_receipt_node] User skipped receipt attachment")
        return {
            "damage": damage.model_copy(update={"receipt_url": None}),
            "messages": [ai_message, human_message],
        }

    # Files (if any) are attached to the BO by the bridge automatically; the
    # flow only prompts and moves on. Nothing to store on the state.
    logger.info("[collect_receipt_node] Receipt step complete")

    manager = get_user_memory_manager(config, store)
    if manager:
        await manager.save_profile_from_state(state)

    return {
        "damage": damage.model_copy(update={"receipt_url": None}),
        "messages": [ai_message, human_message],
    }
