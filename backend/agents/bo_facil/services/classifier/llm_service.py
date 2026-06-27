"""LLM-based classifier service for emergency and human handoff detection."""

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from core.model_routing import resolve_model
from schema.models import AllModelEnum

from .models import (
    ClassificationClass,
    EmergencyIndicators,
    HumanHandoffIndicators,
    LLMClassificationResult,
)
from .prompts import COMBINED_CLASSIFICATION_PROMPT

if TYPE_CHECKING:
    from agents.bo_facil.core.states import BOState

logger = logging.getLogger(__name__)


class CombinedClassificationOutput(BaseModel):
    """Combined structured output for classification."""

    classification: ClassificationClass = Field(
        description="Final classification: emergency, human, or neutral"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")
    reasoning: str = Field(description="Brief explanation of the classification decision")
    emergency_indicators: list[str] = Field(
        default_factory=list,
        description="List of emergency indicators found (empty if not emergency)",
    )
    human_handoff_indicators: list[str] = Field(
        default_factory=list,
        description="List of human handoff indicators found (empty if not human)",
    )


async def classify_with_llm(
    message: str,
    context: list[str] | None,
    config: RunnableConfig,
    model_override: AllModelEnum | None = None,
) -> LLMClassificationResult:
    """
    Classify message using LLM with structured output.

    Args:
        message: The user message to classify
        context: List of previous messages for context (optional)
        config: RunnableConfig with model configuration
        model_override: If set, bypass routing and use this model directly

    Returns:
        LLMClassificationResult with classification and reasoning
    """
    logger.info("[LLMClassifier] Starting classification")

    if model_override:
        from core.llm import get_model

        model = get_model(model_override)
        tier_label = "override"
    else:
        model = resolve_model("classify_with_llm", config)
        tier_label = "routed"

    structured_model = model.with_structured_output(CombinedClassificationOutput)

    context_str = "\n".join(context) if context else "Nenhuma mensagem anterior."

    prompt = COMBINED_CLASSIFICATION_PROMPT.format(
        message=message,
        context=context_str,
    )

    invoke_config = {"metadata": {"node_name": "classify_with_llm", "llm_tier": tier_label}}

    try:
        result: CombinedClassificationOutput = await structured_model.ainvoke(prompt, invoke_config)

        logger.info(
            f"[LLMClassifier] Result: {result.classification.value} "
            f"(confidence={result.confidence:.2f})"
        )

        return LLMClassificationResult(
            classification=result.classification,
            confidence=result.confidence,
            reasoning=result.reasoning,
            emergency_indicators=result.emergency_indicators,
            human_handoff_indicators=result.human_handoff_indicators,
        )

    except Exception as e:
        logger.error(f"[LLMClassifier] Error during classification: {e}", exc_info=True)
        raise


async def classify_emergency_with_llm(
    message: str,
    context: list[str] | None,
    config: RunnableConfig,
) -> EmergencyIndicators:
    """
    Classify specifically for emergency using LLM.

    Args:
        message: The user message to classify
        context: List of previous messages for context
        config: RunnableConfig with model configuration

    Returns:
        EmergencyIndicators with detection result
    """
    from .prompts import EMERGENCY_DETECTION_PROMPT

    logger.info("[LLMClassifier] Starting emergency classification")

    model = resolve_model("classify_emergency", config)

    structured_model = model.with_structured_output(EmergencyIndicators)

    context_str = "\n".join(context) if context else "Nenhuma mensagem anterior."

    prompt = EMERGENCY_DETECTION_PROMPT.format(
        message=message,
        context=context_str,
    )

    invoke_config = {"metadata": {"node_name": "classify_emergency", "llm_tier": "routed"}}

    try:
        result: EmergencyIndicators = await structured_model.ainvoke(prompt, invoke_config)

        logger.info(
            f"[LLMClassifier] Emergency result: is_emergency={result.is_emergency} "
            f"(confidence={result.confidence:.2f})"
        )

        return result

    except Exception as e:
        logger.error(f"[LLMClassifier] Error during emergency classification: {e}", exc_info=True)
        raise


async def classify_human_handoff_with_llm(
    message: str,
    context: list[str] | None,
    config: RunnableConfig,
) -> HumanHandoffIndicators:
    """
    Classify specifically for human handoff using LLM.

    Args:
        message: The user message to classify
        context: List of previous messages for context
        config: RunnableConfig with model configuration

    Returns:
        HumanHandoffIndicators with detection result
    """
    from .prompts import HUMAN_HANDOFF_PROMPT

    logger.info("[LLMClassifier] Starting human handoff classification")

    model = resolve_model("classify_human_handoff", config)

    structured_model = model.with_structured_output(HumanHandoffIndicators)

    context_str = "\n".join(context) if context else "Nenhuma mensagem anterior."

    prompt = HUMAN_HANDOFF_PROMPT.format(
        message=message,
        context=context_str,
    )

    invoke_config = {"metadata": {"node_name": "classify_human_handoff", "llm_tier": "routed"}}

    try:
        result: HumanHandoffIndicators = await structured_model.ainvoke(prompt, invoke_config)

        logger.info(
            f"[LLMClassifier] Human handoff result: needs_human={result.needs_human} "
            f"(confidence={result.confidence:.2f})"
        )

        return result

    except Exception as e:
        logger.error(
            f"[LLMClassifier] Error during human handoff classification: {e}", exc_info=True
        )
        raise


def _extract_text_from_whatsapp_json(content: str) -> str | None:
    """
    Extract text body from WhatsApp JSON message format.

    WhatsApp format: {"messages": [{"type": "text", "body": "actual text"}]}
    Also handles: {"messages": [{"type": "buttons", "body": "question text", ...}]}

    Returns:
        Extracted text or None if parsing fails
    """
    try:
        data = json.loads(content)
        messages = data.get("messages", [])
        if messages and isinstance(messages, list):
            first_msg = messages[0]
            if isinstance(first_msg, dict):
                return first_msg.get("body") or first_msg.get("text")
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def extract_context_from_state(state: "BOState", max_messages: int = 10) -> list[str]:
    """
    Extract recent message context from state.

    Args:
        state: Current BOState
        max_messages: Maximum number of messages to include

    Returns:
        List of recent message strings
    """
    messages = state.get("messages", [])
    if not messages:
        return []

    context = []
    for msg in messages[-max_messages:]:
        if hasattr(msg, "content"):
            content = msg.content

            # Handle list content (multiple blocks)
            if isinstance(content, list):
                # Extract text from list content
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                content = " ".join(text_parts) if text_parts else ""

            # Skip empty content
            if not content or not isinstance(content, str):
                continue

            # Parse WhatsApp JSON messages to extract text body
            if content.startswith("{"):
                extracted = _extract_text_from_whatsapp_json(content)
                if not extracted:
                    continue
                content = extracted

            if msg.type == "human":
                context.append(f"Usuário: {content}")
            else:
                # Lazy import to avoid circular dependency
                from agents.bo_facil.flows.bo_treatment.utils.message_tags import (
                    summarize_bot_message,
                )

                tag = summarize_bot_message(content)
                context.append(f"Bot: {tag}")

    return context
