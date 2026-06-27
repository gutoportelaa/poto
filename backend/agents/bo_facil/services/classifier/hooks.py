"""Hook payload contracts for emergency and human handoff notifications.

These models define the JSON structure for webhook payloads that will be sent
to external systems when emergency or human handoff events occur.

NOTE: Actual webhook sending is not implemented yet - only contracts are defined.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import HybridClassificationResult

# =============================================================================
# Emergency Hook Contracts
# =============================================================================


class EmergencyContext(BaseModel):
    """Context information for emergency hook."""

    last_message: str = Field(description="The message that triggered emergency detection")
    classification: str = Field(default="emergency", description="Classification type")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Classification confidence")
    strategy_used: str = Field(
        description="Classification strategy used (api_only, llm_only, hybrid)"
    )
    indicators: list[str] = Field(
        default_factory=list, description="List of emergency indicators found"
    )
    reasoning: str | None = Field(default=None, description="Explanation of the classification")


class EmergencyHookPayload(BaseModel):
    """
    Payload for emergency webhook notification.

    This payload is sent when an emergency is detected to notify
    external systems (monitoring dashboards, alert systems, etc.).

    Example:
    ```json
    {
        "type": "emergency",
        "priority": "high",
        "conversation_id": "conv_123",
        "sender_id": "user_456",
        "phone": "+5511999999999",
        "timestamp": "2024-01-22T10:30:00Z",
        "context": {
            "last_message": "socorro me ajuda",
            "classification": "emergency",
            "confidence_score": 0.95,
            "strategy_used": "hybrid",
            "indicators": ["pedido de socorro", "urgência"],
            "reasoning": "User explicitly asking for help"
        }
    }
    ```
    """

    type: Literal["emergency"] = Field(default="emergency", description="Event type")
    priority: Literal["high", "critical"] = Field(
        default="high", description="Priority level (critical for imminent threats)"
    )
    conversation_id: str = Field(description="GovChat conversation ID")
    sender_id: str = Field(description="User/sender ID")
    phone: str = Field(description="User phone number")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO 8601 timestamp",
    )
    context: EmergencyContext = Field(description="Emergency context details")

    @classmethod
    def from_classification(
        cls,
        result: HybridClassificationResult,
        conversation_id: str,
        sender_id: str,
        phone: str,
        message: str,
    ) -> "EmergencyHookPayload":
        """Create payload from classification result."""
        indicators = []
        if result.llm_result:
            indicators = result.llm_result.emergency_indicators

        return cls(
            conversation_id=conversation_id,
            sender_id=sender_id,
            phone=phone,
            priority="critical" if result.confidence >= 0.9 else "high",
            context=EmergencyContext(
                last_message=message,
                classification="emergency",
                confidence_score=result.confidence,
                strategy_used=result.strategy_used.value,
                indicators=indicators,
                reasoning=result.reasoning,
            ),
        )


# =============================================================================
# Human Handoff Hook Contracts
# =============================================================================


class HandoffContext(BaseModel):
    """Context information for human handoff hook."""

    conversation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent conversation messages (last N)",
    )
    collected_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Data collected so far (bo_fact, bo_location, etc.)",
    )
    current_node: str = Field(description="Node where handoff was triggered")
    classification_result: dict[str, Any] | None = Field(
        default=None, description="Classification result that triggered handoff (if any)"
    )


class HandoffHookPayload(BaseModel):
    """
    Payload for human handoff webhook notification.

    This payload is sent when a conversation is transferred to a human agent,
    providing full context for the agent to continue the conversation.

    Example:
    ```json
    {
        "type": "handoff",
        "reason": "classifier_detected",
        "conversation_id": "conv_123",
        "sender_id": "user_456",
        "phone": "+5511999999999",
        "timestamp": "2024-01-22T10:30:00Z",
        "agent_state": {"team_id": 23, "handoff_name": "João"},
        "context": {
            "conversation_history": [
                {"role": "user", "content": "preciso de ajuda"},
                {"role": "bot", "content": "Como posso ajudar?"}
            ],
            "collected_data": {
                "bo_fact": "roubo",
                "bo_location": "Centro"
            },
            "current_node": "collect_location_node",
            "classification_result": null
        }
    }
    ```
    """

    type: Literal["handoff"] = Field(default="handoff", description="Event type")
    reason: str = Field(
        description="Reason for handoff: user_requested, bot_limit, classifier_detected, fail_safe"
    )
    conversation_id: str = Field(description="GovChat conversation ID")
    sender_id: str = Field(description="User/sender ID")
    phone: str = Field(description="User phone number")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="ISO 8601 timestamp",
    )
    agent_state: dict[str, Any] = Field(
        default_factory=dict, description="Current agent state (team_id, name, etc.)"
    )
    context: HandoffContext = Field(description="Handoff context details")

    @classmethod
    def from_state(
        cls,
        state: dict[str, Any],
        reason: str,
        current_node: str,
        classification_result: HybridClassificationResult | None = None,
        max_history: int = 10,
    ) -> "HandoffHookPayload":
        """Create payload from agent state."""
        # Extract conversation history
        messages = state.get("messages", [])
        history = []
        for msg in messages[-max_history:]:
            if hasattr(msg, "content"):
                content = msg.content
                # Skip JSON messages
                if not content.startswith("{"):
                    history.append(
                        {
                            "role": "user" if msg.type == "human" else "bot",
                            "content": content,
                        }
                    )

        # Extract collected data
        collected_data = {k: v for k, v in state.items() if k.startswith("bo_") and v is not None}

        # Classification result dict
        classification_dict = None
        if classification_result:
            classification_dict = classification_result.model_dump()

        return cls(
            conversation_id=state.get("conversation_id", "unknown"),
            sender_id=state.get("sender_id", "unknown"),
            phone=state.get("phone", "unknown"),
            reason=reason,
            agent_state={
                "team_id": state.get("team_id"),
                "handoff_name": state.get("handoff_name"),
                "handoff_description": state.get("handoff_description"),
            },
            context=HandoffContext(
                conversation_history=history,
                collected_data=collected_data,
                current_node=current_node,
                classification_result=classification_dict,
            ),
        )


# =============================================================================
# Handoff Reasons (Constants)
# =============================================================================


class HandoffReason:
    """Constants for handoff reasons."""

    USER_REQUESTED = "user_requested"  # User explicitly asked for human
    BOT_LIMIT = "bot_limit"  # Bot reached its capability limit
    CLASSIFIER_DETECTED = "classifier_detected"  # Classifier detected need for human
    FAIL_SAFE = "fail_safe"  # Fail safe due to classifier errors
    EMERGENCY = "emergency"  # Emergency detected, transferring to 190
