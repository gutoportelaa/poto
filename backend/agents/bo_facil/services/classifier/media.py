"""Media URL detection for WhatsApp bridge messages.

The bridge converts photos, videos and documents to URLs
(govchat.tech/rails/active_storage/...) and sends them as plain text.
This module detects those URLs so the flow can handle them gracefully.
"""

import re

from agents.bo_facil.core.messages import create_text_message, to_whatsapp_json

MEDIA_URL_PATTERN = re.compile(
    r"https?://\S*govchat\S*/rails/active_storage/\S+",
    re.IGNORECASE,
)

# All interrupt messages must be WhatsApp JSON format (bridge ignores plain text)
MEDIA_FIRST_MESSAGE = to_whatsapp_json(
    create_text_message("Recebido! Se tiver mais arquivos, envie agora. Quando terminar, digite *pronto*.")
)

MEDIA_SUBSEQUENT_MESSAGE = ""

EVIDENCE_ASK_MESSAGE = (
    "Deseja enviar alguma foto, vídeo ou documento como prova?"
)


def is_media_url(text: str) -> bool:
    """Check if the entire message is a media URL from the bridge."""
    return bool(MEDIA_URL_PATTERN.fullmatch(text.strip()))
