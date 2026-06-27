"""Bot message to semantic tag mapping for conversation history compression.

This module compresses conversation history to save tokens by replacing
verbose bot messages with short semantic tags.

The mapping uses unique substrings from real messages defined in messages/*.py.
When build_conversation_history encounters a bot message, it checks if any
substring from the dictionary is present and substitutes it with the corresponding tag.
"""

import re

# =============================================================================
# TAGS FOR KNOWN MESSAGES (CONSTANTS)
# Key: unique substring from real message | Value: semantic tag
# =============================================================================

BOT_MESSAGE_TAGS: dict[str, str] = {
    # --- Initial flow (flows/initial/messages.py) ---
    "Eu sou a IA da SSP do PIAUÍ": "[boas-vindas]",
    "📍 Você pode:": "[menu de serviços]",
    "Como posso ajudar você hoje?": "[perguntou serviço]",
    "Selecione uma das opções abaixo:": "[mostrou opções]",
    # --- Verify identity (flows/verify_identity/messages.py) ---
    "informe o seu CPF para que eu possa concluir": "[pediu CPF]",
    "informações compartilhadas são tratadas com sigilo": "[garantiu sigilo]",
    "Não foi possível identificar os 11 dígitos do seu CPF": "[CPF inválido]",
    "Verifique o CPF informado e tente novamente": "[pediu verificar CPF]",
    "Você excedeu o número de tentativas": "[limite tentativas CPF]",
    "foi o último documento usado para atendimento": "[ofereceu dados anteriores]",
    "Por segurança, selecione seu ano de nascimento": "[pediu ano nascimento]",
    "Em que ano você nasceu?": "[pediu ano nascimento]",
    "Em que cidade você nasceu?": "[pediu cidade natal]",
    "dados informados não conferem": "[dados não conferem]",
    "Não foi possível concluir a verificação de identidade": "[verificação falhou]",
    "Deseja tentar novamente ou prefere prosseguir com o registro": "[opções verificação]",
    "Informe seu nome completo por gentileza": "[pediu nome]",
    # --- BO Treatment - Common (flows/bo_treatment/messages/common.py) ---
    "comunicação falsa de crime ou de contravenção constitui crime": "[aviso legal]",
    "Vou te ajudar a registrar o seu Boletim de Ocorrência": "[iniciou BO, pediu detalhes]",
    "Você está no local do ocorrido neste momento?": "[perguntou se está no local]",
    "compartilhe sua localização atual comigo": "[pediu localização GPS]",
    "Como você não está no local, poderia me informar o endereço": "[pediu endereço]",
    "Não consegui localizar o endereço. Você pode me informar novamente": "[endereço não encontrado]",
    "Informe por gentileza o seu endereço": "[pediu endereço (cybercrime)]",
    "Confira o seu relato e informe se deseja prosseguir": "[confirmação do relato]",
    # --- BO Treatment - Inline questions (followup node) ---
    "informe a data e o horário em que isso aconteceu": "[pediu data/hora]",
    "descrever com mais detalhes o que aconteceu": "[pediu mais detalhes do fato]",
    # --- BO Treatment - Objects (flows/bo_treatment/messages/object.py) ---
    "adicionar informações sobre os objetos envolvidos": "[perguntou sobre objetos]",
    "informações de identificação dos objetos ajudam no trabalho de recuperação": "[importância objetos]",
    "descreva as informações do(s) objeto(s) que serão adicionados": "[pediu descrição objetos]",
    "estava portando ou usando algum objeto no momento": "[perguntou objeto do suspeito]",
    "Descreva o objeto usado pelo suspeito": "[pediu descrição objeto suspeito]",
    "Não possuo informações de todos os objetos ainda": "[faltam objetos]",
    "algum objeto foi levado durante a ocorrência": "[perguntou objetos levados]",
    "informe o Imei do aparelho": "[pediu IMEI]",
    "informe a placa do veículo": "[pediu placa]",
    "Havia algo dentro ou junto com este objeto": "[perguntou objetos dentro]",
    # --- BO Treatment - Persons (flows/bo_treatment/messages/person.py) ---
    "adicionar informações sobre possíveis suspeitos": "[perguntou sobre suspeitos]",
    "citou um suposto autor na ocorrência, poderia descrevê-lo": "[detectou suspeito]",
    "detalhes sobre os possíveis suspeitos, como aparência": "[pediu descrição suspeitos]",
    # --- BO Treatment - Victims (flows/bo_treatment/messages/victim.py) ---
    "Informe o CPF da vítima": "[pediu CPF vítima]",
    "Informe o nome completo da vítima": "[pediu nome vítima]",
    "Descreva brevemente a relação da vítima com a ocorrência": "[pediu descrição vítima]",
    # --- BO Treatment - Damage (flows/bo_treatment/messages/damage.py) ---
    "Identificamos que houve prejuízo financeiro nessa ocorrência": "[detectou prejuízo]",
    "Nessa situação, ocorreu prejuízo financeiro?": "[perguntou prejuízo]",
    "Qual o valor desse prejuízo?": "[pediu valor prejuízo]",
    "Esse prejuízo foi no valor de R$": "[confirmando valor]",
    "Não consegui identificar o valor. Por favor, informe novamente": "[valor inválido]",
    "Qual foi a forma de pagamento utilizada": "[pediu forma pagamento]",
    "gostaria de anexar o comprovante de pagamento": "[perguntou comprovante]",
    "Pode enviar a foto do comprovante": "[pediu foto comprovante]",
    # --- Post BO (flows/post_bo/messages.py) ---
    "Enviando dados...": "[enviando dados]",
    "Só mais um instante": "[aguardando]",
    "protocolo de atendimento foi registrado com sucesso": "[BO registrado]",
    "Aqui estão os detalhes para sua referência": "[detalhes protocolo]",
    "Lhe ajudo em algo mais?": "[perguntou se ajuda mais]",
    "estamos à disposição para ajudar": "[despedida]",
    "houve um erro ao processar seus dados": "[erro processamento]",
    "transferir você para o centro de atendimento 190": "[transferindo 190]",
    # --- Emergency (flows/emergency/messages.py) ---
    "você está em uma situação de emergência": "[detectou emergência]",
    "time especializado do 190 será acionado": "[acionando 190]",
    "Fique em um local seguro": "[orientação segurança]",
}


