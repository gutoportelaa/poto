"""Base classes for the policy-based classification system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..models import ClassificationClass


class PolicyAction(Enum):
    """Actions that a policy can return."""

    CONTINUE = "continue"  # Pass to next policy in chain
    RESOLVE = "resolve"  # Classification resolved, skip remaining policies
    REJECT = "reject"  # Reject and trigger fallback


@dataclass
class PolicyContext:
    """Shared context between policies in the chain."""

    user_input: str
    user_id: str | None = None
    conversation_id: str | None = None
    state: dict | None = None
    metadata: dict = field(default_factory=dict)

    # Filled during execution
    api_result: Any | None = None
    llm_result: Any | None = None


@dataclass
class PolicyResult:
    """Result returned by a policy."""

    action: PolicyAction
    classification: Optional["ClassificationClass"] = None
    confidence: float = 0.0
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class PolicyBase(ABC):
    """Base class for all policies in the chain."""

    name: str = "base"
    priority: int = 0  # Lower = executes first

    @abstractmethod
    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Execute the policy and return a result.

        Args:
            context: Shared context with user input and metadata

        Returns:
            PolicyResult indicating the action to take
        """
        pass

    def should_skip(self, context: PolicyContext) -> bool:
        """Check if this policy should be skipped.

        Override in subclasses to implement conditional execution.

        Args:
            context: Shared context with user input and metadata

        Returns:
            True if policy should be skipped
        """
        return False
