"""Models for anonymous report flow."""

from pydantic import BaseModel, Field


class AnonymousReportAnalysis(BaseModel):
    """Analysis of anonymous report for crime classification."""

    crime_detected: str = Field(
        description='Whether specific crimes were identified: "yes" or "no"'
    )
    crime_type_codes: str | None = Field(
        default=None, description="Comma-separated IDs of crime types identified (e.g., '26,30,31')"
    )

    class Config:
        """Pydantic config."""

        json_schema_extra = {"example": {"crime_detected": "yes", "crime_type_codes": "30,31"}}


class CityValidation(BaseModel):
    """Validation of city name from user input."""

    is_valid: str = Field(description='Whether a city name was identified: "yes" or "no"')
    city_name: str | None = Field(default=None, description="Name of the city if identified")
