"""User-facing messages for object collection flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# OBJECT COLLECTION MESSAGES
# =============================================================================

# Initial question with buttons (for robbery/theft incidents)
OBJECT_QUESTION = """Gostaria de adicionar informações sobre os objetos envolvidos no registro de sua ocorrência?"""

# Description request (split into instruction + audio hint)
OBJECT_DESCRIPTION_REQUEST = "Em um texto único, descreva todos os objetos envolvidos com o máximo de detalhes: cor, marca, modelo e outras características que lembrar."
OBJECT_DESCRIPTION_AUDIO_HINT = "Se preferir, pode mandar um áudio. 🎙"

# Question for object used in aggression (procedure 86)
OBJECT_USED_QUESTION = """Você se lembra se a pessoa que cometeu o fato estava portando ou usando algum objeto no momento?"""

# Description request for object used
OBJECT_USED_DESCRIPTION_REQUEST = """Descreva o objeto usado pelo suspeito com o máximo de detalhes possíveis, como tipo, cor ou qualquer outra característica que lembrar."""

# Question about objects stolen (alternative phrasing)
OBJECT_STOLEN_QUESTION = """Poderia informar se algum objeto foi levado durante a ocorrência?"""
