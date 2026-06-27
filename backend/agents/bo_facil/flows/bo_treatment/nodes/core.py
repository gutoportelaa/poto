import logging
from typing import Any

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
    CollectionStatus,
    CompletionInfo,
    DamageInfo,
    IdentityInfo,
    IncidentInfo,
    ObjectsInfo,
    PersonsInfo,
    RedirectInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import get_config_info, get_redirect_state, is_redirect, wrap_model
from agents.bo_facil.flows.bo_treatment.messages import BO_DESCRIPTION_CONFIRMATION
from agents.bo_facil.flows.bo_treatment.models import (
    IncidentClassification,
    UserChoiceAnalysis,
)
from agents.bo_facil.flows.bo_treatment.prompts import (
    description_generation_prompt,
    edit_analysis_prompt,
    edit_description_prompt,
    incident_classification_prompt,
    user_choice_analysis_prompt,
)
from agents.bo_facil.flows.bo_treatment.prompts.common import _load_incident_codes_table
from agents.bo_facil.flows.bo_treatment.utils import (
    build_conversation_history,
    soft_handle_redirect,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)


def _sanitize_description(description: str) -> str:
    """Strip JSON/key-value wrappers some models return instead of plain text."""
    if description.startswith('{"description"'):
        try:
            import json

            parsed = json.loads(description)
            return parsed.get("description", description)
        except (json.JSONDecodeError, AttributeError):
            return description
    if description.startswith("description:"):
        import re

        match = re.match(r'description:\s*"(.+)"', description, re.DOTALL)
        if match:
            return match.group(1)
    return description


def _check_redirect_override(state: BOState) -> str | None:
    """Check for redirect overrides."""
    redirect = get_state_field(state, "redirect", RedirectInfo)
    return "workflow_exit" if redirect.to in ["emergency", "human"] else None


async def bo_treatment_init_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """
    Initialize BO treatment workflow.

    NOTE: Biographical data restoration is now done ONCE in verify_identity.entry_router_node,
    which always runs before bo_treatment. This node no longer needs to restore data.

    Args:
        state: Current BOState
        config: Runnable configuration
        store: Data store

    Returns:
        Empty state update
    """
    _ = store  # Mark as used

    logger.info("[bo_treatment_init_node] Initializing BO treatment")

    user_id, _, _ = get_config_info(config)
    identity = get_state_field(state, "identity", IdentityInfo)
    logger.info(
        f"[bo_treatment_init_node] Starting treatment for user {user_id}, "
        f"identity_verified={identity.verified}, "
        f"cpf_validated={identity.cpf_validated}"
    )

    return {"messages": []}


