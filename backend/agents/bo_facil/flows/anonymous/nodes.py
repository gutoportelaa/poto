"""Nodes for anonymous report flow."""

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.bo_facil.core.messages import (
    create_button_message,
    create_multi_message,
    create_text_message,
    to_whatsapp_json,
)
from agents.bo_facil.core.states import (
    AnonymousInfo,
    BOState,
    RedirectInfo,
    UserInfo,
    get_state_field,
)
from agents.bo_facil.core.utils import get_redirect_state, is_redirect, wrap_model_scratchpad
from agents.bo_facil.flows.anonymous.messages import (
    CITY_REQUEST,
    MEDIA_QUESTION,
    MEDIA_SEND_INSTRUCTION,
    PRIVACY_MESSAGE_1A,
    PRIVACY_MESSAGE_1B,
    PRIVACY_MESSAGE_2,
    REPORT_REQUEST,
    SCHOOL_RELATED_QUESTION,
    SUCCESS_MESSAGE,
)
from agents.bo_facil.flows.anonymous.models import AnonymousReportAnalysis, CityValidation
from agents.bo_facil.flows.anonymous.prompts import (
    city_validation_prompt,
    crime_classification_prompt,
)
from agents.bo_facil.services.classifier import classify_and_interrupt
from agents.bo_facil.services.govchat.models import Priority
from agents.bo_facil.services.govchat.operations import (
    govchat_resolve,
    govchat_set_attribute,
    govchat_set_priority,
)
from core.model_routing import resolve_model
from core.settings import settings

logger = logging.getLogger(__name__)


async def _send_to_bofacil_api(payload: dict) -> dict:
    """
    Send anonymous report to BO Fácil API.

    POST {PDF_API_URL}
    Headers: {"Authorization": "Bearer {PDF_API_KEY}"}
    Body: payload

    Returns:
        dict with success status and response data or error
    """
    import httpx

    if not settings.PDF_API_URL or not settings.PDF_API_KEY:
        logger.warning("[BOFacilAPI] Missing PDF_API_URL or PDF_API_KEY, skipping API call")
        return {"success": False, "error": "Missing API configuration"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.PDF_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.PDF_API_KEY.get_secret_value()}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"[BOFacilAPI] Anonymous report sent successfully: {data}")
            return {"success": True, "data": data}
    except httpx.HTTPStatusError as e:
        logger.error(f"[BOFacilAPI] HTTP error: {e.response.status_code} - {e.response.text}")
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        logger.error(f"[BOFacilAPI] Failed to send anonymous report: {e}")
        return {"success": False, "error": str(e)}


