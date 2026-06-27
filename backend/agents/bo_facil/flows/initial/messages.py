"""User-facing messages for initial flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# WELCOME AND MENU MESSAGES
# =============================================================================

WELCOME_MESSAGE = "👋 Bem-vindo(a)!\nEu sou a IA da SSP do PIAUÍ e estou aqui para ajudar."

SERVICES_AVAILABLE_MESSAGE = """📍 Você pode:

✅ Fazer boletins de ocorrência
✅ Solicitar atendimento urgente"""

SERVICE_MENU_PROMPT = "Como posso ajudar você hoje?"

MENU_OPTIONS_PROMPT = "Selecione uma das opções abaixo:"

# Button labels
BUTTON_BO_FACIL = "Fazer BO Fácil"
BUTTON_ATENDIMENTO_190 = "Atendimento Urgente"
BUTTON_DENUNCIA_ANONIMA = "Denúncia Anônima"
