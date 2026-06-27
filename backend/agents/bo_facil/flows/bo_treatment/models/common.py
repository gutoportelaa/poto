from typing import Literal

from pydantic import BaseModel, Field


class IncidentClassification(BaseModel):
    """Classification of incident type based on collected information.

    Supports multiple incident type codes when applicable (e.g., robbery + threat).
    """

    incident_type_codes: list[str] = Field(
        ...,
        description="List of incident type codes (e.g., ['76'], ['86', '57'], ['131'])",
        min_length=1,
    )
    incident_type_names: list[str] = Field(
        ...,
        description="List of incident type names corresponding to codes (e.g., ['Theft'], ['Robbery', 'Threat'])",
        min_length=1,
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence level of classification")
    reasoning: str = Field(
        ..., description="Reasoning for the classification based on the facts (20 words max)"
    )


class BODescription(BaseModel):
    """First-person incident report from the citizen."""

    description: str = Field(
        ...,
        description="First-person incident narrative faithful to what the citizen said. Only concrete facts, never mention what did NOT happen.",
    )


class UserChoiceAnalysis(BaseModel):
    """Analysis of user's choice between proceed or edit."""

    intention: Literal["prosseguir", "alterar", "unclear"] = Field(
        ...,
        description="User's intention: 'prosseguir' to continue, 'alterar' to edit, 'unclear' if ambiguous",
    )
    confidence: float = Field(..., description="Confidence level from 0.0 to 1.0")
    reasoning: str = Field(..., description="Brief explanation of the analysis  (20 words max)")


# ---------------------------------------------------------------------------
# Sequential extraction models (one per domain)
# ---------------------------------------------------------------------------


class FactExtraction(BaseModel):
    """Extract only the incident fact and followup question."""

    has_fact: bool = Field(description="Whether a describable incident/fact was provided")
    fact: str | None = Field(
        default=None, description="The incident description if provided (what happened)"
    )
    is_fact_explained: bool = Field(
        default=False,
        description=(
            "Whether the fact has MINIMUM details to register a BO. "
            "True if the citizen said WHAT happened + at least ONE detail "
            "(object taken, method, circumstance). "
            "When in doubt, mark True. Consider the FULL conversation history."
        ),
    )
    followup_question: str | None = Field(
        default=None,
        description=(
            "Follow-up question in Portuguese ONLY when has_fact=false or is_fact_explained=false. "
            "Must ask about what happened (the fact), NEVER about when or where. "
            "Max 200 characters."
        ),
    )
    is_non_bo_intent: bool = Field(
        default=False,
        description=(
            "True when the user's message indicates they do NOT want to register a BO. "
            "Examples: asking questions, requesting status of existing BO, "
            "wanting general help, greeting without incident description. "
            "False when the user describes any situation, even if not criminal."
        ),
    )
    non_bo_intent_type: str | None = Field(
        default=None,
        description=(
            "Type of non-BO intent when is_non_bo_intent=true. "
            "Options: 'acompanhamento' (wants to check existing BO status), "
            "'duvida' (has a question about the service), "
            "'outro' (other non-BO intent). "
            "Only set when is_non_bo_intent=true."
        ),
    )
    is_non_registrable: bool = Field(
        default=False,
        description=(
            "True ONLY when the user described a situation that clearly does NOT fit "
            "any incident type code (not even 'Outras Comunicações'). "
            "Examples: product defect, medical issue, employment dispute. "
            "NEVER true for: loss of items (code 1101), noise complaints (code 20682), "
            "threats, property damage, or any situation with a matching incident code. "
            "When true, has_fact should be true and fact should describe the situation."
        ),
    )


class DatetimeExtraction(BaseModel):
    """Extract only the incident date and time."""

    has_datetime: bool = Field(
        description="Whether BOTH valid date AND approximate time were provided"
    )
    datetime: str | None = Field(
        default=None,
        description="Date/time in YYYY-MM-DD HH:MM format (24-hour). Example: 2024-11-26 16:30",
    )


class LocationExtraction(BaseModel):
    """Extract only the incident location."""

    has_location: bool = Field(
        description=(
            "True if the user provided a usable location: address, neighborhood, city, "
            "or named landmark. False if generic/virtual/unidentifiable."
        )
    )
    location: str | None = Field(
        default=None,
        description=(
            "The full location text provided by the user. Includes addresses, neighborhoods, "
            "cities, landmarks, and reference points — everything the user said about the location. "
            "ALWAYS fill this field when the user provides anything location-related, "
            "even if informal or incomplete. Only leave null when there is clearly no location info."
        ),
    )
    state_mentioned: bool = Field(
        default=False,
        description=(
            "Cidadão citou o estado em qualquer ponto da conversa (sigla, nome completo, "
            "ou typo claro como 'minasgerais', 'sao pauloo', 'rio grande sul')."
        ),
    )
    state_uf: str | None = Field(
        default=None,
        description=(
            "UF canônica resolvida em 2 letras maiúsculas (PI, SP, MG, ...) quando "
            "state_mentioned=True. None caso contrário."
        ),
    )


# ---------------------------------------------------------------------------
# Composite model — built from sequential extractions, keeps backward compat
# ---------------------------------------------------------------------------


class UnifiedIncidentExtraction(BaseModel):
    """Composite extraction result built from sequential focused LLM calls."""

    has_fact: bool = False
    fact: str | None = None
    is_fact_explained: bool = False
    has_datetime: bool = False
    datetime: str | None = None
    has_location: bool = False
    state_mentioned: bool = False
    state_uf: str | None = None
    location: str | None = None
    followup_question: str | None = None  # from FactExtraction
    is_non_bo_intent: bool = False  # from FactExtraction
    non_bo_intent_type: str | None = None  # from FactExtraction
    is_non_registrable: bool = False  # from FactExtraction
