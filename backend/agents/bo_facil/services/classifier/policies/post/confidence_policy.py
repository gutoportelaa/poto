"""Confidence validation policy.

Validates that LLM classification meets minimum confidence threshold.

Configuration via environment variables:
- CLASSIFIER_MIN_CONFIDENCE: Minimum confidence threshold (default: 0.60)
"""

from core.settings import settings

from ..base import PolicyAction, PolicyBase, PolicyContext, PolicyResult


class ConfidencePolicy(PolicyBase):
    """Policy that validates LLM confidence meets minimum threshold.

    Priority: 10 (executes first among post-policies)

    If confidence is below threshold, marks for fallback.

    Environment variables:
        CLASSIFIER_MIN_CONFIDENCE: Minimum confidence threshold (default: 0.60)
    """

    name = "confidence"
    priority = 10

    def __init__(self, min_confidence: float | None = None):
        """Initialize with optional configuration.

        Args:
            min_confidence: Override for minimum confidence. If None, uses ENV.
        """
        self._min_confidence = (
            min_confidence if min_confidence is not None else settings.CLASSIFIER_MIN_CONFIDENCE
        )

    @property
    def min_confidence(self) -> float:
        """Get minimum confidence threshold."""
        return self._min_confidence

    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Validate LLM result confidence.

        Args:
            context: Policy context with LLM result

        Returns:
            CONTINUE if confidence is acceptable, REJECT if too low
        """
        llm_result = context.llm_result

        # No LLM result - need fallback
        if not llm_result:
            context.metadata["requires_fallback"] = True
            return PolicyResult(
                action=PolicyAction.REJECT,
                reason="No LLM result available",
            )

        # Low confidence - need fallback
        if llm_result.confidence < self.min_confidence:
            context.metadata["requires_fallback"] = True
            return PolicyResult(
                action=PolicyAction.REJECT,
                confidence=llm_result.confidence,
                reason=f"Low confidence: {llm_result.confidence:.2f} < {self.min_confidence}",
            )

        # Acceptable confidence - continue
        return PolicyResult(
            action=PolicyAction.CONTINUE,
            classification=llm_result.classification,
            confidence=llm_result.confidence,
        )
