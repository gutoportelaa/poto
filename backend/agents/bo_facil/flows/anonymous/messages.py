"""User-facing messages for anonymous flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# ANONYMOUS REPORT MESSAGES
# =============================================================================

PRIVACY_MESSAGE_1A = "🔒 Canal de Denúncia Anônima do Estado do Piauí."
PRIVACY_MESSAGE_1B = "Este canal é exclusivo para denúncias. Para registrar um BO, volte ao menu e selecione \"BO Fácil\"."

PRIVACY_MESSAGE_2 = """Nesta opção está garantido o sigilo do denunciante e as informações seguirão sem qualquer vinculação de seus dados."""

SCHOOL_RELATED_QUESTION = (
    """Sua denúncia está relacionada a alguma situação ocorrida em ambiente escolar?"""
)

CITY_REQUEST = """Informe a cidade em que aconteceu essa ocorrência:"""

REPORT_REQUEST = """📝 Envie sua denúncia com o máximo de detalhes em uma única mensagem:
O que aconteceu?
Quem fez? (se souber)
Como foi?
Quando e Onde ocorreu?"""

MEDIA_QUESTION = """Você deseja anexar foto ou vídeo ao seu relato?"""

MEDIA_SEND_INSTRUCTION = """Pode enviar a foto ou vídeo."""

SUCCESS_MESSAGE = """Agradecemos o seu contato, seu relato foi encaminhado com sucesso."""
