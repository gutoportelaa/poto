"""GovChat SDK for managing contacts and conversations via Chatwoot API."""

from .client import GovChatClient, get_govchat_client, govchat_client
from .exceptions import (
    GovChatApiError,
    GovChatConfigError,
    GovChatConnectionError,
    GovChatError,
    GovChatTimeoutError,
)
from .models import (
    AttributeDisplayType,
    AttributeModel,
    ConversationStatus,
    Priority,
)
from .operations import (
    govchat_assign_team,
    govchat_resolve,
    govchat_set_attribute,
    govchat_set_priority,
)

__all__ = [
    # Client
    "GovChatClient",
    "get_govchat_client",
    "govchat_client",
    # Operations
    "govchat_assign_team",
    "govchat_resolve",
    "govchat_set_attribute",
    "govchat_set_priority",
    # Exceptions
    "GovChatError",
    "GovChatApiError",
    "GovChatConfigError",
    "GovChatConnectionError",
    "GovChatTimeoutError",
    # Enums
    "Priority",
    "AttributeDisplayType",
    "AttributeModel",
    "ConversationStatus",
]
