"""Context extraction for police report scratchpad management."""

import logging

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agents.bo_facil.flows.bo_treatment.utils.conversation import build_conversation_history
from core.model_routing import resolve_model

logger = logging.getLogger(__name__)

# =============================================================================
# PROMPTS
# =============================================================================

HISTORY_EXTRACTION_PROMPT = """Extraia APENAS informações explicitamente mencionadas pelo Usuário.

{conversation}

Extraia para os campos do modelo:
- fact: o que aconteceu (palavras do usuário)
- datetime_text: quando aconteceu (PRESERVAR texto original: "ontem às 15h", "segunda passada de manhã")
- location: onde aconteceu
- method: como ocorreu
- objects: lista de objetos envolvidos (cada item = "descrição completa", ex: "celular Samsung azul IMEI 123456789012345")
- people: lista de pessoas envolvidas (cada item = "tipo e descrição", ex: "suspeito alto com cicatriz")
- violence: lista de armas/violência
- financial: lista de valores e formas de pagamento
- digital: lista de plataformas ou perfis digitais
- vehicles: lista de veículos (tipo marca modelo cor placa)
- circumstances: lista de circunstâncias adicionais

REGRAS CRÍTICAS:
- NUNCA invente dados: sem marca, modelo, cor, data ou hora não mencionados
- "meu celular" sem detalhes → "celular" (sem marca/modelo)
- IMEI (15 dígitos) → dentro de objects junto ao celular
- Preserve números exatos (CPF, IMEI, placa, telefone)
- datetime_text: preserve o texto original do usuário, NÃO normalize para YYYY-MM-DD
- Campos sem informação → null ou lista vazia
"""

HISTORY_REWRITE_PROMPT = (
    """INFORMAÇÕES ANTERIORMENTE COLETADAS:
{existing_scratchpad}

---

"""
    + HISTORY_EXTRACTION_PROMPT
    + """
REESCRITA: Gere extração COMPLETA combinando informações anteriores + novas.
- Combine dados do mesmo objeto em uma string (ex: "celular Samsung" + IMEI → "celular Samsung IMEI 123...")
- NÃO duplique itens
- NÃO invente dados ausentes
"""
)

# =============================================================================
# STRUCTURED OUTPUT MODEL
# =============================================================================


class ScratchpadExtraction(BaseModel):
    """Structured extraction from conversation history."""

    fact: str | None = Field(None, description="What happened")
    datetime_text: str | None = Field(
        None,
        description="When it happened (user's original text, e.g. 'yesterday at 3pm')",
    )
    location: str | None = Field(None, description="Where it happened")
    method: str | None = Field(None, description="How it happened")
    objects: list[str] = Field(
        default_factory=list,
        description="Objects involved (e.g. 'blue Samsung phone')",
    )
    people: list[str] = Field(
        default_factory=list,
        description="People involved (e.g. 'tall suspect with tattoo')",
    )
    violence: list[str] = Field(
        default_factory=list,
        description="Weapons or violence (e.g. 'knife')",
    )
    financial: list[str] = Field(
        default_factory=list,
        description="Monetary values or payment methods",
    )
    digital: list[str] = Field(
        default_factory=list,
        description="Digital platforms or profiles",
    )
    vehicles: list[str] = Field(
        default_factory=list,
        description="Vehicles (type, brand, model, color, plate)",
    )
    circumstances: list[str] = Field(
        default_factory=list,
        description="Additional circumstances",
    )


# =============================================================================
# SERIALIZATION
# =============================================================================

_SCALAR_FIELDS = [
    ("FATO", "fact"),
    ("DATA/HORA", "datetime_text"),
    ("LOCAL", "location"),
    ("MODO", "method"),
]

_LIST_FIELDS = [
    ("OBJETOS", "objects"),
    ("PESSOAS", "people"),
    ("VIOLÊNCIA", "violence"),
    ("FINANCEIRO", "financial"),
    ("DIGITAL", "digital"),
    ("VEÍCULO", "vehicles"),
    ("CIRCUNSTÂNCIAS", "circumstances"),
]


def serialize_scratchpad(extraction: ScratchpadExtraction) -> str:
    """Serialize a ScratchpadExtraction into a deterministic plain-text format.

    Format:
        LABEL: value
        LABEL: item1 | item2

    Empty/None fields are omitted.
    """
    lines: list[str] = []

    for label, attr in _SCALAR_FIELDS:
        value = getattr(extraction, attr)
        if value:
            lines.append(f"{label}: {value}")

    for label, attr in _LIST_FIELDS:
        items = getattr(extraction, attr)
        if items:
            lines.append(f"{label}: {' | '.join(items)}")

    return "\n".join(lines)


# =============================================================================
# EXTRACTION
# =============================================================================


async def extract_context_from_history(
    messages: list,
    start_index: int = 0,
    existing_scratchpad: str | None = None,
    current_datetime: str | None = None,  # noqa: ARG001 - kept for caller compatibility
    config: dict | None = None,
) -> str:
    """Extract consolidated context from message history at strategic flow points.

    Args:
        messages: List of conversation messages
        start_index: Index to start extraction from
        existing_scratchpad: Optional existing scratchpad to merge with (rewrites with new info only)
        current_datetime: Deprecated. Kept for caller compatibility, no longer used.
    """
    relevant = messages[start_index:]
    if not relevant:
        logger.debug("[ExtractFromHistory] No messages to process")
        return ""

    conversation_text = build_conversation_history(
        {"messages": relevant},
        max_messages=len(relevant),
        compress_bot_messages=True,
    )

    if conversation_text == "Nenhuma mensagem anterior":
        logger.debug("[ExtractFromHistory] No conversation content found")
        return ""

    try:
        if existing_scratchpad:
            prompt_text = HISTORY_REWRITE_PROMPT
        else:
            prompt_text = HISTORY_EXTRACTION_PROMPT

        prompt = ChatPromptTemplate.from_template(prompt_text)
        model = resolve_model("extract_context_from_history", config or {})
        structured_model = model.with_structured_output(ScratchpadExtraction)

        chain = prompt | structured_model

        invoke_params: dict = {"conversation": conversation_text}
        if existing_scratchpad:
            invoke_params["existing_scratchpad"] = existing_scratchpad

        result = await chain.ainvoke(invoke_params)

        extracted = serialize_scratchpad(result)
        logger.info(
            f"[ExtractFromHistory] Extracted {len(extracted)} chars from {len(relevant)} messages"
        )
        return extracted

    except Exception as e:
        logger.warning(f"[ExtractFromHistory] Extraction failed: {str(e)}")
        return ""
