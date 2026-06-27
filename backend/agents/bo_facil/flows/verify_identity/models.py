from typing import Literal

from pydantic import BaseModel, Field


class BirthYearAnalysis(BaseModel):
    """Analysis of birth year challenge response"""

    selected_year: int | None = Field(None, description="Selected birth year from the options")
    is_correct: bool = Field(description="Whether the selected year matches records")
    confidence: float = Field(
        description="Confidence level of the analysis (0.0 to 1.0)", ge=0.0, le=1.0
    )
    reasoning: str = Field(
        description="Explanation of how the selection was identified (20 words max)"
    )


class UserDecision(BaseModel):
    """User decision after CPF verification failure"""

    decision: Literal["retry", "proceed_without_cpf"] = Field(
        description="User's decision: retry verification or proceed without CPF"
    )
    confidence: float = Field(
        description="Confidence level of the decision analysis (0.0 to 1.0)", ge=0.0, le=1.0
    )
    reasoning: str = Field(
        description="Explanation of how the decision was identified (20 words max)"
    )
