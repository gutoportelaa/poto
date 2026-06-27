"""Follow-up node - asks ONE follow-up question for missing incident info.

This node asks a single follow-up question based on what's missing
(location > datetime > fact priority). It has one interrupt point.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    create_multi_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    CollectionStatus,
    HandoffInfo,
    IncidentInfo,
    RedirectInfo,
    get_state_field,
)
from agents.bo_facil.flows.bo_treatment.messages import (
    DATETIME_FUTURE_REJECTED_MESSAGE,
    DATETIME_QUESTIONS,
    FACT_EXHAUSTED_CONTEXT,
    FACT_EXHAUSTED_QUESTION,
    FOLLOWUP_AUDIO_HINT,
    FOLLOWUP_PREFIX,
    LOCATION_CYBERCRIME_MESSAGE_1,
    LOCATION_CYBERCRIME_MESSAGE_2,
    LOCATION_QUESTION_AT_SITE,
    LOCATION_QUESTION_IF_AT_SITE,
    LOCATION_QUESTION_IF_NOT_AT_SITE,
    LOCATION_QUESTION_IF_NOT_AT_SITE_HINT,
    LOCATION_RETRY_AT_SITE,
    LOCATION_RETRY_CYBERCRIME,
    LOCATION_RETRY_NOT_AT_SITE,
    NON_BO_INTENT_CONTEXTS,
    NON_BO_INTENT_QUESTIONS,
    NON_CRIMINAL_CONTEXT,
    NON_CRIMINAL_QUESTION,
    RESTART_COLLECTION_MESSAGE,
    SOFT_REDIRECT_DECLINE_CONTEXT,
    SOFT_REDIRECT_DECLINE_QUESTION,
    SOFT_REDIRECT_MAX_ATTEMPTS_CONTEXT,
    SOFT_REDIRECT_MAX_ATTEMPTS_QUESTION,
)
from agents.bo_facil.flows.bo_treatment.prompts.common import location_followup_prompt
from agents.bo_facil.flows.bo_treatment.utils import (
    build_conversation_history,
    handle_redirect,
    is_decline_response,
    soft_handle_redirect,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model
from core.settings import settings

logger = logging.getLogger(__name__)


async def _generate_location_followup(state: BOState, config: RunnableConfig) -> str | None:
    """Generate contextual followup question for location using light LLM call."""
    import asyncio

    history = build_conversation_history(state, max_messages=6, compress_bot_messages=False)
    messages = location_followup_prompt.format_messages(conversation_history=history)
    llm = resolve_model("incident_followup", config)
    try:
        result = await asyncio.wait_for(llm.ainvoke(messages), timeout=5.0)
        text = result.content.strip() if result and hasattr(result, "content") else None
        if text and len(text) <= 300:
            return text
        return None
    except Exception as e:
        logger.warning(
            "[_generate_location_followup] LLM call failed (%s: %s), using hardcoded fallback",
            type(e).__name__,
            e,
        )
        return None


def _build_decline_handoff(field: str, messages: list) -> dict[str, Any]:
    """Build handoff redirect when user declines to provide a field."""
    logger.info(f"[incident_followup] User declined {field}, redirecting to handoff")
    return {
        "messages": messages,
        "handoff": HandoffInfo(
            name="Não informado",
            is_related=True,
            team_id=settings.GOVCHAT_TEAM_ID_HANDOFF,
        ),
        "redirect": RedirectInfo(to="human", reason=f"user_declined_{field}"),
    }


def _build_end_redirect(field: str, messages: list) -> dict[str, Any]:
    """Build cancel redirect when user opts to end the conversation cleanly."""
    logger.info(f"[incident_followup] User chose to end {field} flow")
    return {
        "messages": messages,
        "redirect": RedirectInfo(to="cancel", reason=f"user_ended_{field}"),
    }


def _build_followup_message(question: str, attempts: int) -> str:
    """Build followup message with audio hint (1st attempt) or prefix (2nd+).

    Args:
        question: The followup question to ask.
        attempts: Current attempt count for the field (0-based).

    Returns:
        WhatsApp JSON string for the message.
    """
    if attempts == 0:
        # 1st followup: question + audio hint
        msg = create_multi_message(
            [
                {"type": "text", "data": {"body": question}},
                {"type": "text", "data": {"body": FOLLOWUP_AUDIO_HINT}},
            ]
        )
    else:
        # 2nd+ followup: prefix + question
        msg = create_multi_message(
            [
                {"type": "text", "data": {"body": FOLLOWUP_PREFIX}},
                {"type": "text", "data": {"body": question}},
            ]
        )
    return to_whatsapp_json(msg)


async def _soft_redirect_handoff(
    field: str,
    reason: str,
    confirmation_message: str,
    messages: list,
    state: BOState,
    config: RunnableConfig,
    context_message: str | None = None,
) -> dict[str, Any]:
    """Ask user confirmation before transferring to human agent.

    Args:
        context_message: Optional context text sent as a separate bubble
                         before the button message (better WhatsApp UX).
    """
    parts = []
    if context_message:
        parts.append({"type": "text", "data": {"body": context_message}})
    parts.append(
        {
            "type": "buttons",
            "data": {
                "body": confirmation_message,
                "buttons": [("soft_continue", "Continuar"), ("soft_transfer", "Transferir")],
            },
        }
    )
    msg = create_multi_message(parts)
    msg_json = to_whatsapp_json(msg)
    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages = [*messages, AIMessage(content=msg_json), HumanMessage(content=response)]

    if redirect_result := handle_redirect(redirect_type, state, messages):
        return redirect_result

    lower = response.lower().strip()
    wants_transfer = "soft_transfer" in response or "transferir" in lower

    if wants_transfer:
        return _build_decline_handoff(field, messages)

    return {"messages": messages}


async def _soft_redirect_end_or_continue(
    field: str,
    reason: str,
    confirmation_message: str,
    messages: list,
    state: BOState,
    config: RunnableConfig,
    context_message: str | None = None,
) -> dict[str, Any]:
    """Like _soft_redirect_handoff but offers Encerrar instead of Transferir.

    Used when the alternative to continuing is closing the conversation cleanly
    (no human handoff needed) — e.g. BO follow-up requests where the user must
    go to the police station, not be transferred to an attendant.
    """
    parts = []
    if context_message:
        parts.append({"type": "text", "data": {"body": context_message}})
    parts.append(
        {
            "type": "buttons",
            "data": {
                "body": confirmation_message,
                "buttons": [("soft_continue", "Registrar BO"), ("soft_end", "Encerrar")],
            },
        }
    )
    msg = create_multi_message(parts)
    msg_json = to_whatsapp_json(msg)
    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages = [*messages, AIMessage(content=msg_json), HumanMessage(content=response)]

    if redirect_result := handle_redirect(redirect_type, state, messages):
        return redirect_result

    lower = response.lower().strip()
    wants_end = "soft_end" in response or "encerrar" in lower

    if wants_end:
        return _build_end_redirect(field, messages)

    return {"messages": messages}


async def incident_followup_node(
    state: BOState,
    config: RunnableConfig,
    *,
    store: BaseStore,
) -> dict[str, Any]:
    """Ask ONE follow-up question based on what's missing.

    Priority order: fact > location > datetime

    Fact details are collected first so we can classify the incident type
    before asking for location (cybercrime cases need the user's address,
    not the incident location).

    This node:
    1. Checks what's missing (fact, location, datetime)
    2. Asks appropriate question (with buttons for at-site check)
    3. Waits for user response via classify_and_interrupt
    4. Updates attempt counters and user_at_site if applicable
    5. Returns messages for the conversation

    Returns:
        State update with messages and collection updates.
    """
    logger.info("[incident_followup] Starting follow-up node")

    collection = get_state_field(state, "collection", CollectionStatus)
    incident = get_state_field(state, "incident", IncidentInfo)

    # Check if this is a cybercrime case (works correctly now because
    # classification runs immediately after fact collection)
    is_cybercrime = "131" in (incident.type_codes or [])

    messages: list = []
    collection_updates: dict[str, Any] = {}
    max_attempts = settings.MAX_COLLECTION_ATTEMPTS

    # Per-field max: if ANY uncollected field exhausted its attempts → handoff
    # has_* stays false (absolute: only true when data was actually collected)
    uncollected_exhausted = (
        (not collection.has_fact and collection.fact_attempts >= max_attempts)
        or (not collection.has_location and collection.location_attempts >= max_attempts)
        or (not collection.has_datetime and collection.datetime_attempts >= max_attempts)
    )
    if uncollected_exhausted:
        # If user already used "continue" once, force handoff — no more retries
        if collection.continue_used:
            logger.info(
                "[incident_followup] Max attempts exhausted again after continue, "
                "forcing handoff to human agent"
            )
            return _build_decline_handoff(
                "max_attempts_exhausted_after_continue",
                [],
            )

        exhausted_fields = []
        if not collection.has_fact and collection.fact_attempts >= max_attempts:
            exhausted_fields.append(f"fact({collection.fact_attempts})")
        if not collection.has_location and collection.location_attempts >= max_attempts:
            exhausted_fields.append(f"location({collection.location_attempts})")
        if not collection.has_datetime and collection.datetime_attempts >= max_attempts:
            exhausted_fields.append(f"datetime({collection.datetime_attempts})")

        logger.info(
            f"[incident_followup] Field(s) exhausted: {', '.join(exhausted_fields)}, "
            f"asking user before handoff"
        )
        result = await _soft_redirect_handoff(
            "max_attempts",
            "max_attempts_exceeded",
            SOFT_REDIRECT_MAX_ATTEMPTS_QUESTION,
            [],
            state,
            config,
            context_message=SOFT_REDIRECT_MAX_ATTEMPTS_CONTEXT,
        )
        if "redirect" in result:
            return result

        # User chose to continue — give one more chance per exhausted field
        collection_updates["continue_used"] = True
        if not collection.has_fact and collection.fact_attempts >= max_attempts:
            collection_updates["fact_attempts"] = max_attempts - 1
        if not collection.has_location and collection.location_attempts >= max_attempts:
            collection_updates["location_attempts"] = max_attempts - 1
        if not collection.has_datetime and collection.datetime_attempts >= max_attempts:
            collection_updates["datetime_attempts"] = max_attempts - 1

        messages = result["messages"]

    # If collection was just restarted, prepend transition message to next question
    restart_prefix = None
    if collection.collection_restarted:
        restart_prefix = RESTART_COLLECTION_MESSAGE
        collection_updates["collection_restarted"] = False

    # --- Non-BO intent: soft redirect before fact collection ---
    if not collection.has_fact and collection.non_bo_intent_detected:
        intent_type = collection.non_bo_intent_type or "outro"
        context = NON_BO_INTENT_CONTEXTS.get(intent_type, NON_BO_INTENT_CONTEXTS["outro"])
        question = NON_BO_INTENT_QUESTIONS.get(intent_type, NON_BO_INTENT_QUESTIONS["outro"])
        logger.info(
            f"[incident_followup] Non-BO intent detected ({intent_type}), offering soft redirect"
        )

        # acompanhamento: human attendant can't help; offer end (resolve) instead of transfer.
        if intent_type == "acompanhamento":
            result = await _soft_redirect_end_or_continue(
                "non_bo_intent",
                f"non_bo_intent_{intent_type}",
                question,
                [],
                state,
                config,
                context_message=context,
            )
        else:
            result = await _soft_redirect_handoff(
                "non_bo_intent",
                f"non_bo_intent_{intent_type}",
                question,
                [],
                state,
                config,
                context_message=context,
            )
        if "redirect" in result:
            return result
        # User chose to continue — clear flag and proceed to fact collection
        collection_updates["non_bo_intent_detected"] = False
        collection_updates["non_bo_intent_type"] = None
        messages = result["messages"]

    # --- Non-criminal fact: soft redirect before classification ---
    if collection.has_fact and collection.non_registrable_detected:
        logger.info("[incident_followup] Non-criminal fact detected, offering soft redirect")

        result = await _soft_redirect_handoff(
            "non_criminal",
            "non_criminal_fact",
            NON_CRIMINAL_QUESTION,
            [],
            state,
            config,
            context_message=NON_CRIMINAL_CONTEXT,
        )
        if "redirect" in result:
            return result
        # User chose to continue — clear flag, proceed to classification
        collection_updates["non_registrable_detected"] = False
        messages = result["messages"]

    # Priority: fact > location > datetime
    # Fact must be collected first so classification can determine cybercrime
    if not collection.has_fact:
        # Fast-exit: after max-1 failed fact attempts, offer handoff directly
        if collection.fact_attempts >= max_attempts - 1:
            logger.info("[incident_followup] Fact attempts exhausted (2), offering fast-exit")
            result = await _soft_redirect_handoff(
                "fact",
                "fact_collection_exhausted",
                FACT_EXHAUSTED_QUESTION,
                [],
                state,
                config,
                context_message=FACT_EXHAUSTED_CONTEXT,
            )
            if "redirect" in result:
                return result
            messages = result["messages"]

        # Ask for more fact details using LLM-generated question if available
        question = (
            collection.fact_followup_question or "Pode descrever com mais detalhes o que aconteceu?"
        )
        logger.info("[incident_followup] Asking for more fact details")

        msg_json = _build_followup_message(question, collection.fact_attempts)
        if restart_prefix:
            combined = create_multi_message(
                [
                    {"type": "text", "data": {"body": restart_prefix}},
                    {"type": "text", "data": {"body": question}},
                ]
            )
            msg_json = to_whatsapp_json(combined)
            restart_prefix = None

        response, redirect_type, _ = await classify_and_interrupt(
            msg_json, state, config, skip_llm=True
        )
        messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

        if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
            return redirect_result

        if is_decline_response(response):
            result = await _soft_redirect_handoff(
                "fact",
                "user_declined_fact",
                SOFT_REDIRECT_DECLINE_QUESTION,
                messages,
                state,
                config,
                context_message=SOFT_REDIRECT_DECLINE_CONTEXT,
            )
            if "redirect" in result:
                return result
            messages = result["messages"]

        # Increment fact attempts
        collection_updates["fact_attempts"] = collection.fact_attempts + 1

    elif not collection.has_location:
        # Location collection logic (cybercrime detection now works)
        if collection.user_at_site is None and not is_cybercrime:
            # First ask if user is at site (buttons)
            logger.info("[incident_followup] Asking if user is at incident site")
            body = LOCATION_QUESTION_AT_SITE
            if restart_prefix:
                body = f"{restart_prefix}\n\n{body}"
                restart_prefix = None
            msg = create_button_message(
                body=body,
                buttons=[("sim_no_local", "Sim"), ("nao_no_local", "Não")],
            )
            msg_json = to_whatsapp_json(msg)

            response, redirect_type, _ = await classify_and_interrupt(
                msg_json, state, config, skip_llm=True
            )
            messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

            if redirect_result := await soft_handle_redirect(
                redirect_type, state, messages, config
            ):
                return redirect_result

            # Classify response for user_at_site
            lower = response.lower().strip()
            is_at_site = "sim" in lower or "estou" in lower or "sim_no_local" in response
            collection_updates["user_at_site"] = is_at_site

            logger.info(f"[incident_followup] User at site: {is_at_site}")

        else:
            # Already know if at site, or cybercrime - ask for specific location
            attempts = collection.location_attempts
            if attempts == 0:
                # First attempt: use the standard question
                if is_cybercrime:
                    question = f"{LOCATION_CYBERCRIME_MESSAGE_1}\n\n{LOCATION_CYBERCRIME_MESSAGE_2}"
                elif collection.user_at_site:
                    question = LOCATION_QUESTION_IF_AT_SITE
                else:
                    question = LOCATION_QUESTION_IF_NOT_AT_SITE
            else:
                # Retry: generate contextual question from conversation history
                question = await _generate_location_followup(state, config)
                if not question:
                    # Fallback to hardcoded retry messages
                    retry_idx = min(attempts - 1, len(LOCATION_RETRY_AT_SITE) - 1)
                    if is_cybercrime:
                        question = LOCATION_RETRY_CYBERCRIME[retry_idx]
                    elif collection.user_at_site:
                        question = LOCATION_RETRY_AT_SITE[retry_idx]
                    else:
                        question = LOCATION_RETRY_NOT_AT_SITE[retry_idx]

            logger.info("[incident_followup] Asking for location details")
            # Build location message — add hint for not-at-site first attempt
            extra_hint = (
                LOCATION_QUESTION_IF_NOT_AT_SITE_HINT
                if question == LOCATION_QUESTION_IF_NOT_AT_SITE and attempts == 0
                else None
            )
            if restart_prefix or extra_hint:
                parts = []
                if restart_prefix:
                    parts.append({"type": "text", "data": {"body": restart_prefix}})
                    restart_prefix = None
                parts.append({"type": "text", "data": {"body": question}})
                if extra_hint:
                    parts.append({"type": "text", "data": {"body": extra_hint}})
                if attempts == 0 and not restart_prefix:
                    parts.append({"type": "text", "data": {"body": FOLLOWUP_AUDIO_HINT}})
                msg_json = to_whatsapp_json(create_multi_message(parts))
            else:
                msg_json = _build_followup_message(question, collection.location_attempts)

            response, redirect_type, _ = await classify_and_interrupt(
                msg_json, state, config, skip_llm=True
            )
            messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

            if redirect_result := await soft_handle_redirect(
                redirect_type, state, messages, config
            ):
                return redirect_result

            if is_decline_response(response):
                result = await _soft_redirect_handoff(
                    "location",
                    "user_declined_location",
                    SOFT_REDIRECT_DECLINE_QUESTION,
                    messages,
                    state,
                    config,
                )
                if "redirect" in result:
                    return result
                messages = result["messages"]

            collection_updates["location_attempts"] = collection.location_attempts + 1

    elif not collection.has_datetime:
        # Ask for datetime with varied messages per attempt
        logger.info("[incident_followup] Asking for datetime")
        if collection.datetime_future_rejected:
            question = DATETIME_FUTURE_REJECTED_MESSAGE
            collection_updates["datetime_future_rejected"] = False
        else:
            dt_idx = min(collection.datetime_attempts, len(DATETIME_QUESTIONS) - 1)
            question = DATETIME_QUESTIONS[dt_idx]
        msg_json = _build_followup_message(question, collection.datetime_attempts)
        if restart_prefix:
            combined = create_multi_message(
                [
                    {"type": "text", "data": {"body": restart_prefix}},
                    {"type": "text", "data": {"body": question}},
                ]
            )
            msg_json = to_whatsapp_json(combined)
            restart_prefix = None

        response, redirect_type, _ = await classify_and_interrupt(
            msg_json, state, config, skip_llm=True
        )
        messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

        if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
            return redirect_result

        if is_decline_response(response):
            result = await _soft_redirect_handoff(
                "datetime",
                "user_declined_datetime",
                SOFT_REDIRECT_DECLINE_QUESTION,
                messages,
                state,
                config,
                context_message=SOFT_REDIRECT_DECLINE_CONTEXT,
            )
            if "redirect" in result:
                return result
            messages = result["messages"]

        # Increment datetime attempts
        collection_updates["datetime_attempts"] = collection.datetime_attempts + 1

    else:
        # All collected, should not reach here
        logger.warning("[incident_followup] All fields collected, nothing to follow up")
        return {"messages": []}

    # Build result
    result: dict[str, Any] = {"messages": messages}

    if collection_updates:
        result["collection"] = collection.model_copy(update=collection_updates)

    logger.info(f"[incident_followup] Completed - updates={list(collection_updates.keys())}")

    return result