async def classify_incident_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Classify the incident type based on collected information."""
    from agents.bo_facil.core.tools.context_extractor import extract_context_from_history
    from agents.bo_facil.core.utils import now_brazil

    messages = state.get("messages", [])
    scratchpad = await extract_context_from_history(
        messages, start_index=0, current_datetime=now_brazil().isoformat(), config=config
    )
    logger.info(f"[classify_incident_node] Extracted context from {len(messages)} messages")

    incident = get_state_field(state, "incident", IncidentInfo)
    model_runnable = wrap_model(
        resolve_model("classify_incident", config).with_structured_output(IncidentClassification),
        incident_classification_prompt.format(
            classification_table=_load_incident_codes_table(),
            fact=incident.fact,
            datetime_info=incident.datetime,
            location=incident.location,
            scratchpad=scratchpad,
        ),
    ).with_config(tags=["skip_stream"], node_name="classify_incident")
    result = await model_runnable.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    response = result

    codes_str = ", ".join(response.incident_type_codes)
    names_str = ", ".join(response.incident_type_names)
    logger.info(f"[classify_incident_node] Classified as: {codes_str} - {names_str}")

    return {
        "incident": incident.model_copy(
            update={
                "type_codes": response.incident_type_codes,
                "type_names": response.incident_type_names,
            }
        ),
        "scratchpad": scratchpad,
        "last_extraction_index": len(messages),
        "messages": [],
    }


def _requires_damage_collection(incident_type_codes: list[str]) -> bool:
    """Check if incident type requires damage/financial loss collection."""
    damage_related_codes = {
        "131",  # Estelionato (fraud)
        "10061",  # Crime Cibernético (cybercrime)
    }
    return any(code in damage_related_codes for code in incident_type_codes)


def should_collect_object_details(state: BOState) -> str:
    """Route after object collection to follow-up, damage, or persons.

    Checks whether the unified node flagged a follow-up need (persisted in state).
    If so, routes to the deterministic follow-up node instead of re-running LLM.
    """
    if override := _check_redirect_override(state):
        redirect = get_state_field(state, "redirect", RedirectInfo)
        logger.warning(
            f"[should_collect_object_details] Redirect override: {override}, "
            f"redirect.to={redirect.to}"
        )
        return override

    # Check follow-up before damage/persons
    objects = get_state_field(state, "objects", ObjectsInfo)
    if objects.needs_followup and objects.followup_question:
        logger.info("[should_collect_object_details] Routing to object_followup")
        return "object_followup"

    # Check if damage collection is needed
    incident = get_state_field(state, "incident", IncidentInfo)
    if _requires_damage_collection(incident.type_codes or []):
        logger.info("[should_collect_object_details] Routing to collect_damage")
        return "collect_damage"

    logger.info("[should_collect_object_details] Routing to collect_persons")
    return "collect_persons"


async def bo_description_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Generate and display BO description with options."""
    # Early return if redirect is set (avoids unnecessary LLM calls)
    redirect = get_state_field(state, "redirect", RedirectInfo)
    if redirect.to in ["emergency", "human", "cancel"]:
        logger.info(f"[bo_description_node] Redirect detected ({redirect.to}), skipping")
        return {"messages": []}

    # Get state models
    incident = get_state_field(state, "incident", IncidentInfo)
    collection = get_state_field(state, "collection", CollectionStatus)
    objects = get_state_field(state, "objects", ObjectsInfo)
    persons = get_state_field(state, "persons", PersonsInfo)
    damage = get_state_field(state, "damage", DamageInfo)
    completion = get_state_field(state, "completion", CompletionInfo)

    last_idx = state.get("last_extraction_index", 0)
    messages = state.get("messages", [])

    # Advance extraction index if there are new messages, but skip scratchpad
    # rewrite — the description prompt already receives structured_context
    # (from collected models) + conversation_history (from messages).
    if len(messages) > last_idx:
        relevant_messages = messages[last_idx:]
        has_new_user_content = any(isinstance(m, HumanMessage) for m in relevant_messages)

        if not has_new_user_content:
            logger.debug("[bo_description_node] No new user messages, advancing index")
            return {"last_extraction_index": len(messages), "messages": []}

    if incident.description and not completion.awaiting_response:
        logger.info("[bo_description_node] Showing confirmation message to user")

        response = create_multi_message(
            [
                {"type": "text", "data": {"body": BO_DESCRIPTION_CONFIRMATION}},
                {"type": "text", "data": {"body": incident.description}},
                {
                    "type": "buttons",
                    "data": {
                        "body": "Escolha uma opção:",
                        "buttons": [
                            ("bo_prosseguir", "✅ Prosseguir"),
                            ("bo_alterar", "✏️ Alterar"),
                        ],
                    },
                },
            ]
        )

        user_input, redirect_type, _ = await classify_and_interrupt(
            to_whatsapp_json(response), state, config, skip_llm=True
        )

        messages_update = [
            AIMessage(content=to_whatsapp_json(response)),
            HumanMessage(content=user_input),
        ]

        # Calculate new last_extraction_index to account for messages we're adding
        new_last_idx = len(messages) + len(messages_update)

        if redirect_result := await soft_handle_redirect(
            redirect_type, state, messages_update, config
        ):
            redirect_result["last_extraction_index"] = new_last_idx
            return redirect_result

        # Fast path: Check button IDs directly before LLM call
        user_input_lower = user_input.lower().strip()
        if user_input_lower in ("bo_prosseguir", "prosseguir", "✅ prosseguir"):
            logger.info("[bo_description_node] Button click detected: prosseguir")
            return {
                "completion": completion.model_copy(
                    update={"completed": True, "awaiting_response": False}
                ),
                "messages": messages_update,
                "last_extraction_index": new_last_idx,
            }
        elif user_input_lower in ("bo_alterar", "alterar", "✏️ alterar"):
            logger.info("[bo_description_node] Button click detected: alterar")
            return {
                "completion": completion.model_copy(
                    update={"wants_edit": True, "awaiting_response": False}
                ),
                "messages": messages_update,
                "last_extraction_index": new_last_idx,
            }

        # Fallback: Use LLM for free-text responses
        conversation_history = build_conversation_history(state)
        choice_analysis = wrap_model(
            resolve_model("user_choice_analysis", config).with_structured_output(
                UserChoiceAnalysis
            ),
            user_choice_analysis_prompt.format(
                user_input=user_input,
                conversation_history=conversation_history,
            ),
        ).with_config(tags=["skip_stream"], node_name="user_choice_analysis")

        result = await choice_analysis.ainvoke(state, config)
        if is_redirect(result):
            return get_redirect_state(result)
        choice = result
        logger.info(f"[bo_description_node] User choice classified as: {choice.intention}")

        if choice.intention == "prosseguir":
            logger.info("[bo_description_node] User confirmed - completing BO")
            return {
                "completion": completion.model_copy(
                    update={"completed": True, "awaiting_response": False}
                ),
                "messages": messages_update,
                "last_extraction_index": new_last_idx,
            }
        elif choice.intention == "alterar":
            logger.info("[bo_description_node] User wants to edit (inline change detected)")
            return {
                "completion": completion.model_copy(
                    update={
                        "wants_edit": True,
                        "awaiting_response": False,
                        "edit_request": user_input,
                    }
                ),
                "messages": messages_update,
                "last_extraction_index": new_last_idx,
            }
        else:
            # Intention is "unclear" - reset and ask again
            logger.info("[bo_description_node] Unclear intention - will ask again")
            return {
                "completion": completion.model_copy(update={"awaiting_response": False}),
                "messages": messages_update,
                "last_extraction_index": new_last_idx,
            }

    if not incident.description:
        # Minimum requirement: must have at least the fact to generate description.
        # Other fields (datetime, location) may be missing if max attempts were reached.
        # The routing already ensures we don't reach here prematurely.
        if not collection.has_fact:
            logger.warning("[bo_description_node] No fact collected, cannot generate description")
            return {
                "completion": completion.model_copy(update={"completed": True}),
                "messages": [],
            }

        from agents.bo_facil.flows.bo_treatment.models import BODescription
        from agents.bo_facil.flows.bo_treatment.utils.summary_formatter import (
            build_description_context,
        )

        # Build structured context from extracted data
        structured_context = build_description_context(
            fact=incident.fact,
            datetime_info=incident.datetime,
            location=incident.location,
            bo_objects=objects.items,
            bo_weapons=objects.weapons,
            bo_persons=persons.items,
            has_damage=damage.has_damage,
            damage_value=damage.value,
            damage_payment_method=damage.payment_method,
        )

        # Use higher limit for description generation to capture all details
        conversation_history = build_conversation_history(state, max_messages=50)
        model_runnable = wrap_model(
            resolve_model("bo_description", config).with_structured_output(BODescription),
            description_generation_prompt.format(
                conversation_history=conversation_history,
                structured_context=structured_context,
            ),
        ).with_config(tags=["skip_stream"], node_name="bo_description")

        result = await model_runnable.ainvoke(state, config)
        if is_redirect(result):
            return get_redirect_state(result)
        description_result = result

        description = _sanitize_description(description_result.description)

        logger.info(
            "[bo_description_node] Generated description, will show confirmation on next iteration"
        )

        return {
            "incident": incident.model_copy(update={"description": description}),
            "messages": [],
        }

    return {"messages": []}


