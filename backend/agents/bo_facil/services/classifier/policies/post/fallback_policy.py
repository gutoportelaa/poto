"""Fallback policy for uncertain classifications.

Handles cases where LLM confidence is too low or LLM failed.

Configuration via environment variables:
- CLASSIFIER_FALLBACK_THRESHOLD: Threshold for API fallback (default: 0.60)
"""

import logging

from core.settings import settings

from ...models import ClassificationClass
from ..base import PolicyAction, PolicyBase, PolicyContext, PolicyResult

logger = logging.getLogger(__name__)


class FallbackPolicy(PolicyBase):
    """Policy that handles fallback for uncertain classifications.

    Priority: 20 (executes after ConfidencePolicy)

    Strategies:
    1. If API and LLM agree, combine confidence
    2. If API has medium confidence, use API result
    3. Default to human handoff for safety

    Environment variables:
        CLASSIFIER_FALLBACK_THRESHOLD: Threshold for API fallback (default: 0.60)
    """

    name = "fallback"
    priority = 20

    def __init__(self, threshold: float | None = None):
        """Initialize with optional configuration.

        Args:
            threshold: Override for fallback threshold. If None, uses ENV.
        """
        self._threshold = (
            threshold if threshold is not None else settings.CLASSIFIER_FALLBACK_THRESHOLD
        )

    @property
    def threshold(self) -> float:
        """Get fallback threshold."""
        return self._threshold

    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Handle fallback when confidence is too low.

        Args:
            context: Policy context with API and LLM results

        Returns:
            RESOLVE with fallback decision, or CONTINUE if no fallback needed
        """
        # Only process if fallback is needed
        if not context.metadata.get("requires_fallback"):
            return PolicyResult(action=PolicyAction.CONTINUE)

        api_result = context.api_result
        llm_result = context.llm_result

        # Try to combine API and LLM results
        if api_result and llm_result:
            emergency_r, human_r = api_result
            api_class = self._get_api_class(emergency_r, human_r)
            api_confidence = context.metadata.get("api_confidence", 0)

            # If both agree and each has minimum confidence, combine
            min_agreement = 0.40
            if (
                api_class == llm_result.classification
                and api_confidence >= min_agreement
                and llm_result.confidence >= min_agreement
            ):
                combined_confidence = (api_confidence + llm_result.confidence) / 2
                logger.info(
                    f"[FallbackPolicy] API+LLM agreement on {api_class.value}, "
                    f"combined confidence: {combined_confidence:.2f}"
                )
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=api_class,
                    confidence=combined_confidence,
                    reason="API+LLM agreement",
                )

            # If API has medium confidence, prefer API
            if api_confidence >= self.threshold:
                logger.info(
                    f"[FallbackPolicy] Using API result ({api_class.value}) "
                    f"with medium confidence: {api_confidence:.2f}"
                )
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=api_class,
                    confidence=api_confidence,
                    reason=f"API medium confidence: {api_confidence:.2f}",
                )

        # If only API available and has result
        if api_result and not llm_result:
            emergency_r, human_r = api_result
            api_class = self._get_api_class(emergency_r, human_r)
            api_confidence = context.metadata.get("api_confidence", 0)

            if api_confidence >= self.threshold:
                logger.info(f"[FallbackPolicy] LLM failed, using API result ({api_class.value})")
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=api_class,
                    confidence=api_confidence,
                    reason="LLM failed, API fallback",
                )

        # Default: fail safe based on flow context
        if self._is_in_bo_treatment(context):
            logger.info("[FallbackPolicy] Uncertainty in BO treatment, defaulting to NEUTRAL")
            return PolicyResult(
                action=PolicyAction.RESOLVE,
                classification=ClassificationClass.NEUTRAL,
                confidence=0.5,
                reason="Uncertainty fallback to neutral (BO treatment context)",
            )

        logger.warning("[FallbackPolicy] Uncertainty too high, failing safe to human")
        return PolicyResult(
            action=PolicyAction.RESOLVE,
            classification=ClassificationClass.HUMAN,
            confidence=0.5,
            reason="Uncertainty fallback to human",
        )

    def _is_in_bo_treatment(self, context: PolicyContext) -> bool:
        """Check if user is already inside BO treatment flow."""
        if not context.state:
            return False
        classification = context.state.get("classification", {})
        cls_type = (
            classification.get("type")
            if isinstance(classification, dict)
            else getattr(classification, "type", None)
        )
        return cls_type == "bo_facil"

    def _get_api_class(self, emergency_result, human_result) -> ClassificationClass:
        """Determine API classification from results.

        Args:
            emergency_result: Emergency classifier result
            human_result: Human classifier result

        Returns:
            ClassificationClass based on API results
        """
        if emergency_result and emergency_result.prediction_class == "emergency":
            return ClassificationClass.EMERGENCY
        if human_result and human_result.prediction_class == "human":
            return ClassificationClass.HUMAN
        return ClassificationClass.NEUTRAL
