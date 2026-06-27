"""
WhatsApp message creation system for bo_facil agent.

This module provides a complete system for creating WhatsApp Business API messages
with flexible helpers and validated models.
"""

# Import main models
# Import all helper functions
from .helpers import (
    create_audio_message,
    create_button_message,
    create_contact_message,
    create_document_message,
    create_image_message,
    create_list_message,
    create_location_message,
    create_multi_message,
    create_text_message,
    create_text_with_buttons,
    create_video_message,
    to_whatsapp_json,
)
from .models import (
    AudioMessage,
    Contact,
    ContactEmail,
    ContactMessage,
    ContactName,
    ContactPhone,
    ContactURL,
    DocumentMessage,
    ImageMessage,
    InteractiveButtonMessage,
    InteractiveListMessage,
    ListRowOption,
    ListSection,
    LocationMessage,
    ReplyButtonOption,
    TextMessage,
    VideoMessage,
    WhatsAppResponse,
)

# Define what gets imported with "from messages import *"
__all__ = [
    # Core models
    "WhatsAppResponse",
    "TextMessage",
    "InteractiveButtonMessage",
    "InteractiveListMessage",
    "ContactMessage",
    "LocationMessage",
    "ImageMessage",
    "AudioMessage",
    "VideoMessage",
    "DocumentMessage",
    "ReplyButtonOption",
    "ListSection",
    "ListRowOption",
    "Contact",
    "ContactName",
    "ContactPhone",
    "ContactEmail",
    "ContactURL",
    # Helper functions
    "create_text_message",
    "create_button_message",
    "create_list_message",
    "create_contact_message",
    "create_location_message",
    "create_image_message",
    "create_audio_message",
    "create_video_message",
    "create_document_message",
    "create_multi_message",
    "create_text_with_buttons",
    "to_whatsapp_json",
]
