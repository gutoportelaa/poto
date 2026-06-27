"""Pydantic models for victim data collection."""

from pydantic import BaseModel, Field


class ThirdPartyReporterAnalysis(BaseModel):
    """Model to determine if reporter is the victim or a third-party reporter (witness/bystander).

    Used to detect if the incident happened to another person, triggering victim data collection.
    """

    is_third_party_reporter: bool = Field(
        description=(
            "True if the reporter is NOT the victim (incident happened to another person). "
            "False if the reporter IS the victim or if unclear."
        )
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence level of the analysis (0.0 to 1.0)",
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief explanation of why the reporter is/isn't considered a third-party reporter",
    )
