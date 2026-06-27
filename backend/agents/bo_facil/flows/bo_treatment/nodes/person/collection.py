"""Nodes for person collection workflow - simplified."""

import logging
from difflib import SequenceMatcher

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_button_message,
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import BOState, CollectionStatus, PersonsInfo, get_state_field
from agents.bo_facil.core.utils import get_redirect_state, is_redirect, wrap_model_scratchpad
from agents.bo_facil.flows.bo_treatment.messages import (
    PERSON_DESCRIPTION_AUDIO_HINT,
    PERSON_DESCRIPTION_REQUEST,
    PERSON_QUESTION,
)
from agents.bo_facil.flows.bo_treatment.models import BasicPersonInfo, PersonAnalysis
from agents.bo_facil.flows.bo_treatment.prompts import persons_analysis_prompt
from agents.bo_facil.flows.bo_treatment.utils import build_conversation_history, classify_response
from agents.bo_facil.flows.bo_treatment.utils.response_classification import soft_handle_redirect
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


def _deduplicate_persons(persons: list[dict]) -> list[dict]:
    """Remove duplicates by type + description similarity."""
    seen = []
    for person in persons:
        is_duplicate = False
        for existing in seen:
            if person.get("type") == existing.get("type"):
                # Guard: different names = different persons, never merge
                person_name = person.get("name", "").strip().lower()
                existing_name = existing.get("name", "").strip().lower()
                if person_name and existing_name and person_name != existing_name:
                    continue

                desc1 = person.get("description", "").lower().strip()
                desc2 = existing.get("description", "").lower().strip()

                # Skip empty descriptions
                if not desc1 or not desc2:
                    continue

                # Check if one contains the other
                if desc1 in desc2 or desc2 in desc1:
                    is_duplicate = True
                    # Keep longer description
                    if len(desc1) > len(desc2):
                        existing["description"] = person["description"]
                    break

                # Check similarity ratio
                similarity = SequenceMatcher(None, desc1, desc2).ratio()
                if similarity > 0.7:
                    is_duplicate = True
                    # Merge: combine descriptions if different
                    if desc1 not in desc2:
                        existing["description"] = (
                            f"{existing['description']}, {person['description']}"
                        )
                    break

        if not is_duplicate:
            seen.append(person)

    logger.info(f"[_deduplicate_persons] Reduced {len(persons)} -> {len(seen)} persons")
    return seen


def _convert_persons_to_bo_format(persons: list) -> list[dict]:
    """Convert PersonAnalysis persons to simplified BO format (3 fields only)."""
    bo_persons = []
    for person in persons:
        if isinstance(person, BasicPersonInfo):
            data = person.model_dump()
        elif isinstance(person, dict):
            data = {
                "name": person.get("name", "Desconhecido"),
                "type": person.get("type", "outro_envolvido"),
                "description": person.get("description", ""),
            }
        else:
            data = {"name": str(person), "type": "outro_envolvido", "description": ""}

        bo_persons.append(data)
    return bo_persons


async def collect_persons_node(
    state: BOState, config: RunnableConfig, *, store: BaseStore
) -> BOState:
    """
    Collect information about involved persons.

    Simplified flow:
    1. Ask if there are persons to add (with buttons)
    2. If yes or direct answer: collect description
    3. Parse description with LLM
    4. Deduplicate results
    5. Return structured person data
    """
    logger.info("[collect_persons_node] Starting person collection")

    messages = []
    persons = get_state_field(state, "persons", PersonsInfo)

    # Ask confirmation
    buttons_msg = create_button_message(
        body=PERSON_QUESTION, buttons=[("persons_add_yes", "Sim"), ("persons_add_no", "Não")]
    )
    question_json = to_whatsapp_json(buttons_msg)

    user_response, redirect_type, _ = await classify_and_interrupt(
        question_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=question_json), HumanMessage(content=user_response)])

    if redirect_type:
        return {"redirect_to": redirect_type, "messages": []}

    # Classify response
    declined, confirmed, is_direct = classify_response(
        user_response, "persons_add_no", "persons_add_yes"
    )

    if declined:
        logger.info("[collect_persons_node] User declined")
        collection = get_state_field(state, "collection", CollectionStatus)
        return {
            "persons": persons.model_copy(
                update={
                    "items": [],
                    "has_persons": False,
                    "collected": True,
                }
            ),
            "collection": collection.model_copy(
                update={
                    "has_persons": True,
                }
            ),
            "messages": messages,
        }

    # Get description (direct or requested)
    if is_direct:
        description = user_response
    else:
        desc_msg = create_multi_message(
            [
                {"type": "text", "data": {"body": PERSON_DESCRIPTION_REQUEST}},
                {"type": "text", "data": {"body": PERSON_DESCRIPTION_AUDIO_HINT}},
            ]
        )
        desc_json = to_whatsapp_json(desc_msg)

        # Use classify_and_interrupt with skip_llm=True for regex-only emergency detection
        # (avoids LLM false positives like "tatuagem no pescoço" while catching real emergencies)
        description, redirect_type, _ = await classify_and_interrupt(
            desc_json, state, config, skip_llm=True
        )
        messages.extend([AIMessage(content=desc_json), HumanMessage(content=description)])

        if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
            return redirect_result

    # Parse with LLM
    llm = resolve_model("collect_persons", config)
    model = llm.with_structured_output(PersonAnalysis)
    conversation_history = build_conversation_history(state)
    runnable = wrap_model_scratchpad(
        model,
        persons_analysis_prompt.format(
            user_response=description,
            conversation_history=conversation_history,
        ),
        node_name="collect_persons",
    ).with_config(tags=["skip_stream"])

    result = await runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result

    # Convert and deduplicate
    new_persons = (
        _convert_persons_to_bo_format(analysis.persons)
        if analysis.has_persons and analysis.persons
        else []
    )
    logger.info(f"[collect_persons_node] Parsed {len(new_persons)} persons from user response")

    bo_persons = _deduplicate_persons(new_persons)
    logger.info(f"[collect_persons_node] Final persons count: {len(bo_persons)}")

    collection = get_state_field(state, "collection", CollectionStatus)
    return {
        "persons": persons.model_copy(
            update={
                "items": bo_persons,
                "has_persons": len(bo_persons) > 0,
                "collected": True,
            }
        ),
        "collection": collection.model_copy(
            update={
                "has_persons": True,
            }
        ),
        "messages": messages,
    }