async def anonymous_report_node(state: BOState, config: RunnableConfig) -> BOState:
    """
    Handle anonymous report following Typebot ANONIMOUS-ESCOLAR flow.

    Flow:
    1. Privacy messages (wait 3s)
    2. Ask if school-related
       - If yes: ask for city → validate → collect report
       - If no: collect report directly
    3. Collect detailed report
    4. Analyze with GPT (classify crime types)
    5. If crime detected → set high priority
    6. Set custom attributes
    7. Ask if wants to attach media
    8. Send to BO Fácil API
    9. Success message
    10. Resolve conversation
    """
    logger.info("[anonymous_report_node] Starting anonymous report flow")

    messages = []

    # Step 1 & 2: Send privacy messages together with school question
    # (using create_multi_message to ensure all messages are sent together)
    intro_msg = create_multi_message(
        [
            {"type": "text", "data": {"body": PRIVACY_MESSAGE_1A}},
            {"type": "text", "data": {"body": PRIVACY_MESSAGE_1B}},
            {"type": "text", "data": {"body": PRIVACY_MESSAGE_2}},
            {
                "type": "buttons",
                "data": {
                    "body": SCHOOL_RELATED_QUESTION,
                    "buttons": [("school_yes", "Sim"), ("school_no", "Não")],
                },
            },
        ]
    )
    intro_json = to_whatsapp_json(intro_msg)

    school_response, redirect_type, _ = await classify_and_interrupt(
        intro_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=intro_json), HumanMessage(content=school_response)])

    if redirect_type:
        # redirect_type is already one of "emergency" or "human" from classify_and_interrupt
        return {"redirect": RedirectInfo(to=redirect_type), "messages": messages}

    is_school_related = "school_yes" in school_response or school_response.lower().strip() in {
        "sim",
        "s",
    }
    city_name = None

    # If school-related, ask for city
    if is_school_related:
        logger.info("[anonymous_report_node] School-related report, collecting city")

        city_msg = create_text_message(CITY_REQUEST)
        city_json = to_whatsapp_json(city_msg)

        city_input, redirect_type, _ = await classify_and_interrupt(
            city_json, state, config, skip_llm=True
        )
        messages.extend([AIMessage(content=city_json), HumanMessage(content=city_input)])

        if redirect_type:
            return {"redirect": RedirectInfo(to=redirect_type), "messages": messages}

        # Validate city with GPT
        city_validator = wrap_model_scratchpad(
            resolve_model("city_validation", config).with_structured_output(CityValidation),
            city_validation_prompt.format(user_input=city_input),
        ).with_config(tags=["skip_stream"], node_name="city_validation")

        result = await city_validator.ainvoke(state, config)
        if is_redirect(result):
            return get_redirect_state(result)
        validation = result

        if validation.is_valid == "yes" and validation.city_name:
            city_name = validation.city_name
            logger.info(f"[anonymous_report_node] City validated: {city_name}")
        else:
            logger.warning(f"[anonymous_report_node] Invalid city input: {city_input}")

    # Step 3: Collect report
    report_msg = create_text_message(REPORT_REQUEST)
    report_json = to_whatsapp_json(report_msg)

    report, redirect_type, _ = await classify_and_interrupt(report_json, state, config)
    messages.extend([AIMessage(content=report_json), HumanMessage(content=report)])

    if redirect_type:
        return {"redirect": RedirectInfo(to=redirect_type), "messages": messages}

    logger.info(f"[anonymous_report_node] Report collected: {report[:100]}...")

    # Step 4: Analyze report with GPT
    analyzer = wrap_model_scratchpad(
        resolve_model("crime_classification", config).with_structured_output(
            AnonymousReportAnalysis
        ),
        crime_classification_prompt.format(user_report=report),
    ).with_config(tags=["skip_stream"], node_name="crime_classification")

    result = await analyzer.ainvoke(state, config)
    if is_redirect(result):
        return get_redirect_state(result)
    analysis = result
    logger.info(
        f"[anonymous_report_node] Analysis: crime_detected={analysis.crime_detected}, crime_type_codes={analysis.crime_type_codes}"
    )

    user = get_state_field(state, "user", UserInfo)
    conversation_id = user.conversation_id
    account_id = user.account_id

    # Step 5: Set high priority if crime detected
    if analysis.crime_detected == "yes":
        await govchat_set_priority(account_id, conversation_id, Priority.HIGH)

    # Step 6: Set custom attributes if crime_type_codes exists
    if analysis.crime_type_codes:
        await govchat_set_attribute(
            account_id, conversation_id, "Natureza", analysis.crime_type_codes
        )

    # Step 7: Ask if wants to attach media
    media_msg = create_button_message(
        body=MEDIA_QUESTION, buttons=[("media_yes", "Sim"), ("media_no", "Não")]
    )
    media_json = to_whatsapp_json(media_msg)

    media_response, redirect_type, _ = await classify_and_interrupt(
        media_json, state, config, skip_llm=True
    )
    messages.extend([AIMessage(content=media_json), HumanMessage(content=media_response)])

    if redirect_type:
        return {"redirect": RedirectInfo(to=redirect_type), "messages": messages}

    wants_media = "media_yes" in media_response or media_response.lower().strip() in {"sim", "s"}

    if wants_media:
        # Request file upload
        media_instruction = create_text_message(MEDIA_SEND_INSTRUCTION)
        media_instruction_json = to_whatsapp_json(media_instruction)

        file_data, redirect_type, _ = await classify_and_interrupt(
            media_instruction_json, state, config, skip_llm=True
        )
        messages.extend(
            [AIMessage(content=media_instruction_json), HumanMessage(content=file_data)]
        )

        if redirect_type:
            return {"redirect": RedirectInfo(to=redirect_type), "messages": messages}

        logger.info(f"[anonymous_report_node] Media file received: {file_data[:50]}...")

    # Step 8: Build and send request to BO Fácil API
    phone = user.phone

    # Determine tipo_ocorrencia based on school-related or crime classification
    if is_school_related:
        tipo_ocorrencia = [99]  # School-related code
    elif analysis.crime_type_codes:
        # Convert comma-separated IDs to list of integers
        tipo_ocorrencia = [int(id.strip()) for id in analysis.crime_type_codes.split(",")]
    else:
        tipo_ocorrencia = [0]  # Generic/unclassified

    # Build request payload
    payload = {
        "pessoa": {
            "cpf": "000.000.000-00",
            "telefone_contato": phone,
            "email_contato": None,
            "naturalidade": None,
            "nacionalidade": None,
            "profissao": None,
            "sexo": None,
            "estado_civil": None,
        },
        "descricao_fato": report,
        "tipo_ocorrencia": tipo_ocorrencia,
        "canal": "BO fácil",
    }

    # Add city if school-related
    if city_name:
        payload["municipio_fato"] = city_name

    # Send to API
    await _send_to_bofacil_api(payload)

    # Step 9: Success message
    success_msg = create_text_message(SUCCESS_MESSAGE)
    messages.append(AIMessage(content=to_whatsapp_json(success_msg)))

    # Step 10: Resolve conversation
    await govchat_resolve(account_id, conversation_id)

    logger.info("[anonymous_report_node] Anonymous report flow completed")

    anonymous = get_state_field(state, "anonymous", AnonymousInfo)
    return {
        "anonymous": anonymous.model_copy(update={"completed": True}),
        "messages": messages,
    }
