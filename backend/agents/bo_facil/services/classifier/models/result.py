"""Classification result model for pipeline output."""

from pydantic import BaseModel, Field

from .api import ClassificationResult
from .base import ClassificationClass, ClassificationStrategy
from .llm import LLMClassificationResult


class HybridClassificationResult(BaseModel):
    """Result from classification pipeline.

    Note: Class name kept as HybridClassificationResult for backward compatibility,
    even though it's now produced by the policy-based pipeline.
    """

    final_class: ClassificationClass = Field(description="Final classification decision")
    confidence: float = Field(ge=0.0, le=1.0, description="Final confidence score")
    strategy_used: ClassificationStrategy = Field(description="Which strategy was used")
    api_result: ClassificationResult | None = Field(
        default=None, description="Result from API classifier if used"
    )
    llm_result: LLMClassificationResult | None = Field(
        default=None, description="Result from LLM classifier if used"
    )
    reasoning: str | None = Field(default=None, description="Explanation of the decision")

    def is_emergency(self) -> bool:
        """Check if final classification is emergency."""
        return self.final_class == ClassificationClass.EMERGENCY

    def needs_human_handoff(self) -> bool:
        """Check if final classification requires human handoff."""
        return self.final_class == ClassificationClass.HUMAN

    def is_cancel(self) -> bool:
        """Check if user requested cancellation."""
        return self.final_class == ClassificationClass.CANCEL
