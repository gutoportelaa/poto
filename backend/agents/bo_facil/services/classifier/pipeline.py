"""Classifier Pipeline - Chain of Responsibility orchestrator.

Replaces HybridClassifierService with a policy-based architecture.
"""

import logging
from typing import TYPE_CHECKING

from langchain_core.runnables import RunnableConfig

from agents.bo_facil.core import circuit_state
from agents.bo_facil.core.llm_fallback import _get_thread_id
from core.observability import set_run_metadata
from core.settings import settings

from .llm_service import classify_with_llm, extract_context_from_state
from .models import ClassificationClass, ClassificationStrategy, HybridClassificationResult
from .policies.base import PolicyAction, PolicyBase, PolicyContext

if TYPE_CHECKING:
    from agents.bo_facil.core.states import BOState

logger = logging.getLogger(__name__)


class ClassifierPipeline:
    """Pipeline that orchestrates classification through policies.

    Executes pre-policies → LLM → post-policies in sequence.
    Pre-policies can short-circuit (RESOLVE) to skip LLM.
    Post-policies validate and process LLM results.
    """

    def __init__(
        self,
        pre_policies: list[PolicyBase],
        post_policies: list[PolicyBase],
    ):
        """Initialize pipeline with policies.

        Args:
            pre_policies: Policies executed before LLM (sorted by priority)
            post_policies: Policies executed after LLM (sorted by priority)
        """
        self.pre_policies = sorted(pre_policies, key=lambda p: p.priority)
        self.post_policies = sorted(post_policies, key=lambda p: p.priority)

    async def classify(
        self,
        message: str,
        state: "BOState",
        config: RunnableConfig,
        user_id: str | None = None,
        skip_llm: bool = False,
    ) -> HybridClassificationResult:
        """Execute classification pipeline.

        Args:
            message: User message to classify
            state: Current BOState for context
            config: RunnableConfig with model configuration
            user_id: Optional user ID for logging

        Returns:
            HybridClassificationResult with final classification
        """
        logger.info("[Pipeline] Starting classification")

        # Create shared context
        context = PolicyContext(
            user_input=message,
            user_id=user_id,
            conversation_id=state.get("conversation_id") if state else None,
            state=dict(state) if state else None,
        )

        # 1. Execute pre-policies
        for policy in self.pre_policies:
            if policy.should_skip(context):
                logger.debug(f"[Pipeline] Skipping pre-policy: {policy.name}")
                continue

            logger.debug(f"[Pipeline] Executing pre-policy: {policy.name}")
            result = await policy.execute(context)

            if result.action == PolicyAction.RESOLVE:
                logger.info(f"[Pipeline] Resolved by pre-policy: {policy.name}")
                context.metadata["resolved_by"] = policy.name
                context.metadata["final_classification"] = result.classification
                context.metadata["final_confidence"] = result.confidence
                await self._run_audit(context)
                return self._to_hybrid_result(result, ClassificationStrategy.HYBRID, policy.name)

        # 2. Skip LLM if requested (data collection nodes where emergency risk is minimal)
        if skip_llm:
            logger.info("[Pipeline] skip_llm=True, defaulting to NEUTRAL")
            context.metadata["resolved_by"] = "skip_llm"
            context.metadata["final_classification"] = ClassificationClass.NEUTRAL
            context.metadata["final_confidence"] = 0.9
            await self._run_audit(context)
            return HybridClassificationResult(
                final_class=ClassificationClass.NEUTRAL,
                confidence=0.9,
                strategy_used=ClassificationStrategy.HYBRID,
                api_result=None,
                llm_result=None,
                reasoning="skip_llm: pre-policies did not detect emergency/human",
            )

        # 3. Execute LLM classification
        llm_context = extract_context_from_state(state) if state else None
        thread_id = _get_thread_id(config)
        use_fallback = await circuit_state.is_thread_degraded(thread_id) and settings.FALLBACK_MODEL

        if use_fallback:
            logger.info(f"[Pipeline] Thread {thread_id} degraded, using fallback directly")

        try:
            logger.debug("[Pipeline] Executing LLM classification")
            if use_fallback:
                context.llm_result = await classify_with_llm(
                    message, llm_context, config, model_override=settings.FALLBACK_MODEL
                )
                context.metadata["used_fallback_model"] = True
            else:
                context.llm_result = await classify_with_llm(message, llm_context, config)
            logger.debug(
                f"[Pipeline] LLM result: {context.llm_result.classification.value} "
                f"(confidence={context.llm_result.confidence:.2f})"
            )
        except Exception as e:
            logger.error(f"[Pipeline] LLM classification failed: {e}")
            context.metadata["llm_error"] = str(e)

            # Retry with fallback model before giving up
            if not use_fallback and settings.FALLBACK_MODEL:
                await circuit_state.mark_thread_degraded(thread_id)
                await circuit_state.record_global_failure()
                try:
                    logger.warning(
                        f"[Pipeline] Retrying classification with fallback: {settings.FALLBACK_MODEL}"
                    )
                    context.llm_result = await classify_with_llm(
                        message, llm_context, config, model_override=settings.FALLBACK_MODEL
                    )
                    context.metadata["used_fallback_model"] = True
                    logger.info(
                        f"[Pipeline] Fallback succeeded: {context.llm_result.classification.value} "
                        f"(confidence={context.llm_result.confidence:.2f})"
                    )
                except Exception as fallback_err:
                    logger.error(f"[Pipeline] Fallback model also failed: {fallback_err}")
                    context.llm_result = None
            else:
                context.llm_result = None

        # 4. Execute post-policies
        final_result = None

        for policy in self.post_policies:
            if policy.should_skip(context):
                logger.debug(f"[Pipeline] Skipping post-policy: {policy.name}")
                continue

            logger.debug(f"[Pipeline] Executing post-policy: {policy.name}")
            result = await policy.execute(context)

            if result.action == PolicyAction.RESOLVE:
                logger.info(f"[Pipeline] Resolved by post-policy: {policy.name}")
                context.metadata["resolved_by"] = policy.name
                final_result = result
                break
            elif result.action == PolicyAction.REJECT:
                logger.debug(
                    f"[Pipeline] Rejected by post-policy: {policy.name}, triggering fallback"
                )
                context.metadata["requires_fallback"] = True

        # 5. Determine final classification
        if final_result:
            context.metadata["final_classification"] = final_result.classification
            context.metadata["final_confidence"] = final_result.confidence
            await self._run_audit(context)
            return self._to_hybrid_result(
                final_result,
                ClassificationStrategy.HYBRID,
                context.metadata.get("resolved_by", "fallback"),
            )

        # Use LLM result if available
        if context.llm_result:
            context.metadata["resolved_by"] = "llm"
            context.metadata["final_classification"] = context.llm_result.classification
            context.metadata["final_confidence"] = context.llm_result.confidence
            await self._run_audit(context)
            return HybridClassificationResult(
                final_class=context.llm_result.classification,
                confidence=context.llm_result.confidence,
                strategy_used=ClassificationStrategy.HYBRID,
                api_result=None,
                llm_result=context.llm_result,
                reasoning=context.llm_result.reasoning,
            )

        # 6. Fail-safe to human
        logger.warning("[Pipeline] All classification methods failed, failing safe to human")
        context.metadata["resolved_by"] = "fail_safe"
        context.metadata["final_classification"] = ClassificationClass.HUMAN
        context.metadata["final_confidence"] = 0.0
        await self._run_audit(context)
        return HybridClassificationResult(
            final_class=ClassificationClass.HUMAN,
            confidence=0.0,
            strategy_used=ClassificationStrategy.HYBRID,
            api_result=None,
            llm_result=None,
            reasoning="Pipeline fail-safe: all classification methods failed",
        )

    async def _run_audit(self, context: PolicyContext) -> None:
        """Execute audit policy AND forward classification metadata to LangSmith trace.

        Args:
            context: Policy context with classification metadata
        """
        # Forward to LangSmith trace BEFORE running audit policy so that even if
        # audit raises (e.g. log handler error), classifier metadata still lands
        # on the trace for dashboards.
        final_class = context.metadata.get("final_classification")
        forwarded = {
            "classifier_resolved_by": context.metadata.get("resolved_by"),
            "classifier_class": final_class.value if final_class else None,
            "classifier_confidence": context.metadata.get("final_confidence"),
        }
        if context.metadata.get("used_fallback_model"):
            forwarded["classifier_used_fallback"] = True
        set_run_metadata({k: v for k, v in forwarded.items() if v is not None})

        for policy in self.post_policies:
            if policy.name == "audit":
                await policy.execute(context)
                break

    def _to_hybrid_result(
        self,
        result,
        strategy: ClassificationStrategy,
        resolved_by: str,
    ) -> HybridClassificationResult:
        """Convert policy result to HybridClassificationResult.

        Args:
            result: PolicyResult from a policy
            strategy: Classification strategy used
            resolved_by: Name of policy that resolved

        Returns:
            HybridClassificationResult for compatibility
        """
        return HybridClassificationResult(
            final_class=result.classification,
            confidence=result.confidence,
            strategy_used=strategy,
            api_result=None,
            llm_result=None,
            reasoning=f"[{resolved_by}] {result.reason}",
        )