# =============================================================================
# NODE NAME TAGS (fallback for AI-generated messages)
# =============================================================================

NODE_INTENT_TAGS: dict[str, str] = {
    "incident_initial_node": "[iniciou coleta incidente]",
    "extract_incident_info_node": "[extraindo info]",
    "incident_followup_node": "[coletando incidente]",
    "object_unified_node": "[coletando objetos]",
    "person_collection_node": "[coletando suspeitos]",
    "victim_collection_node": "[coletando vítima]",
    "damage_collection_node": "[coletando prejuízos]",
    "classify_incident_node": "[classificando]",
    "generate_description_node": "[gerando descrição]",
    "confirmation_node": "[confirmação]",
}


# =============================================================================
# REGEX PATTERNS FOR DYNAMICALLY GENERATED MESSAGES
# =============================================================================

GENERATED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^Consta dos presentes autos", re.IGNORECASE), "[resumo formal BO]"),
    (re.compile(r"Entendi.*você mencionou", re.IGNORECASE), "[confirmou entendimento]"),
    (re.compile(r"Preciso de mais (detalhes|informações)", re.IGNORECASE), "[pediu mais detalhes]"),
]


# =============================================================================
# TOPIC DETECTION (for LLM-generated follow-ups)
# Ordered by specificity — first match wins.
# =============================================================================

_TOPIC_KEYWORDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"imei", re.I), "[follow-up IMEI]"),
    (re.compile(r"placa", re.I), "[follow-up placa]"),
    (re.compile(r"hor[aá]rio|que horas|hora .* acontec|turno|manh[aã]|tarde|noite", re.I), "[follow-up horário]"),
    (re.compile(r"data|quando|dia .* acontec|dia .* ocorr", re.I), "[follow-up data]"),
    (re.compile(r"endere[cç]o|local|onde|rua|bairro|cidade|cep", re.I), "[follow-up local]"),
    (re.compile(r"celular|aparelho|telefone|smartphone", re.I), "[follow-up celular]"),
    (re.compile(r"ve[ií]culo|carro|moto|autom[oó]vel", re.I), "[follow-up veículo]"),
    (re.compile(r"marca|modelo|cor\b", re.I), "[follow-up detalhes objeto]"),
    (re.compile(r"objeto|pertence|levaram|roubaram|furtaram", re.I), "[follow-up objetos]"),
    (re.compile(r"suspect|autor|agressor|descrev.*pessoa|aparência", re.I), "[follow-up suspeito]"),
    (re.compile(r"v[ií]tima|CPF da v[ií]tima|nome da v[ií]tima", re.I), "[follow-up vítima]"),
    (re.compile(r"preju[ií]zo|valor|dano|pagamento", re.I), "[follow-up prejuízo]"),
    (re.compile(r"o que acontec|relat|descrev|fato|ocorr[eê]ncia", re.I), "[follow-up fato]"),
]


# =============================================================================
# MAIN FUNCTION
# =============================================================================


def _detect_topic(content: str) -> str | None:
    for pattern, tag in _TOPIC_KEYWORDS:
        if pattern.search(content):
            return tag
    return None


def summarize_bot_message(
    content: str,
    node_name: str | None = None,
) -> str:
    """Return a semantic tag for a bot message, or the original text if LLM-generated.

    Known constant messages (from messages/*.py) are compressed to tags.
    LLM-generated follow-up questions are kept in full to preserve the
    exact question context for downstream prompts (e.g., description generation).

    Priority:
    1. Match in BOT_MESSAGE_TAGS (known message substrings) → tag
    2. Match in GENERATED_PATTERNS (regex for generated messages) → tag
    3. No match → keep original text (LLM-generated follow-up)
    """
    for substring, tag in BOT_MESSAGE_TAGS.items():
        if substring in content:
            return tag

    for pattern, tag in GENERATED_PATTERNS:
        if pattern.search(content):
            return tag

    # LLM-generated messages: keep full text to preserve question context
    return content
