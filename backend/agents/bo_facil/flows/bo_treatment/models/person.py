from typing import Literal

from pydantic import BaseModel, Field


class BasicPersonInfo(BaseModel):
    """Basic person information for initial collection - simplified for performance."""

    name: str = Field(..., description="Name or identifier (e.g., 'Suspeito 1', 'João')")
    type: Literal["suspeito", "testemunha", "outro_envolvido"] = Field(
        ..., description="Type of involvement"
    )
    description: str = Field(..., description="Brief description or role")


class InvolvedPerson(BaseModel):
    """Simplified person model - only essential fields."""

    name: str = Field(..., description="Person's name or 'Desconhecido' if unknown")
    type: Literal["suspeito", "testemunha", "outro_envolvido"] = Field(
        ..., description="Type of involvement"
    )
    description: str = Field(default="", description="All details combined")

    def to_display_string(self) -> str:
        """Format person for display in summary."""
        type_config = {
            "suspeito": ("⚠️", "SUSPEITO"),
            "testemunha": ("👁️", "TESTEMUNHA"),
            "outro_envolvido": ("👤", "ENVOLVIDO"),
        }
        emoji, type_label = type_config.get(self.type, ("👤", "ENVOLVIDO"))

        result = f"{emoji} *{type_label}: {self.name}*"
        if self.description:
            result += f"\n  {self.description}"
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "InvolvedPerson":
        """Create InvolvedPerson from dictionary, ignoring unknown fields."""
        known_fields = {"name", "type", "description"}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)


class PersonAnalysis(BaseModel):
    """Analysis for person collection - uses BasicPersonInfo."""

    persons: list[BasicPersonInfo] = Field(
        default_factory=list, description="List of persons (name, type, description only)"
    )
    has_persons: bool = Field(..., description="Whether user mentioned other persons involved")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence level of the analysis")
    reasoning: str = Field(..., description="Reasoning for the analysis (20 words max)")
