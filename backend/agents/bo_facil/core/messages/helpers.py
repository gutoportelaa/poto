from typing import Any

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
    WhatsAppMessageType,
    WhatsAppResponse,
)


def create_text_message(body: str) -> WhatsAppResponse:
    """
    Create a simple text message.

    Args:
        body: Text content (supports WhatsApp formatting: *bold*, _italic_, etc.)

    Returns:
        WhatsAppResponse with a single text message

    Example:
        response = create_text_message("Hello *world*! How can I help you?")
    """
    return WhatsAppResponse(messages=[TextMessage(body=body)])


def create_button_message(
    body: str, buttons: list[tuple[str, str]], max_buttons: int = 3
) -> WhatsAppResponse:
    """
    Create an interactive message with reply buttons.

    Args:
        body: Main message text
        buttons: List of (id, title) tuples for buttons
        max_buttons: Maximum number of buttons (WhatsApp limit is 3)

    Returns:
        WhatsAppResponse with interactive button message

    Example:
        response = create_button_message(
            "Choose an option:",
            [("option1", "Yes"), ("option2", "No"), ("option3", "Maybe")]
        )
    """
    # Limit buttons to WhatsApp maximum
    buttons = buttons[:max_buttons]

    button_objects = [ReplyButtonOption(id=btn_id, title=title) for btn_id, title in buttons]

    return WhatsAppResponse(messages=[InteractiveButtonMessage(body=body, buttons=button_objects)])


def create_list_message(
    body: str, button_text: str, sections: list[dict[str, Any]]
) -> WhatsAppResponse:
    """
    Create an interactive list message.

    Args:
        body: Main message text
        button_text: Text shown on the list button
        sections: List of sections, each containing title and rows
                 Format: [{"title": "Section Name", "rows": [{"id": "id1", "title": "Title", "description": "Desc"}]}]

    Returns:
        WhatsAppResponse with interactive list message

    Example:
        response = create_list_message(
            "Select a service:",
            "Choose Service",
            [{
                "title": "Available Services",
                "rows": [
                    {"id": "service1", "title": "Service 1", "description": "Description 1"},
                    {"id": "service2", "title": "Service 2", "description": "Description 2"}
                ]
            }]
        )
    """
    section_objects = []

    for section_data in sections:
        rows = [
            ListRowOption(id=row["id"], title=row["title"], description=row.get("description"))
            for row in section_data["rows"]
        ]

        section_objects.append(ListSection(title=section_data["title"], rows=rows))

    return WhatsAppResponse(
        messages=[
            InteractiveListMessage(body=body, button_text=button_text, sections=section_objects)
        ]
    )


def create_contact_message(contacts: list[dict[str, Any]]) -> WhatsAppResponse:
    """
    Create a message with contact cards.

    Args:
        contacts: List of contact dictionaries
                 Format: [{"name": {"formatted_name": "Name"}, "phones": [{"phone": "+123", "type": "CELL"}]}]

    Returns:
        WhatsAppResponse with contact message

    Example:
        response = create_contact_message([
            {
                "name": {
                    "formatted_name": "Emergency Services",
                    "first_name": "Emergency",
                    "last_name": "Services"
                },
                "phones": [{"phone": "+55190", "type": "MAIN"}]
            }
        ])
    """
    contact_objects = []

    for contact_data in contacts:
        # Build contact name
        name_data = contact_data["name"]
        contact_name = ContactName(**name_data)

        # Build contact phones
        phones = None
        if "phones" in contact_data:
            phones = [ContactPhone(**phone) for phone in contact_data["phones"]]

        # Build contact emails
        emails = None
        if "emails" in contact_data:
            emails = [ContactEmail(**email) for email in contact_data["emails"]]

        # Build contact URLs
        urls = None
        if "urls" in contact_data:
            urls = [ContactURL(**url) for url in contact_data["urls"]]

        contact_objects.append(Contact(name=contact_name, phones=phones, emails=emails, urls=urls))

    return WhatsAppResponse(messages=[ContactMessage(contacts=contact_objects)])


def create_location_message(
    latitude: float, longitude: float, name: str, address: str
) -> WhatsAppResponse:
    """
    Create a location message.

    Args:
        latitude: Latitude coordinate (-90 to 90)
        longitude: Longitude coordinate (-180 to 180)
        name: Location name/title
        address: Full address of the location

    Returns:
        WhatsAppResponse with location message

    Example:
        response = create_location_message(
            -23.5505, -46.6333,
            "Police Station Central",
            "123 Main Street, São Paulo, SP, Brazil"
        )
    """
    return WhatsAppResponse(
        messages=[
            LocationMessage(latitude=latitude, longitude=longitude, name=name, address=address)
        ]
    )


def create_image_message(link: str, caption: str | None = None) -> WhatsAppResponse:
    """
    Create an image message.

    Args:
        link: Public HTTPS URL of the image
        caption: Optional image caption

    Returns:
        WhatsAppResponse with image message
    """
    return WhatsAppResponse(messages=[ImageMessage(link=link, caption=caption)])


def create_audio_message(link: str) -> WhatsAppResponse:
    """
    Create an audio message.

    Args:
        link: Public HTTPS URL of the audio file

    Returns:
        WhatsAppResponse with audio message
    """
    return WhatsAppResponse(messages=[AudioMessage(link=link)])


