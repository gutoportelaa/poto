from typing import Literal

from pydantic import BaseModel, Field


class UrgencyAnalysis(BaseModel):
    is_urgent: bool = Field(
        description="True if the situation is urgent and requires immediate response, False otherwise"
    )
    urgency_level: Literal["critica", "alta", "media", "baixa"] = Field(
        description="Urgency level: critical (imminent danger), high (ongoing crime), medium (concerning situation), low (no urgency)"
    )
    reasoning: str = Field(
        description="Clear explanation of the reasons that led to the urgency classification (20 words max)"
    )


class UserChoiceAnalysis(BaseModel):
    service_type: Literal["bo_facil", "atendimento_190", "denuncia_anonima"] | None = Field(
        description="Service type chosen by the user based on their response. Null if ambiguous."
    )
    confidence: float = Field(
        description="Confidence level in the identification of the choice (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Explanation of how the choice was identified in the user's response (20 words max)"
    )
