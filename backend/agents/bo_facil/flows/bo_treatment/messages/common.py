"""User-facing messages for BO treatment flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# LEGAL WARNINGS
# =============================================================================

BO_WARNING_MESSAGE = """*A comunicação falsa de crime ou de contravenção constitui crime e tem pena prevista no artigo 340 do Código Penal Brasileiro.*"""

# Initial messages shown right after user selects "Fazer BO Fácil"
INITIAL_BO_MESSAGE_1 = "Vou te ajudar a registrar o seu Boletim de Ocorrência."
INITIAL_BO_MESSAGE_2 = "Pode me contar o que aconteceu?"

# =============================================================================
# NON-BO INTENT MESSAGES (soft redirect — user decides)
# =============================================================================

# Non-BO intent: context (text bubble) + question (button bubble)
NON_BO_INTENT_CONTEXTS = {
    "acompanhamento": (
        "Para acompanhar um boletim já registrado, você precisa "
        "comparecer à delegacia mais próxima informando o número do protocolo."
    ),
    "duvida": "Esse canal é para registro de boletins de ocorrência.",
    "outro": "Esse canal é para registro de boletins de ocorrência.",
}
NON_BO_INTENT_QUESTIONS = {
    "acompanhamento": "Caso queira registrar um novo boletim, posso te ajudar.",
    "duvida": "Deseja ser transferido para tirar sua dúvida com um atendente?",
    "outro": "Deseja ser transferido para um atendente?",
}

# Non-criminal fact: context + question
NON_CRIMINAL_CONTEXT = "O que você descreveu pode não se enquadrar como um boletim de ocorrência."
NON_CRIMINAL_QUESTION = "Deseja prosseguir mesmo assim ou falar com um atendente?"

# Fact exhausted: context + question
FACT_EXHAUSTED_CONTEXT = "Não consegui entender a situação que você está descrevendo."
FACT_EXHAUSTED_QUESTION = "Deseja falar com um atendente?"


# =============================================================================
# DATA COLLECTION QUESTIONS
# =============================================================================

LOCATION_QUESTION_AT_SITE = """Preciso saber o local onde o incidente ocorreu.

Você está no local do ocorrido neste momento?"""

LOCATION_QUESTION_IF_AT_SITE = """Preciso que você compartilhe sua localização atual comigo ou pode me descrever o endereço. 📍"""

LOCATION_QUESTION_IF_NOT_AT_SITE = "Poderia me informar o endereço onde o ocorrido aconteceu?"
LOCATION_QUESTION_IF_NOT_AT_SITE_HINT = (
    "Inclua rua, número, bairro e, se possível, um ponto de referência."
)

# Fallback retry messages for location (used when LLM doesn't generate followup_question)
# Indexed by attempt - 1, i.e. 2nd attempt onward
LOCATION_RETRY_AT_SITE = [
    """Não identifiquei um endereço. Pode informar a rua e o bairro? Se souber o número, inclua também.""",
    """Preciso de um endereço para registrar: rua, número e bairro.""",
]

LOCATION_RETRY_NOT_AT_SITE = [
    """Não identifiquei um endereço. Pode informar a rua, bairro e cidade onde aconteceu?""",
    """Preciso de um endereço para registrar. Se não souber o exato, informe um ponto de referência próximo.""",
]

LOCATION_RETRY_CYBERCRIME = [
    """Não identifiquei o endereço. Pode informar sua rua, número e bairro?""",
    """Preciso do endereço completo: rua, número, bairro e cidade.""",
]

# Cybercrime (131) specific location messages - asks for user's address instead of incident location
LOCATION_CYBERCRIME_MESSAGE_1 = """Informe por gentileza o seu endereço."""

LOCATION_CYBERCRIME_MESSAGE_2 = (
    """Inclua o nome da rua, número, bairro e qualquer ponto de referência que possa ajudar."""
)


# Datetime collection messages (indexed by attempt: 0 = first, 1 = retry, 2 = last retry)
DATETIME_QUESTIONS = [
    """Por favor, informe a data e o horário em que isso aconteceu.""",
    """Preciso saber quando isso ocorreu. Pode informar o dia e o horário aproximado?""",
    """Para finalizar, informe a data e a hora do ocorrido. Exemplo: "ontem às 15h" ou "dia 10 de manhã".""",
]

DATETIME_FUTURE_REJECTED_MESSAGE = (
    "Essa data ainda não aconteceu. Pode me informar quando o fato ocorreu?"
)


# =============================================================================
# FOLLOWUP RETRY FORMATTING
# =============================================================================

# Audio hint appended to the 1st followup of each field
FOLLOWUP_AUDIO_HINT = """Se preferir, você também pode responder com um áudio."""

# Prefix shown before 2nd+ followup of each field
FOLLOWUP_PREFIX = """Para concluir o registro do seu boletim, por gentileza, forneça as informações conforme elas são solicitadas:"""


# =============================================================================
# MAX ATTEMPTS EXCEEDED (redirect to handoff)
# =============================================================================

MAX_ATTEMPTS_MESSAGE_1 = """Infelizmente, não consegui entender completamente suas mensagens."""

MAX_ATTEMPTS_MESSAGE_2 = (
    """Vou transferir você para o centro de atendimento 190 para melhor assistência."""
)


# =============================================================================
# SOFT REDIRECT (confirmation before handoff)
# =============================================================================

SOFT_REDIRECT_DECLINE_CONTEXT = "Entendo que você não tem essa informação no momento."
SOFT_REDIRECT_DECLINE_QUESTION = "Deseja continuar o registro ou falar com um atendente?"

SOFT_REDIRECT_MAX_ATTEMPTS_CONTEXT = "Não consegui coletar todas as informações necessárias."
SOFT_REDIRECT_MAX_ATTEMPTS_QUESTION = "Deseja tentar novamente ou falar com um atendente?"

RESTART_COLLECTION_MESSAGE = (
    "Tudo bem, vamos tentar de novo. Vou perguntar apenas o que ficou faltando."
)


# =============================================================================
# BO DESCRIPTION CONFIRMATION
# =============================================================================

BO_DESCRIPTION_CONFIRMATION = (
    """Confira o seu relato e informe se deseja prosseguir ou deseja informar novamente o relato:"""
)


# =============================================================================
# NON-PI STATE CONFIRMATION
# =============================================================================

NON_PI_STATE_QUESTION_TEMPLATE = (
    "Este é um canal oficial de denúncias do estado do Piauí. "
    "Para ocorrências em {detected_state}, é importante buscar os canais "
    "de registro local. Deseja continuar mesmo assim?"
)
