"""GovChat SDK models based on Chatwoot API specification."""

from enum import Enum

from pydantic import BaseModel, Field


class Priority(str, Enum):
    """Conversation priority levels."""

    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class AttributeDisplayType(int, Enum):
    """Custom attribute data types (integer values as per Chatwoot API)."""

    TEXT = 0
    NUMBER = 1
    CURRENCY = 2
    PERCENT = 3
    LINK = 4
    DATE = 5
    LIST = 6
    CHECKBOX = 7


class AttributeModel(int, Enum):
    """Model type for custom attributes (integer values as per Chatwoot API)."""

    CONVERSATION = 0
    CONTACT = 1


class ConversationStatus(str, Enum):
    """Conversation status values."""

    OPEN = "open"
    RESOLVED = "resolved"
    PENDING = "pending"
    SNOOZED = "snoozed"


# =============================================================================
# Request Models
# =============================================================================


class UpdateConversationCustomAttributesRequest(BaseModel):
    """
    Request body for updating conversation custom attributes.

    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/custom_attributes
    """

    custom_attributes: dict


class UpdateContactRequest(BaseModel):
    """
    Request body for updating contact (including custom attributes).

    PUT /api/v1/accounts/{account_id}/contacts/{id}
    """

    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    blocked: bool | None = None
    identifier: str | None = None
    avatar_url: str | None = None
    custom_attributes: dict | None = None
    additional_attributes: dict | None = None


class CreateAttributeDefinitionRequest(BaseModel):
    """
    Request body for creating a custom attribute definition.

    POST /api/v1/accounts/{account_id}/custom_attribute_definitions
    """

    attribute_display_name: str
    attribute_display_type: (
        int  # 0=text, 1=number, 2=currency, 3=percent, 4=link, 5=date, 6=list, 7=checkbox
    )
    attribute_key: str
    attribute_model: int  # 0=conversation, 1=contact
    attribute_description: str | None = None
    attribute_values: list[str] | None = None  # For list type
    regex_pattern: str | None = None
    regex_cue: str | None = None


class TogglePriorityRequest(BaseModel):
    """
    Request body for toggling conversation priority.

    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_priority
    """

    priority: Priority


class ToggleStatusRequest(BaseModel):
    """
    Request body for toggling conversation status.

    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status
    """

    status: ConversationStatus
    snoozed_until: int | None = None  # Unix timestamp for snoozed status


class CreateConversationRequest(BaseModel):
    """
    Request body for creating a new conversation.

    POST /api/v1/accounts/{account_id}/conversations
    """

    inbox_id: int
    contact_id: int
    status: ConversationStatus = ConversationStatus.OPEN
    source_id: str | None = None


class AssignConversationRequest(BaseModel):
    """
    Request body for assigning conversation to team/agent.

    POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments
    """

    team_id: int | None = None
    assignee_id: int | None = None


# =============================================================================
# Response Models
# =============================================================================


class ToggleStatusResponse(BaseModel):
    """Response from toggle_status endpoint."""

    class Payload(BaseModel):
        success: bool
        current_status: str
        conversation_id: int

    meta: dict = Field(default_factory=dict)
    payload: Payload | None = None


class CustomAttributesResponse(BaseModel):
    """Response from update custom_attributes endpoint."""

    custom_attributes: dict = Field(default_factory=dict)


class AttributeDefinitionResponse(BaseModel):
    """Response from custom attribute definition operations."""

    id: int
    attribute_key: str
    attribute_display_name: str
    attribute_display_type: str
    attribute_description: str | None = None
    attribute_values: str | None = None
    attribute_model: str
    default_value: str | None = None
    regex_pattern: str | None = None
    regex_cue: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ContactResponse(BaseModel):
    """Response from contact operations."""

    id: int
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    blocked: bool | None = None
    custom_attributes: dict = Field(default_factory=dict)
    additional_attributes: dict = Field(default_factory=dict)
    created_at: str | None = None
    last_activity_at: str | None = None
