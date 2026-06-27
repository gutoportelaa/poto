"""API-based classifier service using BERT models for emergency and human handoff detection."""

import asyncio
import logging
import uuid

import httpx

from core.settings import settings

from .models import (
    ClassificationResult,
    ClassifierType,
    EmergencyClassificationRequest,
    EmergencyClassificationResponse,
    HumanClassificationRequest,
    HumanClassificationResponse,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 2.0


class APIClassifierService:
    """Service for emergency and human classification using external BERT APIs."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, verify=settings.CLASSIFIER_VERIFY_SSL
        )

    async def classify_message(
        self,
        message: str,
        classifier_type: ClassifierType,
        user_id: str | None = None,
    ) -> ClassificationResult | None:
        """
        Classify a message using the specified classifier.

        Args:
            message: The message text to classify
            classifier_type: Type of classifier to use (emergency or human)
            user_id: Optional user ID (defaults to random UUID)

        Returns:
            Classification result or None if API fails or is disabled
        """
        if not settings.CLASSIFIER_API_ENABLED:
            return None

        if classifier_type == ClassifierType.EMERGENCY:
            return await self._classify_emergency(message, user_id)
        elif classifier_type == ClassifierType.HUMAN:
            return await self._classify_human(message, user_id)
        else:
            logger.error(f"[APIClassifierService] Unknown classifier type: {classifier_type}")
            return None

    async def _classify_emergency(
        self, message: str, user_id: str | None = None
    ) -> ClassificationResult | None:
        """Classify message for emergency content."""
        if not settings.EMERGENCY_CLASSIFIER_KEY:
            logger.warning("[APIClassifierService] No emergency API key configured")
            return None

        if not settings.EMERGENCY_CLASSIFIER_URL:
            logger.warning("[APIClassifierService] No emergency API URL configured")
            return None

        request_uuid = user_id or str(uuid.uuid4())
        request_data = EmergencyClassificationRequest(uuid=request_uuid, text=message)

        for attempt in range(2):  # 1 initial + 1 retry
            try:
                if attempt > 0:
                    await asyncio.sleep(0.5)
                    logger.info("[APIClassifierService] Emergency classification retry")

                response = await self.client.post(
                    settings.EMERGENCY_CLASSIFIER_URL,
                    json=request_data.model_dump(),
                    headers={
                        "accept": "application/json",
                        "Authorization": f"Bearer {settings.EMERGENCY_CLASSIFIER_KEY.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code == 200:
                    result = EmergencyClassificationResponse.model_validate(response.json())
                    logger.info(
                        f"[APIClassifierService] Emergency result: {result.prediction.class_} "
                        f"(confidence: {result.prediction.confidence})"
                    )
                    return ClassificationResult(
                        classifier_type=ClassifierType.EMERGENCY,
                        prediction_class=result.prediction.class_,
                        confidence=result.prediction.confidence,
                        uuid=result.uuid,
                        conversation_text=result.conversation_text,
                        raw_response=result,
                    )
                else:
                    logger.warning(
                        f"[APIClassifierService] Emergency API returned status {response.status_code}"
                    )

            except TimeoutError:
                logger.warning(
                    f"[APIClassifierService] Emergency classification timeout (attempt {attempt + 1}/2)"
                )
            except Exception as e:
                logger.error(f"[APIClassifierService] Emergency classification error: {str(e)}")
                return None  # Non-transient error, don't retry

        return None

    async def _classify_human(
        self, message: str, user_id: str | None = None
    ) -> ClassificationResult | None:
        """Classify message for human handoff need."""
        if not settings.HUMAN_CLASSIFIER_KEY:
            logger.warning("[APIClassifierService] No human classifier API key configured")
            return None

        if not settings.HUMAN_CLASSIFIER_URL:
            logger.warning("[APIClassifierService] No human classifier API URL configured")
            return None

        request_uuid = user_id or str(uuid.uuid4())
        request_data = HumanClassificationRequest(uuid=request_uuid, text=message)

        for attempt in range(2):  # 1 initial + 1 retry
            try:
                if attempt > 0:
                    await asyncio.sleep(0.5)
                    logger.info("[APIClassifierService] Human classification retry")

                response = await self.client.post(
                    settings.HUMAN_CLASSIFIER_URL,
                    json=request_data.model_dump(),
                    headers={
                        "accept": "application/json",
                        "Authorization": f"Bearer {settings.HUMAN_CLASSIFIER_KEY.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code == 200:
                    result = HumanClassificationResponse.model_validate(response.json())
                    logger.info(
                        f"[APIClassifierService] Human result: {result.prediction.class_} "
                        f"(confidence: {result.prediction.confidence})"
                    )
                    return ClassificationResult(
                        classifier_type=ClassifierType.HUMAN,
                        prediction_class=result.prediction.class_,
                        confidence=result.prediction.confidence,
                        uuid=result.uuid,
                        conversation_text=result.conversation_text,
                        raw_response=result,
                    )
                else:
                    logger.warning(
                        f"[APIClassifierService] Human API returned status {response.status_code}"
                    )

            except TimeoutError:
                logger.warning(
                    f"[APIClassifierService] Human classification timeout (attempt {attempt + 1}/2)"
                )
            except Exception as e:
                logger.error(f"[APIClassifierService] Human classification error: {str(e)}")
                return None  # Non-transient error, don't retry

        return None

    async def is_emergency(
        self, message: str, confidence_threshold: float = 0.8, user_id: str | None = None
    ) -> bool:
        """
        Simple helper to check if message is emergency.

        Args:
            message: Message to classify
            confidence_threshold: Minimum confidence for emergency classification
            user_id: Optional user ID

        Returns:
            True if emergency detected with sufficient confidence
        """
        result = await self.classify_message(message, ClassifierType.EMERGENCY, user_id)
        return result.is_emergency(confidence_threshold) if result else False

    async def needs_human_handoff(
        self, message: str, confidence_threshold: float = 0.8, user_id: str | None = None
    ) -> bool:
        """
        Simple helper to check if message needs human handoff.

        Args:
            message: Message to classify
            confidence_threshold: Minimum confidence for human classification
            user_id: Optional user ID

        Returns:
            True if human handoff needed with sufficient confidence
        """
        result = await self.classify_message(message, ClassifierType.HUMAN, user_id)
        return result.needs_human_handoff(confidence_threshold) if result else False

    async def classify_both(
        self,
        message: str,
        user_id: str | None = None,
        emergency_threshold: float = 0.8,
        human_threshold: float = 0.8,
    ) -> tuple[bool, bool]:
        """
        Classify message with both classifiers and return boolean results.

        Args:
            message: Message to classify
            user_id: Optional user ID
            emergency_threshold: Threshold for emergency detection
            human_threshold: Threshold for human handoff detection

        Returns:
            Tuple of (is_emergency, needs_human) booleans
        """
        emergency_result = await self.classify_message(message, ClassifierType.EMERGENCY, user_id)
        human_result = await self.classify_message(message, ClassifierType.HUMAN, user_id)

        is_emergency = (
            emergency_result.is_emergency(emergency_threshold) if emergency_result else False
        )
        needs_human = human_result.needs_human_handoff(human_threshold) if human_result else False

        return is_emergency, needs_human

    async def classify_both_with_results(
        self,
        message: str,
        user_id: str | None = None,
    ) -> tuple[ClassificationResult | None, ClassificationResult | None]:
        """
        Classify message with both classifiers and return raw results.

        Args:
            message: Message to classify
            user_id: Optional user ID

        Returns:
            Tuple of (emergency_result, human_result) ClassificationResult objects
        """
        emergency_result = await self.classify_message(message, ClassifierType.EMERGENCY, user_id)
        human_result = await self.classify_message(message, ClassifierType.HUMAN, user_id)

        return emergency_result, human_result

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global instance
api_classifier_service = APIClassifierService()
