"""Classifier services for emergency and human handoff detection.

Uses policy-based classification pipeline (Chain of Responsibility pattern).

Structure:
- models/: Pydantic models for classification
  - base.py: Enums (ClassificationClass, ClassificationStrategy, ClassifierType)
  - api.py: API request/response models
  - llm.py: LLM indicator/result models
  - result.py: ClassificationResult (pipeline output)
- policies/: Policy-based classification
  - base.py: PolicyBase, PolicyContext, PolicyResult, PolicyAction
  - pre/: Pre-policies (before LLM)
    - regex_policy.py: Fast-path regex detection
    - api_policy.py: BERT API classifier
  - post/: Post-policies (after LLM)
    - confidence_policy.py: Confidence validation
    - fallback_policy.py: Uncertainty handling
    - audit_policy.py: Logging/metrics
- pipeline.py: ClassifierPipeline orchestrator
- api_service.py: BERT API-based classifier
- llm_service.py: LLM-based classifier
- hooks.py: Webhook payload contracts
- prompts.py: LLM prompts
- utils.py: Classification utilities (classify_and_interrupt)
"""

# Core models (re-exported from models/)
# API Service
from .api_service import (
    APIClassifierService,
    api_classifier_service,
)

# Hook Contracts
from .hooks import (
    EmergencyContext,
    EmergencyHookPayload,
    HandoffContext,
    HandoffHookPayload,
    HandoffReason,
)

# LLM Service
from .llm_service import (
    classify_emergency_with_llm,
    classify_human_handoff_with_llm,
    classify_with_llm,
    extract_context_from_state,
)

# Media detection
from .media import is_media_url
from .models import (
    # Base enums
    ClassificationClass,
    # API models
    ClassificationResult,
    ClassificationStrategy,
    ClassifierType,
    EmergencyClassificationRequest,
    EmergencyClassificationResponse,
    # LLM models
    EmergencyIndicators,
    EmergencyPrediction,
    HumanClassificationRequest,
    HumanClassificationResponse,
    HumanHandoffIndicators,
    HumanPrediction,
    # Result model
    HybridClassificationResult,
    LLMClassificationResult,
)

# Policy-based Pipeline
from .pipeline import ClassifierPipeline
from .policies import PolicyAction, PolicyBase, PolicyContext, PolicyResult
from .policies.post import AuditPolicy, ConfidencePolicy, FallbackPolicy
from .policies.pre import ApiPolicy, RegexPolicy

# Utilities
from .utils import (
    classify_and_interrupt,
    redirect_to_cancel,
    redirect_to_emergency,
    redirect_to_human,
)

__all__ = [
    # Base Enums
    "ClassificationClass",
    "ClassificationStrategy",
    "ClassifierType",
    # API Models
    "ClassificationResult",
    "EmergencyClassificationRequest",
    "EmergencyClassificationResponse",
    "EmergencyPrediction",
    "HumanClassificationRequest",
    "HumanClassificationResponse",
    "HumanPrediction",
    # LLM Models
    "EmergencyIndicators",
    "HumanHandoffIndicators",
    "LLMClassificationResult",
    # Result Model
    "HybridClassificationResult",
    # Services
    "APIClassifierService",
    "api_classifier_service",
    # LLM Service
    "classify_with_llm",
    "classify_emergency_with_llm",
    "classify_human_handoff_with_llm",
    "extract_context_from_state",
    # Hook Contracts
    "EmergencyContext",
    "EmergencyHookPayload",
    "HandoffContext",
    "HandoffHookPayload",
    "HandoffReason",
    # Media detection
    "is_media_url",
    # Utilities
    "classify_and_interrupt",
    "redirect_to_cancel",
    "redirect_to_emergency",
    "redirect_to_human",
    # Pipeline
    "ClassifierPipeline",
    # Policies - Base
    "PolicyAction",
    "PolicyBase",
    "PolicyContext",
    "PolicyResult",
    # Policies - Pre
    "ApiPolicy",
    "RegexPolicy",
    # Policies - Post
    "AuditPolicy",
    "ConfidencePolicy",
    "FallbackPolicy",
]