def _apply_entity_ops(
    current: list[dict], to_remove: list[str], to_update: list, to_add: list, key: str
) -> list[dict]:
    """Apply remove/update/add operations to a list of entity dicts."""
    # Copy current items
    result = [dict(item) for item in current]

    # Remove (case-insensitive match)
    remove_lower = {name.lower() for name in to_remove}
    result = [item for item in result if item.get(key, "").lower() not in remove_lower]

    # Update (case-insensitive match on target field)
    for update in to_update:
        target = getattr(update, f"target_{key}", None) or getattr(update, "target_name", "")
        for item in result:
            if item.get(key, "").lower() == target.lower():
                changes = update.model_dump(
                    exclude={f"target_{key}", "target_name", "target_type"}, exclude_none=True
                )
                item.update(changes)
                break

    # Add
    for addition in to_add:
        result.append(addition.model_dump())

    return result


def _apply_diff(diff, incident: IncidentInfo, objects: ObjectsInfo, persons: PersonsInfo):
    """Apply edit diff to current state, returning updated models.

    Returns (incident, objects, persons, location_changed).
    """
    # 1. Scalars
    incident_update = {}
    location_changed = False
    if diff.updated_fact is not None:
        incident_update["fact"] = diff.updated_fact
    if diff.updated_datetime is not None:
        incident_update["datetime"] = diff.updated_datetime
    if diff.updated_location is not None:
        incident_update["location"] = diff.updated_location
        # Clear stale geocoding data — text changed, old coordinates are wrong
        incident_update["latitude"] = None
        incident_update["longitude"] = None
        incident_update["geocoded_data"] = None
        incident_update["reference_point"] = None
        location_changed = True

    # 2. Objects & Weapons
    items = _apply_entity_ops(
        current=objects.items,
        to_remove=diff.objects_to_remove,
        to_update=diff.objects_to_update,
        to_add=diff.objects_to_add,
        key="name",
    )
    weapons = _apply_entity_ops(
        current=objects.weapons,
        to_remove=diff.weapons_to_remove,
        to_update=diff.weapons_to_update,
        to_add=diff.weapons_to_add,
        key="type",
    )

    # 3. Persons
    person_items = _apply_entity_ops(
        current=persons.items,
        to_remove=diff.persons_to_remove,
        to_update=diff.persons_to_update,
        to_add=diff.persons_to_add,
        key="name",
    )

    return (
        incident.model_copy(update=incident_update) if incident_update else incident,
        objects.model_copy(update={"items": items, "weapons": weapons}),
        persons.model_copy(update={"items": person_items}),
        location_changed,
    )


