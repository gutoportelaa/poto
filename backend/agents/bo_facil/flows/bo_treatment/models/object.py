"""Models for object collection workflow."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
    DOCUMENTO = "documento"
    CELULAR = "celular"
    CARRO = "carro"
    MOTO = "moto"
    OUTRO = "outro"


class BOObject(BaseModel):
    """Model for stolen/lost objects in police report."""

    name: str = Field(
        description="Object name (e.g., 'iPhone 14', 'carteira', 'Gol')", min_length=1
    )
    type: ObjectType = Field(description="Object type/category", default=ObjectType.OUTRO)
    description: str | None = Field(default=None, description="Additional details if provided")

    brand: str | None = Field(default=None, description="Brand if mentioned")
    model: str | None = Field(default=None, description="Model if mentioned")
    color: str | None = Field(default=None, description="Color if mentioned")
    imei: str | None = Field(default=None, description="IMEI for cellphones")
    document_number: str | None = Field(default=None, description="Document number")
    plate: str | None = Field(default=None, description="Vehicle plate")

    # Internal control fields
    collected_details: bool = Field(default=False, description="Whether details were collected")
    scratchpad_checked: bool = Field(default=False, description="Whether scratchpad was checked")

    def __str__(self) -> str:
        return f"{self.name} ({self.type.value})"

    @classmethod
    def from_dict(cls, data: dict) -> "BOObject":
        return cls(**data)

    def to_display_string(self) -> str:
        """Format object for display in summary with improved formatting."""
        # Build main parts
        parts = []

        # Object name/type
        type_emoji = {
            ObjectType.CELULAR: "📱",
            ObjectType.DOCUMENTO: "📄",
            ObjectType.CARRO: "🚗",
            ObjectType.MOTO: "🏍️",
            ObjectType.OUTRO: "📦",
        }
        emoji = type_emoji.get(self.type, "📦")
        parts.append(f"{emoji} *{self.name}*")

        # Add specific details based on type
        if self.type == ObjectType.CELULAR:
            celular_details = []
            if self.brand:
                celular_details.append(f"Marca: {self.brand}")
            if self.model:
                celular_details.append(f"Modelo: {self.model}")
            if self.color:
                celular_details.append(f"Cor: {self.color}")
            if self.imei:
                celular_details.append(f"IMEI: {self.imei}")
            if celular_details:
                parts.append("\n  " + ", ".join(celular_details))

        elif self.type == ObjectType.DOCUMENTO:
            if self.document_number:
                parts.append(f"\n  Nº: {self.document_number}")

        elif self.type in (ObjectType.CARRO, ObjectType.MOTO):
            vehicle_details = []
            if self.brand:
                vehicle_details.append(f"Marca: {self.brand}")
            if self.model:
                vehicle_details.append(f"Modelo: {self.model}")
            if self.color:
                vehicle_details.append(f"Cor: {self.color}")
            if self.plate:
                vehicle_details.append(f"Placa: {self.plate}")
            if vehicle_details:
                parts.append("\n  " + ", ".join(vehicle_details))
            elif self.description:
                parts.append(f"\n  {self.description}")

        elif self.type == ObjectType.OUTRO:
            if self.description:
                parts.append(f"\n  {self.description}")

        return "".join(parts)

    model_config = {"extra": "forbid"}


class BOWeapon(BaseModel):
    """Model for weapons/objects used by aggressor during incident."""

    type: Literal[
        "arma de fogo", "faca", "machado", "pau", "pedra", "outro",
    ] = Field(
        description="Normalized weapon type. "
        "Variations must be normalized (e.g., 'revólver' → 'arma de fogo', 'canivete' → 'faca')."
    )
    description: str | None = Field(
        default=None, description="Details provided by citizen (color, size, etc)"
    )

    def to_display_string(self) -> str:
        """Format weapon for display in summary."""
        parts = [f"🔪 *{self.type}*"]
        if self.description:
            parts.append(f"\n  {self.description}")
        return "".join(parts)


class WeaponAnalysis(BaseModel):
    """Analysis model for weapons/objects used by aggressor."""

    weapons: list[BOWeapon] = Field(
        description="List of weapons/objects identified as used by aggressor", default_factory=list
    )
    has_weapons: bool = Field(
        description="Whether weapons/objects used were identified", default=False
    )
    confidence: float = Field(
        description="Confidence level in identification (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        default=0.0,
    )
    reasoning: str = Field(
        description="Reasoning about weapon identification (20 words max)", default=""
    )


class UnifiedObjectExtraction(BaseModel):
    """Single-pass extraction of all objects from all available sources.

    This model supports the unified object collection approach, extracting objects
    from: current message + conversation history + scratchpad + existing state.
    """

    stolen_objects: list[BOObject] = Field(
        default_factory=list,
        description="ALL objects found in: current message + conversation history + scratchpad + existing state",
    )

    weapons: list[BOWeapon] = Field(
        default_factory=list, description="Weapons used in the crime (if applicable)"
    )

    completeness_level: Literal["complete", "partial", "minimal"] = Field(
        description="complete: 2+ details per object | partial: 1 detail | minimal: name only"
    )

    needs_followup: bool = Field(
        default=False,
        description="True ONLY if critical info missing AND user likely knows it AND not already said 'don't know'",
    )

    followup_question: str | None = Field(
        default=None,
        description="Natural, friendly question in Portuguese asking for missing details (if needs_followup=True)",
    )

    extraction_summary: str = Field(
        default="",
        description="Brief summary of what was extracted from where (for debugging and logging)",
    )

    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence score for this extraction"
    )


class ObjectFieldUpdate(BaseModel):
    """Update fields of an existing object. None = no change."""

    target_name: str = Field(description="EXACT name from baseline objects")
    brand: str | None = None
    model: str | None = None
    color: str | None = None
    imei: str | None = None
    document_number: str | None = None
    plate: str | None = None
    description: str | None = None


class FollowUpObjectDiff(BaseModel):
    """Diff from follow-up answer. Only new data."""

    objects_to_add: list[BOObject] = Field(default_factory=list)
    objects_to_update: list[ObjectFieldUpdate] = Field(default_factory=list)
    user_declined_info: bool = Field(
        default=False,
        description="True if user explicitly said they don't know the requested info",
    )
    diff_summary: str = Field(default="", description="Brief summary for debugging")
