"""Nodes for generating and submitting BO reports."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.store.base import BaseStore

from agents.bo_facil.core.messages import (
    create_multi_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    BOState,
    ClassificationInfo,
    CollectionStatus,
    CompletionInfo,
    CybercrimeInfo,
    DamageInfo,
    HandoffInfo,
    IdentityInfo,
    IncidentInfo,
    ObjectsInfo,
    PersonsInfo,
    RedirectInfo,
    UserInfo,
    VictimInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import get_user_memory_manager
from agents.bo_facil.flows.post_bo.messages import (
    MSG_ERROR_COMFORT,
    MSG_ERROR_TITLE,
    MSG_ERROR_TRANSFER,
    MSG_FAREWELL,
    MSG_HELP_MORE,
    MSG_PROTOCOL_TEMPLATE,
    MSG_SUCCESS_DETAILS,
    MSG_SUCCESS_TITLE,
)
from agents.bo_facil.flows.post_bo.utils import (
    build_incident_payload,
    call_pdf_generation_api,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from agents.bo_facil.services.govchat.operations import govchat_resolve, govchat_set_attribute
from core.settings import settings

logger = logging.getLogger(__name__)


# ==============================================================================
# GOVCHAT API FUNCTIONS (centralized in services/govchat/operations.py)
# ==============================================================================


async def _send_error_alert(error_code: str, error_data: str) -> dict:
    """
    Send error alert to monitoring webhook.

    TODO: Implement real webhook call to https://flows.sendvers.pro/webhook/alerts-cdbofacil
    """
    logger.critical(f"[ErrorAlert] PDF generation failure - Code: {error_code}, Data: {error_data}")
    return {"success": True}


def _get_user_info(state: BOState) -> UserInfo:
    """Get user info, handling dict or model."""
    return get_state_field(state, "user", UserInfo)


def _get_completion(state: BOState) -> CompletionInfo:
    """Get completion info, handling dict or model."""
    return get_state_field(state, "completion", CompletionInfo)


def _get_incident(state: BOState) -> IncidentInfo:
    """Get incident info, handling dict or model."""
    return get_state_field(state, "incident", IncidentInfo)


# ==============================================================================
# MAIN NODE FUNCTIONS
# ==============================================================================


async def _handle_submit_without_cpf(
    state: BOState, config: RunnableConfig, store: BaseStore
) -> BOState:
    """Handle BO submission without CPF — same strategy as anonymous flow."""
    from agents.bo_facil.flows.anonymous.messages import SUCCESS_MESSAGE
    from agents.bo_facil.flows.anonymous.nodes import _send_to_bofacil_api

    logger.info("[generate_pdf_node] Handling proceed_without_cpf (anonymous-like flow)")

    user = _get_user_info(state)
    completion = _get_completion(state)

    payload = await build_incident_payload(state)
    if payload:
        await _send_to_bofacil_api(payload.model_dump(exclude_none=True))

    success_msg = create_multi_message([{"type": "text", "data": {"body": SUCCESS_MESSAGE}}])
    success_json = to_whatsapp_json(success_msg)

    result = await govchat_resolve(user.account_id, user.conversation_id)
    if not result.get("success"):
        logger.warning(f"[generate_pdf_node] GovChat resolve failed: {result.get('error')}")

    return {
        "completion": completion.model_copy(update={"completed": True}),
        "messages": [AIMessage(content=success_json)],
    }


async def generate_pdf_node(state: BOState, config: RunnableConfig, store: BaseStore) -> BOState:
    """
    Generate PDF by calling the incident report API.

    Split into 2 phases to avoid duplicate BO generation on interrupt resume:
    - Phase 1 (pdf_generated=False): Build payload, call API, save side effects, return with pdf_generated=True
    - Phase 2 (pdf_generated=True): Show success messages + ask "help more?" via interrupt

    The routing self-loops back to this node between phases.
    """
    logger.info("[generate_pdf_node] Starting POST-BO flow")

    user = _get_user_info(state)
    completion = _get_completion(state)
    incident = _get_incident(state)

    # Anonymous flow only when no regex-valid CPF was ever captured.
    identity = get_state_field(state, "identity", IdentityInfo)
    if identity.proceed_without_cpf and not identity.cpf_validated:
        return await _handle_submit_without_cpf(state, config, store)

    conversation_id = user.conversation_id or "unknown"

    try:
        # ── PHASE 1: Generate PDF (runs only once) ──
        if not completion.pdf_generated:
            max_attempts = 3
            payload = await build_incident_payload(state)

            if not payload:
                logger.warning(
                    "[generate_pdf_node] Payload creation failed - missing required data"
                )
                api_response = None
                http_status = None
            else:
                missing_ids = []
                if payload.conversation_id is None:
                    missing_ids.append("conversation_id")
                if payload.inbox_id is None:
                    missing_ids.append("inbox_id")
                if payload.account_id is None:
                    missing_ids.append("account_id")
                if missing_ids:
                    logger.error(
                        f"[generate_pdf_node] Payload has missing IDs: {missing_ids}. "
                        f"BO will be generated but GovChat traceability will be lost. "
                        f"thread_id={config.get('configurable', {}).get('thread_id', 'unknown')}"
                    )
                logger.info(
                    f"[generate_pdf_node] Payload created successfully for CPF: {payload.pessoa.cpf}"
                )

                api_response = None
                http_status = None
                for attempt in range(1, max_attempts + 1):
                    api_response = await call_pdf_generation_api(payload)
                    if api_response is not None:
                        http_status = 200
                        if api_response.protocolo is None:
                            # API accepted the payload (HTTP 200) but didn't
                            # return a protocolo — BO exists upstream but PDF
                            # generation failed. Retrying would duplicate the
                            # BO, so stop here and fall into the error branch.
                            logger.error(
                                "[generate_pdf_node] API returned 200 without "
                                "protocolo — BO exists upstream, NOT retrying. "
                                "Treating as failure."
                            )
                        break
                    http_status = 500
                    logger.warning(
                        f"[generate_pdf_node] API call failed, attempt {attempt}/{max_attempts}"
                    )

            if api_response and api_response.protocolo:
                protocol_info = api_response.protocolo

                # Extract protocol number from filename
                protocol_number = "N/A"
                if protocol_info.nm_arquivo:
                    import re
                    from datetime import datetime

                    match = re.search(r"protocolo-(\d+)", protocol_info.nm_arquivo)
                    if match:
                        protocol_number = f"{match.group(1)}/{datetime.now().year}"

                # Side effects (execute only once)
                result = await govchat_set_attribute(
                    user.account_id, conversation_id, "protocolo", protocol_number
                )
                if not result.get("success"):
                    logger.warning(
                        f"[generate_pdf_node] GovChat set_attribute failed: {result.get('error')}"
                    )

                manager = get_user_memory_manager(config, store)
                if manager and incident.description:
                    incident_type = incident.type_names[0] if incident.type_names else None
                    await manager.add_bo_to_history(
                        bo_description=incident.description, incident_type=incident_type
                    )
                    logger.info("[generate_pdf_node] BO added to user history")

                # Return with pdf_generated=True → routing self-loops → phase 2
                # Reset completed=False because bo_treatment sets it for "description confirmed",
                # but the PDF flow is not done yet.
                logger.info(f"[generate_pdf_node] Phase 1 complete - protocol: {protocol_number}")
                return {
                    "completion": completion.model_copy(
                        update={
                            "pdf_generated": True,
                            "completed": False,
                            "protocol_number": protocol_number,
                            "pdf_url": protocol_info.url_aws_temporaria,
                        }
                    ),
                    "messages": [],
                }
            else:
                # All attempts exhausted — send error alert and transfer to human
                logger.error(
                    "[generate_pdf_node] All attempts exhausted, transferring to human handoff"
                )

                await _send_error_alert(
                    error_code=str(http_status or "unknown"),
                    error_data="All attempts exhausted for PDF generation",
                )

                error_messages = [MSG_ERROR_TITLE, MSG_ERROR_COMFORT, MSG_ERROR_TRANSFER]
                handoff = get_state_field(state, "handoff", HandoffInfo)
                redirect = get_state_field(state, "redirect", RedirectInfo)

                return {
                    "completion": completion.model_copy(update={"retry_count": 0}),
                    "redirect": redirect.model_copy(
                        update={
                            "to": "human",
                            "reason": "Erro ao gerar PDF após múltiplas tentativas",
                            "custom_message": error_messages,
                        }
                    ),
                    "handoff": handoff.model_copy(
                        update={"team_id": settings.GOVCHAT_TEAM_ID_HANDOFF}
                    ),
                }

        # ── PHASE 2: Show success + ask "help more?" (interrupt here) ──
        # protocol_number and pdf_url are already persisted in completion from phase 1
        logger.info("[generate_pdf_node] Phase 2 - showing success and asking help more")

        combined_success = create_multi_message(
            [
                {"type": "text", "data": {"body": MSG_SUCCESS_TITLE}},
                {"type": "text", "data": {"body": MSG_SUCCESS_DETAILS}},
                {
                    "type": "text",
                    "data": {
                        "body": MSG_PROTOCOL_TEMPLATE.format(protocolo=completion.protocol_number)
                    },
                },
                {
                    "type": "document",
                    "data": {
                        "link": completion.pdf_url,
                        "filename": f"protocolo-{completion.protocol_number}.pdf",
                        "caption": f"Boletim de Ocorrência - Protocolo {completion.protocol_number}",
                    },
                },
                {
                    "type": "buttons",
                    "data": {
                        "body": MSG_HELP_MORE,
                        "buttons": [("help_yes", "Sim"), ("help_no", "Não")],
                    },
                },
            ]
        )
        combined_json = to_whatsapp_json(combined_success)

        help_response, redirect_type, _ = await classify_and_interrupt(
            combined_json, state, config, skip_llm=True
        )

        if redirect_type:
            redirect = get_state_field(state, "redirect", RedirectInfo)
            return {
                "redirect": redirect.model_copy(update={"to": redirect_type}),
                "messages": [
                    AIMessage(content=combined_json),
                    HumanMessage(content=help_response),
                ],
            }

        wants_more_help = "help_yes" in help_response or help_response.lower().strip() in {
            "sim",
            "s",
        }

        if wants_more_help:
            # User wants more help - reset ALL states and clear conversation history
            logger.info("[generate_pdf_node] User requested more help - resetting all states")

            existing_messages = state.get("messages", [])
            remove_ops = [RemoveMessage(id=m.id) for m in existing_messages]

            return {
                "messages": remove_ops,
                "redirect": RedirectInfo(to="initial"),
                # Reset all state groups for fresh BO (CompletionInfo() resets pdf_generated=False)
                "classification": ClassificationInfo(),
                "incident": IncidentInfo(),
                "collection": CollectionStatus(),
                "objects": ObjectsInfo(),
                "persons": PersonsInfo(),
                "damage": DamageInfo(),
                "cybercrime": CybercrimeInfo(),
                "completion": CompletionInfo(),
                "victim": VictimInfo(),
                "identity": IdentityInfo(),
                "handoff": HandoffInfo(),
                "scratchpad": "",
                "last_extraction_index": None,
            }
        else:
            # User doesn't need more help - send farewell and resolve conversation
            logger.info(
                "[generate_pdf_node] User doesn't need more help - sending farewell and resolving"
            )

            farewell_msg = create_multi_message([{"type": "text", "data": {"body": MSG_FAREWELL}}])
            farewell_json = to_whatsapp_json(farewell_msg)

            result = await govchat_resolve(user.account_id, conversation_id)
            if not result.get("success"):
                logger.warning(f"[generate_pdf_node] GovChat resolve failed: {result.get('error')}")

            logger.info(
                f"[generate_pdf_node] Conversation resolved - Protocol: {completion.protocol_number}"
            )

            return {
                "completion": completion.model_copy(
                    update={
                        "completed": True,
                        "retry_count": 0,
                    }
                ),
                "messages": [
                    AIMessage(content=combined_json),
                    HumanMessage(content=help_response),
                    AIMessage(content=farewell_json),
                ],
            }

    except GraphInterrupt:
        raise

    except Exception as e:
        logger.error(f"[generate_pdf_node] Exception occurred: {str(e)}", exc_info=True)

        await _send_error_alert(error_code="500", error_data=str(e)[:500])

        error_messages = [MSG_ERROR_TITLE, MSG_ERROR_COMFORT, MSG_ERROR_TRANSFER]
        handoff = get_state_field(state, "handoff", HandoffInfo)
        redirect = get_state_field(state, "redirect", RedirectInfo)

        return {
            "completion": completion.model_copy(update={"retry_count": 0}),
            "redirect": redirect.model_copy(
                update={
                    "to": "human",
                    "reason": f"Erro interno: {str(e)[:100]}",
                    "custom_message": error_messages,
                }
            ),
            "handoff": handoff.model_copy(update={"team_id": settings.GOVCHAT_TEAM_ID_HANDOFF}),
        }
