"""User-facing messages for victim data collection flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# VICTIM NAME COLLECTION MESSAGES
# =============================================================================

VICTIM_NAME_REQUEST_MESSAGE = """Qual o nome completo da vítima?"""

VICTIM_NAME_UNKNOWN_OPTION = "Não sei informar"


# =============================================================================
# VICTIM CPF COLLECTION MESSAGES
# =============================================================================

VICTIM_CPF_REQUEST_MESSAGE = """Informe o CPF da vítima."""

VICTIM_CPF_INVALID_MESSAGE = "Não consegui identificar um CPF válido. Pode tentar novamente?"

VICTIM_CPF_UNKNOWN_OPTION = "Não sei informar"
