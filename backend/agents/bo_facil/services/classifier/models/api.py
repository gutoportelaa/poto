"""API request/response models for BERT-based classifiers."""

from pydantic import BaseModel, Field

from .base import ClassifierType


class EmergencyClassificationRequest(BaseModel):
    """Request model for emergency classification API."""

    uuid: str
    text: str


class HumanClassificationRequest(BaseModel):
    """Request model for human classification API."""

    uuid: str
    text: str


class EmergencyPrediction(BaseModel):
    """Prediction result from emergency classification API."""

    class_: str = Field(alias="class")
    confidence: float


class HumanPrediction(BaseModel):
    """Prediction result from human classification API."""

    class_: str = Field(alias="class")
    confidence: float


class EmergencyClassificationResponse(BaseModel):
    """Response model from emergency classification API."""

    uuid: str
    prediction: EmergencyPrediction
    conversation_text: str


class HumanClassificationResponse(BaseModel):
    """Response model from human classification API."""

    uuid: str
    prediction: HumanPrediction
    conversation_text: str


class ClassificationResult(BaseModel):
    """Unified result from any API classifier."""

    classifier_type: ClassifierType
    prediction_class: str
    confidence: float
    uuid: str
    conversation_text: str
    raw_response: EmergencyClassificationResponse | HumanClassificationResponse

    def is_emergency(self, threshold: float = 0.8) -> bool:
        """Check if result indicates emergency with sufficient confidence."""
        return (
            self.classifier_type == ClassifierType.EMERGENCY
            and self.prediction_class == "emergency"
            and self.confidence >= threshold
        )

    def needs_human_handoff(self, threshold: float = 0.8) -> bool:
        """Check if result indicates need for human handoff with sufficient confidence."""
        return (
            self.classifier_type == ClassifierType.HUMAN
            and self.prediction_class == "human"
            and self.confidence >= threshold
        )