async def bo_edit_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """Handle BO description editing with diff-only approach.

    This node:
    1. Collects user's requested changes
    2. Uses LLM to return only the diff (what changed)
    3. Applies diff to current state
    4. Regenerates description from updated data
    """
    import json

    from agents.bo_facil.flows.bo_treatment.models import BODescription
    from agents.bo_facil.flows.bo_treatment.models.edit import EditDiff

    # Get state models
    incident = get_state_field(state, "incident", IncidentInfo)
    objects = get_state_field(state, "objects", ObjectsInfo)
    persons = get_state_field(state, "persons", PersonsInfo)
    completion = get_state_field(state, "completion", CompletionInfo)

    # STEP 1: Collect user input (skip if already provided inline at confirmation)
    messages = state.get("messages", [])
    messages_update: list = []

    if completion.edit_request:
        # User already described changes at confirmation step — use directly
        logger.info("[bo_edit_node] Using inline edit_request from confirmation step")
        user_input = completion.edit_request
    else:
        # User clicked the "Alterar" button — need to ask what to change
        response = create_text_message("O que você gostaria de alterar? Descreva as mudanças:")
        user_input, redirect_type, _ = await classify_and_interrupt(
            to_whatsapp_json(response), state, config, skip_llm=True
        )

        messages_update = [
            AIMessage(content=to_whatsapp_json(response)),
            HumanMessage(content=user_input),
        ]

        if redirect_result := await soft_handle_redirect(
            redirect_type, state, messages_update, config
        ):
            redirect_result["last_extraction_index"] = len(messages) + len(messages_update)
            return redirect_result

    new_last_idx = len(messages) + len(messages_update)

    # STEP 2: Prepare current data as JSON
    current_objects_json = json.dumps(objects.items, ensure_ascii=False)
    current_weapons_json = json.dumps(objects.weapons, ensure_ascii=False)
    current_persons_json = json.dumps(persons.items, ensure_ascii=False)

    # STEP 3: Use LLM to get diff (only what changed)
    m = resolve_model("bo_edit", config)
    edit_model = wrap_model(
        m.with_structured_output(EditDiff),
        edit_analysis_prompt.format(
            current_fact=incident.fact or "",
            current_datetime=incident.datetime or "",
            current_location=incident.location or "",
            current_objects_json=current_objects_json,
            current_weapons_json=current_weapons_json,
            current_persons_json=current_persons_json,
            user_changes=user_input,
        ),
        node_name="bo_edit",
    ).with_config(tags=["skip_stream"])

    result = await edit_model.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    edit_result = result

    logger.info(f"[bo_edit_node] Changes applied: {edit_result.changes_summary}")

    # STEP 4: Apply diff to current state
    updated_incident, updated_objects, updated_persons, location_changed = _apply_diff(
        edit_result, incident, objects, persons
    )

    # STEP 5: Update description based on changes
    description_model = wrap_model(
        m.with_structured_output(BODescription),
        edit_description_prompt.format(
            current_description=incident.description or "",
            changes_summary=edit_result.changes_summary,
            user_changes=user_input,
            updated_fact=updated_incident.fact or "",
            updated_datetime=updated_incident.datetime or "",
            updated_location=updated_incident.location or "",
        ),
        node_name="bo_description_rebuild",
    ).with_config(tags=["skip_stream"])

    result = await description_model.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    description_result = result

    result_dict: dict[str, Any] = {
        "incident": updated_incident.model_copy(
            update={"description": _sanitize_description(description_result.description)}
        ),
        "objects": updated_objects,
        "persons": updated_persons,
        "completion": completion.model_copy(update={"wants_edit": False, "edit_request": None}),
        "messages": messages_update,
        "last_extraction_index": new_last_idx,
    }

    if location_changed:
        collection = get_state_field(state, "collection", CollectionStatus)
        result_dict["collection"] = collection.model_copy(update={"location_geocoded": False})

    return result_dict


