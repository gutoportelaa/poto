"""User-facing messages for person collection flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# PERSON COLLECTION MESSAGES
# =============================================================================

# Initial question with buttons (when no persons detected proactively)
PERSON_QUESTION = (
    """Você gostaria de adicionar informações sobre possíveis suspeitos desta ocorrência?"""
)

# Collection messages for free-text description (split into instruction + audio hint)
PERSON_DESCRIPTION_REQUEST = "Em um texto único, descreva todos os suspeitos com o máximo de detalhes: aparência, roupas, comportamento e qualquer característica que lembrar."
PERSON_DESCRIPTION_AUDIO_HINT = "Se preferir, pode mandar um áudio. 🎙"