def create_video_message(link: str, caption: str | None = None) -> WhatsAppResponse:
    """
    Create a video message.

    Args:
        link: Public HTTPS URL of the video file
        caption: Optional video caption

    Returns:
        WhatsAppResponse with video message
    """
    return WhatsAppResponse(messages=[VideoMessage(link=link, caption=caption)])


def create_document_message(
    link: str, filename: str = "document.pdf", caption: str | None = None
) -> WhatsAppResponse:
    """
    Create a document message.

    Args:
        link: Public HTTPS URL of the document
        filename: Filename displayed to the user
        caption: Optional document caption

    Returns:
        WhatsAppResponse with document message
    """
    return WhatsAppResponse(
        messages=[DocumentMessage(link=link, filename=filename, caption=caption)]
    )


def create_multi_message(components: list[dict[str, Any]]) -> WhatsAppResponse:
    """
    Create a message with multiple components of different types.

    Args:
        components: List of component dictionaries
                   Format: [{"type": "text|buttons|contact|location|image|etc", "data": {...}}]

    Returns:
        WhatsAppResponse with multiple messages

    Example:
        response = create_multi_message([
            {
                "type": "text",
                "data": {"body": "Welcome to our service!"}
            },
            {
                "type": "buttons",
                "data": {
                    "body": "What would you like to do?",
                    "buttons": [("action1", "Option 1"), ("action2", "Option 2")]
                }
            },
            {
                "type": "contact",
                "data": {
                    "contacts": [{
                        "name": {"formatted_name": "Support Team"},
                        "phones": [{"phone": "+5511999999999", "type": "WORK"}]
                    }]
                }
            }
        ])
    """
    messages: list[WhatsAppMessageType] = []

    for component in components:
        comp_type = component["type"]
        data = component["data"]

        if comp_type == "text":
            messages.append(TextMessage(body=data["body"]))

        elif comp_type == "buttons":
            buttons = [ReplyButtonOption(id=btn[0], title=btn[1]) for btn in data["buttons"]]
            messages.append(InteractiveButtonMessage(body=data["body"], buttons=buttons))

        elif comp_type == "list":
            sections = []
            for section_data in data["sections"]:
                rows = [
                    ListRowOption(
                        id=row["id"], title=row["title"], description=row.get("description")
                    )
                    for row in section_data["rows"]
                ]
                sections.append(ListSection(title=section_data["title"], rows=rows))

            messages.append(
                InteractiveListMessage(
                    body=data["body"], button_text=data["button_text"], sections=sections
                )
            )

        elif comp_type == "contact":
            contacts = []
            for contact_data in data["contacts"]:
                name = ContactName(**contact_data["name"])
                phones = (
                    [ContactPhone(**phone) for phone in contact_data.get("phones", [])]
                    if contact_data.get("phones")
                    else None
                )
                emails = (
                    [ContactEmail(**email) for email in contact_data.get("emails", [])]
                    if contact_data.get("emails")
                    else None
                )
                urls = (
                    [ContactURL(**url) for url in contact_data.get("urls", [])]
                    if contact_data.get("urls")
                    else None
                )

                contacts.append(Contact(name=name, phones=phones, emails=emails, urls=urls))

            messages.append(ContactMessage(contacts=contacts))

        elif comp_type == "location":
            messages.append(
                LocationMessage(
                    latitude=data["latitude"],
                    longitude=data["longitude"],
                    name=data["name"],
                    address=data["address"],
                )
            )

        elif comp_type == "image":
            messages.append(ImageMessage(link=data["link"], caption=data.get("caption")))

        elif comp_type == "audio":
            messages.append(AudioMessage(link=data["link"]))

        elif comp_type == "video":
            messages.append(VideoMessage(link=data["link"], caption=data.get("caption")))

        elif comp_type == "document":
            messages.append(
                DocumentMessage(
                    link=data["link"],
                    filename=data.get("filename", "document.pdf"),
                    caption=data.get("caption"),
                )
            )

        else:
            raise ValueError(f"Unsupported component type: {comp_type}")

    return WhatsAppResponse(messages=messages)


def to_whatsapp_json(response: WhatsAppResponse) -> str:
    """
    Convert WhatsAppResponse to JSON string format.

    Args:
        response: WhatsAppResponse object

    Returns:
        JSON string representation of the WhatsApp response

    Example:
        response = create_text_message("Hello!")
        json_str = to_whatsapp_json(response)
        # Use in node: return {"messages": [AIMessage(content=json_str)]}
    """
    return response.model_dump_json()


# Convenience helper for common use case: text with buttons
def create_text_with_buttons(
    text: str, button_text: str, buttons: list[tuple[str, str]]
) -> WhatsAppResponse:
    """
    Create a common pattern: text message followed by buttons.

    Args:
        text: Initial text message
        button_text: Text for the button message
        buttons: List of (id, title) tuples

    Returns:
        WhatsAppResponse with text + buttons

    Example:
        response = create_text_with_buttons(
            "Welcome to our service!",
            "How can I help you?",
            [("help", "Get Help"), ("info", "More Info")]
        )
    """
    return create_multi_message(
        [
            {"type": "text", "data": {"body": text}},
            {"type": "buttons", "data": {"body": button_text, "buttons": buttons}},
        ]
    )
