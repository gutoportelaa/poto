"""Audit policy for logging and metrics.

Centralizes logging for all classification decisions.
"""

import logging

from ..base import PolicyAction, PolicyBase, PolicyContext, PolicyResult

logger = logging.getLogger(__name__)


class AuditPolicy(PolicyBase):
    """Policy that logs classification decisions.

    Priority: 100 (always executes last)

    Logs:
    - User ID
    - Input length
    - Which policy resolved
    - Final classification
    - Confidence score
    """

    name = "audit"
    priority = 100

    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Log classification audit information.

        Args:
            context: Policy context with classification metadata

        Returns:
            Always CONTINUE (audit never changes the result)
        """
        resolved_by = context.metadata.get("resolved_by", "pipeline")
        final_class = context.metadata.get("final_classification")
        final_confidence = context.metadata.get("final_confidence", 0)

        # Format classification for logging
        class_str = final_class.value if hasattr(final_class, "value") else str(final_class)

        # Log the audit entry
        logger.info(
            f"[Audit] "
            f"user={context.user_id or 'unknown'} | "
            f"input_len={len(context.user_input)} | "
            f"resolved_by={resolved_by} | "
            f"class={class_str} | "
            f"confidence={final_confidence:.2f}"
        )

        # Log additional context if available
        if context.metadata.get("api_error"):
            logger.debug(f"[Audit] API error: {context.metadata['api_error']}")

        if context.metadata.get("requires_fallback"):
            logger.debug("[Audit] Fallback was triggered")

        return PolicyResult(action=PolicyAction.CONTINUE)
