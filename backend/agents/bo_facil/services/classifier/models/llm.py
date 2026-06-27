"""LLM classification models for structured output."""

from pydantic import BaseModel, Field

from .base import ClassificationClass


class EmergencyIndicators(BaseModel):
    """Structured output for LLM emergency detection."""

    is_emergency: bool = Field(description="Whether this is an emergency situation")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")
    indicators: list[str] = Field(
        default_factory=list,
        description="List of emergency indicators found (e.g., 'pessoa em perigo', 'pedido de socorro')",
    )
    reasoning: str = Field(description="Brief explanation of the classification decision")


class HumanHandoffIndicators(BaseModel):
    """Structured output for LLM human handoff detection."""

    needs_human: bool = Field(description="Whether user needs human assistance")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0.0 to 1.0")
    indicators: list[str] = Field(
        default_factory=list,
        description="List of handoff indicators found (e.g., 'frustração', 'pedido de atendente')",
    )
    reasoning: str = Field(description="Brief explanation of the classification decision")


class LLMClassificationResult(BaseModel):
    """Result from LLM-based classification."""

    classification: ClassificationClass = Field(description="Final classification")
    confidence: float = Field(ge=0.0, le=1.0, description="Overall confidence score")
    reasoning: str = Field(description="Explanation of the decision")
    emergency_indicators: list[str] = Field(default_factory=list)
    human_handoff_indicators: list[str] = Field(default_factory=list)
