"""User-facing messages for verify_identity flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# CPF VERIFICATION MESSAGES
# =============================================================================

# Initial CPF request (2 messages sent together)
CPF_REQUEST_MESSAGE_1 = """Por favor, informe o seu CPF para que eu possa concluir o registro."""
CPF_REQUEST_MESSAGE_2 = (
    """Ressalto que todas as informações compartilhadas são tratadas com sigilo e segurança."""
)

# Invalid CPF messages
CPF_INVALID_11_DIGITS_MESSAGE = """O CPF informado não é válido. Verifique os números e tente novamente."""

CPF_INVALID_RETRY_MESSAGE = """Verifique o CPF informado e tente novamente."""

CPF_MAX_ATTEMPTS_MESSAGE = """Você excedeu o número de tentativas."""


# =============================================================================
# DATA CONFIRMATION MESSAGES
# =============================================================================


def get_data_confirmation_message(masked_cpf: str, birth_city: str | None = None) -> str:
    """Generate data confirmation message with masked CPF and optional birth city."""
    message = f"""Identifiquei aqui que este *{masked_cpf}* foi o último documento usado para atendimento."""

    if birth_city:
        message += f"\nCidade natal: *{birth_city}*"

    message += "\n\n*Gostaria de continuar utilizando os mesmos dados?*"
    return message


# Button labels
BUTTON_CONFIRM_DATA = "Sim"
BUTTON_UPDATE_DATA = "Não"

# Security validation message (shown after user confirms to use previous data)
SECURITY_VALIDATION_PROMPT = """Por segurança, selecione seu ano de nascimento:"""


# =============================================================================
# BIRTH YEAR VERIFICATION MESSAGES
# =============================================================================

BIRTH_YEAR_PROMPT = """Por segurança, vamos confirmar os seus dados. Em que ano você nasceu?"""


# =============================================================================
# BIRTH CITY COLLECTION MESSAGES
# =============================================================================

BIRTH_CITY_PROMPT = """Em que cidade você nasceu?"""

BIRTH_CITY_INVALID_MESSAGE = """Não consegui identificar o nome da cidade. Por favor, informe apenas o nome da sua cidade natal."""


# =============================================================================
# VERIFICATION FAILURE MESSAGES
# =============================================================================

VERIFICATION_FAILED_MESSAGE = """Hmm... parece que os dados informados não conferem."""

VERIFICATION_NOT_COMPLETED_MESSAGE = """Não foi possível concluir a verificação de identidade."""

VERIFICATION_DECISION_MESSAGE = """Deseja tentar novamente ou prefere prosseguir com o registro da ocorrência sem informar o CPF?"""

# Button labels
BUTTON_RETRY_VERIFICATION = "🌀 Tentar novamente"
BUTTON_PROCEED_WITHOUT_CPF = "📝 Registrar sem CPF"

# =============================================================================
# NAME COLLECTION MESSAGES (for proceed without CPF)
# =============================================================================

NAME_REQUEST_MESSAGE = """Informe seu nome completo por gentileza."""
