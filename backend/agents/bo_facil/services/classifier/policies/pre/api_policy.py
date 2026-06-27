"""API-based policy using BERT classifier.

Wraps the existing APIClassifierService for high-confidence classifications.

Configuration via environment variables:
- CLASSIFIER_API_POLICY_ENABLED: Enable/disable this policy (default: True)
- CLASSIFIER_API_POLICY_THRESHOLD: Confidence threshold to resolve (default: 0.85)
"""

import logging
from typing import TYPE_CHECKING

from core.settings import settings

from ...models import ClassificationClass
from ..base import PolicyAction, PolicyBase, PolicyContext, PolicyResult

if TYPE_CHECKING:
    from ...api_service import APIClassifierService

logger = logging.getLogger(__name__)


class ApiPolicy(PolicyBase):
    """Policy that uses the BERT API classifier.

    Priority: 20 (executes after RegexPolicy)

    Only resolves if confidence >= threshold (configurable via ENV).
    For lower confidence, continues to LLM classification.

    Environment variables:
        CLASSIFIER_API_POLICY_ENABLED: Set to "false" to disable this policy
        CLASSIFIER_API_POLICY_THRESHOLD: Confidence threshold (default: 0.85)
    """

    name = "api"
    priority = 20

    def __init__(
        self,
        api_service: "APIClassifierService | None" = None,
        enabled: bool | None = None,
        threshold: float | None = None,
    ):
        """Initialize with optional API service and configuration.

        Args:
            api_service: APIClassifierService instance. If None, creates new instance.
            enabled: Override for policy enabled state. If None, uses ENV.
            threshold: Override for confidence threshold. If None, uses ENV.
        """
        self._api_service = api_service
        self._enabled = enabled if enabled is not None else settings.CLASSIFIER_API_POLICY_ENABLED
        self._threshold = (
            threshold if threshold is not None else settings.CLASSIFIER_API_POLICY_THRESHOLD
        )

    @property
    def enabled(self) -> bool:
        """Check if policy is enabled."""
        return self._enabled

    @property
    def threshold(self) -> float:
        """Get confidence threshold."""
        return self._threshold

    @property
    def api_service(self) -> "APIClassifierService":
        """Lazy initialization of API service."""
        if self._api_service is None:
            from ...api_service import APIClassifierService

            self._api_service = APIClassifierService()
        return self._api_service

    def should_skip(self, context: PolicyContext) -> bool:
        """Skip this policy if disabled via environment variable.

        Args:
            context: Policy context (unused)

        Returns:
            True if policy is disabled, False otherwise
        """
        if not self.enabled:
            logger.debug("[ApiPolicy] Skipped - disabled via CLASSIFIER_API_POLICY_ENABLED=false")
            return True
        return False

    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Call BERT API classifier and resolve if high confidence.

        Args:
            context: Policy context with user input

        Returns:
            RESOLVE if high confidence, CONTINUE otherwise
        """
        try:
            emergency_result, human_result = await self.api_service.classify_both_with_results(
                context.user_input, context.user_id
            )

            # Store results in context for post-policies
            context.api_result = (emergency_result, human_result)

            # Check emergency with high confidence
            if emergency_result and emergency_result.is_emergency(self.threshold):
                logger.info(
                    f"[ApiPolicy] Emergency detected with confidence {emergency_result.confidence:.2f} "
                    f"(threshold: {self.threshold})"
                )
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.EMERGENCY,
                    confidence=emergency_result.confidence,
                    reason=f"API emergency: {emergency_result.confidence:.2f} >= {self.threshold}",
                )

            # Check human handoff with high confidence
            if human_result and human_result.needs_human_handoff(self.threshold):
                logger.info(
                    f"[ApiPolicy] Human handoff detected with confidence {human_result.confidence:.2f} "
                    f"(threshold: {self.threshold})"
                )
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.HUMAN,
                    confidence=human_result.confidence,
                    reason=f"API human handoff: {human_result.confidence:.2f} >= {self.threshold}",
                )

            # Store confidence for post-policies (used by FallbackPolicy)
            api_confidence = max(
                emergency_result.confidence if emergency_result else 0,
                human_result.confidence if human_result else 0,
            )
            context.metadata["api_confidence"] = api_confidence
            context.metadata["api_emergency_confidence"] = (
                emergency_result.confidence if emergency_result else 0
            )
            context.metadata["api_human_confidence"] = (
                human_result.confidence if human_result else 0
            )

            logger.debug(f"[ApiPolicy] Low confidence ({api_confidence:.2f}), continuing to LLM")
            return PolicyResult(
                action=PolicyAction.CONTINUE,
                metadata={"api_confidence": api_confidence},
            )

        except Exception as e:
            logger.warning(f"[ApiPolicy] API classification failed: {e}")
            context.metadata["api_error"] = str(e)
            return PolicyResult(
                action=PolicyAction.CONTINUE,
                reason=f"API error: {str(e)}",
            )