async def collect_evidence_node(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Ask user for evidence files (photos, videos, documents) before finalizing.

    This node runs after the user confirms the BO description. It asks if they
    have evidence to attach. If yes, tells them to send everything and type
    "pronto". Media URLs are silently accepted at the service layer (no graph
    resumption), so the interrupt only returns when the user sends text.
    """
    from agents.bo_facil.services.classifier.media import EVIDENCE_ASK_MESSAGE

    logger.info("[collect_evidence_node] Asking about evidence attachments")

    msg = create_button_message(
        body=EVIDENCE_ASK_MESSAGE,
        buttons=[("evidence_yes", "Sim"), ("evidence_no", "Não")],
    )
    msg_json = to_whatsapp_json(msg)

    response, redirect_type, _ = await classify_and_interrupt(
        msg_json, state, config, skip_llm=True
    )
    messages = [AIMessage(content=msg_json), HumanMessage(content=response)]

    if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
        return redirect_result

    lower = response.lower().strip()
    wants_evidence = "evidence_yes" in response or lower in ("sim", "s", "yes")

    if not wants_evidence:
        logger.info("[collect_evidence_node] User declined evidence, continuing")
        return {"messages": messages}

    # User wants to send evidence. expecting_media=True makes
    # classify_and_interrupt collect the files silently (the node owns its own
    # instruction copy) and proceed when the user finishes — while still running
    # emergency/human/cancel detection on that terminating message. Files are
    # auto-attached to the BO by the bridge, so nothing is captured here.
    logger.info("[collect_evidence_node] User wants to send evidence, waiting for completion")
    collect_msg = create_text_message(
        "Envie todos os arquivos que tiver. Depois, é só digitar *pronto*."
    )
    collect_json = to_whatsapp_json(collect_msg)

    final_input, redirect_type, _ = await classify_and_interrupt(
        collect_json, state, config, skip_llm=True, expecting_media=True
    )
    messages.append(AIMessage(content=collect_json))
    messages.append(HumanMessage(content=final_input))

    if redirect_result := await soft_handle_redirect(redirect_type, state, messages, config):
        return redirect_result

    logger.info("[collect_evidence_node] Evidence collection completed")
    return {"messages": messages}
