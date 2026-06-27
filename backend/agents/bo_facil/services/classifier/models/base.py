"""Base enums for classifier models."""

from enum import Enum


class ClassifierType(str, Enum):
    """Types of classifiers available."""

    EMERGENCY = "emergency"
    HUMAN = "human"


class ClassificationStrategy(str, Enum):
    """Strategy for classification."""

    API_ONLY = "api_only"
    LLM_ONLY = "llm_only"
    HYBRID = "hybrid"


class ClassificationClass(str, Enum):
    """Possible classification results."""

    EMERGENCY = "emergency"
    HUMAN = "human"
    NEUTRAL = "neutral"
    CANCEL = "cancel"
