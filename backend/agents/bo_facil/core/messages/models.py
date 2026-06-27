"""
WhatsApp Business API models for message composition and sending.

This module defines Pydantic models that represent the various types of messages
and interactive components supported by the WhatsApp Business API.
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

# ===== CONSTANTS =====

# WhatsApp API Limits
MAX_INTERACTIVE_BUTTONS = 3
MAX_LIST_SECTIONS = 10
MAX_LIST_ROWS_PER_SECTION = 10
MAX_CONTACTS_PER_MESSAGE = 5
MAX_MESSAGES_PER_RESPONSE = 10

# Text Limits
MAX_TEXT_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
MAX_BUTTON_TITLE_LENGTH = 20
MAX_LIST_BUTTON_TEXT_LENGTH = 20
MAX_LIST_TITLE_LENGTH = 24
MAX_LIST_DESCRIPTION_LENGTH = 72

# Contact Types
PHONE_TYPES = Literal["CELL", "MAIN", "WORK", "HOME"]
EMAIL_TYPES = Literal["WORK", "HOME"]
URL_TYPES = Literal["WORK", "HOME"]

# Media Types
SUPPORTED_IMAGE_FORMATS = ["image/jpeg", "image/png", "image/webp"]
SUPPORTED_AUDIO_FORMATS = ["audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"]
SUPPORTED_VIDEO_FORMATS = ["video/mp4", "video/3gpp"]
SUPPORTED_DOCUMENT_FORMATS = [
    "application/pdf",
    "application/vnd.ms-powerpoint",
    "application/msword",
]


# ===== UTILITY VALIDATORS =====


def validate_phone_number(phone: str) -> str:
    """Validate phone number format with Brazilian emergency number support."""
    # Remove common separators
    clean_phone = re.sub(r"[\s\-\(\)]", "", phone)

    # Remove + for validation
    digits_only = clean_phone.lstrip("+")

    # Brazilian emergency numbers: 190, 192, 193, 194, 197, 198, 199
    if re.match(r"^19[0-9]$", digits_only):
        return clean_phone if clean_phone.startswith("+") else f"+{clean_phone}"

    # Brazilian emergency numbers with country code: +55190, +55192, etc.
    if re.match(r"^5519[0-9]$", digits_only):
        return clean_phone if clean_phone.startswith("+") else f"+{clean_phone}"

    # International format with minimum length for regular numbers
    if not re.match(r"^[1-9]\d{6,14}$", digits_only):
        raise ValueError(
            "Phone number must be in international format (+country_code + number) or valid emergency number (19X)"
        )

    return clean_phone if clean_phone.startswith("+") else f"+{clean_phone}"


def validate_email_address(email: str) -> str:
    """Validate email address format using basic regex."""
    # Basic email validation regex
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

    if not re.match(email_pattern, email):
        raise ValueError("Invalid email address format")

    return email.lower()


def validate_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    """Validate geographic coordinates."""
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90 degrees")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180 degrees")
    return latitude, longitude


# ===== INTERACTIVE COMPONENTS =====


class ReplyButtonOption(BaseModel):
    """Represents a reply button option in interactive messages."""

    id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description="Unique identifier for the button callback payload",
        ),
    ]
    title: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_BUTTON_TITLE_LENGTH,
            description="Button text displayed to the user",
        ),
    ]


class ListRowOption(BaseModel):
    """Represents a single row option within a list section."""

    id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="Unique identifier for the row callback payload",
        ),
    ]
    title: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_LIST_TITLE_LENGTH,
            description="Main title text for the row option",
        ),
    ]
    description: (
        Annotated[
            str,
            Field(
                max_length=MAX_LIST_DESCRIPTION_LENGTH,
                description="Optional description text for the row option",
            ),
        ]
        | None
    ) = None


class ListSection(BaseModel):
    """Represents a section within an interactive list message."""

    title: Annotated[
        str, Field(min_length=1, max_length=MAX_LIST_TITLE_LENGTH, description="Section title text")
    ]
    rows: Annotated[
        list[ListRowOption],
        Field(
            min_length=1,
            max_length=MAX_LIST_ROWS_PER_SECTION,
            description="List of row options within this section",
        ),
    ]


# ===== CONTACT MODELS =====


class ContactName(BaseModel):
    """Contact name information."""

    formatted_name: Annotated[
        str, Field(min_length=1, max_length=100, description="Full formatted name of the contact")
    ]
    first_name: Annotated[str, Field(max_length=50, description="First name")] | None = None
    last_name: Annotated[str, Field(max_length=50, description="Last name")] | None = None


class ContactPhone(BaseModel):
    """Contact phone number information."""

    phone: str = Field(..., description="Phone number in international format")
    type: PHONE_TYPES = Field(default="CELL", description="Type of phone number")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_phone_number(v)


class ContactEmail(BaseModel):
    """Contact email information."""

    email: str = Field(..., description="Valid email address")
    type: EMAIL_TYPES = Field(default="WORK", description="Type of email address")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return validate_email_address(v)


class ContactURL(BaseModel):
    """Contact URL information."""

    url: HttpUrl = Field(..., description="Valid website URL")
    type: URL_TYPES = Field(default="WORK", description="Type of website")


class Contact(BaseModel):
    """Represents a single contact card."""

    name: ContactName = Field(..., description="Contact name information")
    phones: (
        Annotated[
            list[ContactPhone], Field(max_length=5, description="List of phone numbers (max 5)")
        ]
        | None
    ) = None
    emails: (
        Annotated[
            list[ContactEmail], Field(max_length=3, description="List of email addresses (max 3)")
        ]
        | None
    ) = None
    urls: (
        Annotated[list[ContactURL], Field(max_length=3, description="List of website URLs (max 3)")]
        | None
    ) = None


# ===== MESSAGE TYPES =====


class TextMessage(BaseModel):
    """Plain text message with optional WhatsApp formatting."""

    type: Literal["text"] = "text"
    body: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_TEXT_LENGTH,
            description="Text content supporting WhatsApp formatting (*bold*, _italic_, ~strikethrough~, ```monospace```)",
        ),
    ]


class ImageMessage(BaseModel):
    """Image message with optional caption."""

    type: Literal["image"] = "image"
    link: HttpUrl = Field(..., description="Public HTTPS URL of the image (JPEG, PNG, WebP)")
    caption: (
        Annotated[str, Field(max_length=MAX_CAPTION_LENGTH, description="Optional image caption")]
        | None
    ) = None


class AudioMessage(BaseModel):
    """Audio file message (AAC, MP4, MPEG, AMR, OGG formats)."""

    type: Literal["audio"] = "audio"
    link: HttpUrl = Field(..., description="Public HTTPS URL of the audio file")


class VideoMessage(BaseModel):
    """Video file message (MP4, 3GPP formats)."""

    type: Literal["video"] = "video"
    link: HttpUrl = Field(..., description="Public HTTPS URL of the video file")
    caption: (
        Annotated[str, Field(max_length=MAX_CAPTION_LENGTH, description="Optional video caption")]
        | None
    ) = None


class DocumentMessage(BaseModel):
    """Document file message (PDF, DOC, PPT formats)."""

    type: Literal["document"] = "document"
    link: HttpUrl = Field(..., description="Public HTTPS URL of the document")
    filename: Annotated[
        str, Field(min_length=1, max_length=100, description="Filename displayed to the user")
    ] = "document.pdf"
    caption: (
        Annotated[
            str, Field(max_length=MAX_CAPTION_LENGTH, description="Optional document caption")
        ]
        | None
    ) = None


class LocationMessage(BaseModel):
    """Geographic location message."""

    type: Literal["location"] = "location"
    latitude: float = Field(..., description="Latitude coordinate (-90 to 90)")
    longitude: float = Field(..., description="Longitude coordinate (-180 to 180)")
    name: Annotated[str, Field(min_length=1, max_length=100, description="Location name or title")]
    address: Annotated[
        str, Field(min_length=1, max_length=200, description="Full address of the location")
    ]

    @field_validator("latitude", "longitude")
    @classmethod
    def validate_coordinates_range(cls, v: float, info) -> float:
        field_name = info.field_name
        if field_name == "latitude" and not (-90 <= v <= 90):
            raise ValueError("Latitude must be between -90 and 90 degrees")
        elif field_name == "longitude" and not (-180 <= v <= 180):
            raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class InteractiveButtonMessage(BaseModel):
    """Interactive message with reply buttons (max 3 buttons)."""

    type: Literal["interactive_buttons"] = "interactive_buttons"
    body: Annotated[
        str, Field(min_length=1, max_length=MAX_TEXT_LENGTH, description="Main message text")
    ]
    buttons: Annotated[
        list[ReplyButtonOption],
        Field(
            min_length=1,
            max_length=MAX_INTERACTIVE_BUTTONS,
            description="List of reply button options (1-3 buttons)",
        ),
    ]


class InteractiveListMessage(BaseModel):
    """Interactive message with a selectable list."""

    type: Literal["interactive_list"] = "interactive_list"
    body: Annotated[
        str, Field(min_length=1, max_length=MAX_TEXT_LENGTH, description="Main message text")
    ]
    button_text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_LIST_BUTTON_TEXT_LENGTH,
            description="Text displayed on the list button",
        ),
    ]
    sections: Annotated[
        list[ListSection],
        Field(
            min_length=1,
            max_length=MAX_LIST_SECTIONS,
            description="List sections containing selectable options",
        ),
    ]


class ContactMessage(BaseModel):
    """Message containing one or more contact cards."""

    type: Literal["contacts"] = "contacts"
    contacts: Annotated[
        list[Contact],
        Field(
            min_length=1,
            max_length=MAX_CONTACTS_PER_MESSAGE,
            description="List of contact cards to send (1-5 contacts)",
        ),
    ]


# ===== MAIN RESPONSE MODEL =====

# Union type for all supported message types
WhatsAppMessageType = (
    TextMessage
    | ImageMessage
    | AudioMessage
    | VideoMessage
    | DocumentMessage
    | LocationMessage
    | InteractiveButtonMessage
    | InteractiveListMessage
    | ContactMessage
)


class WhatsAppResponse(BaseModel):
    """
    Complete WhatsApp response containing one or more messages to be sent.

    This is the main model used by agents to compose WhatsApp responses
    that can include multiple message types in sequence.
    """

    messages: Annotated[
        list[WhatsAppMessageType],
        Field(
            min_length=1,
            max_length=MAX_MESSAGES_PER_RESPONSE,
            description="Ordered list of message components to be sent to the user",
        ),
    ]
