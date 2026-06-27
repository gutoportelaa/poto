"""User-facing messages for damage data collection flow.

This module contains all messages that are displayed directly to users via WhatsApp.
For LLM prompts, see prompts.py.
"""

# =============================================================================
# DAMAGE CONFIRMATION MESSAGES
# =============================================================================

DAMAGE_DETECTED_CONFIRM_MESSAGE = (
    "Identificamos que houve prejuízo financeiro nessa ocorrência. Você confirma isso?"
)

DAMAGE_ASK_MESSAGE = "Nessa situação, ocorreu prejuízo financeiro?"

DAMAGE_YES_OPTION = "Sim"
DAMAGE_NO_OPTION = "Não"


# =============================================================================
# DAMAGE VALUE COLLECTION MESSAGES
# =============================================================================

DAMAGE_VALUE_REQUEST_MESSAGE = "Qual o valor desse prejuízo?"

DAMAGE_VALUE_EXAMPLE = "Exemplo: 1.000 ou 1000"

DAMAGE_VALUE_CONFIRM_MESSAGE = "Esse prejuízo foi no valor de R${value}?"

DAMAGE_VALUE_INVALID_MESSAGE = (
    "Não consegui identificar o valor. Por favor, informe novamente apenas o número."
)


# =============================================================================
# PAYMENT METHOD COLLECTION MESSAGES
# =============================================================================

PAYMENT_METHOD_REQUEST_MESSAGE = "Qual foi a forma de pagamento utilizada?"

PAYMENT_METHOD_EXAMPLES = (
    "Exemplos: Pix, Cartão de crédito, Transferência bancária, Dinheiro, Boleto"
)


# =============================================================================
# RECEIPT COLLECTION MESSAGES
# =============================================================================

RECEIPT_ASK_MESSAGE = "Você gostaria de anexar o comprovante de pagamento?"

RECEIPT_REQUEST_MESSAGE = (
    "Envie a(s) foto(s) do comprovante. Quando terminar, é só digitar *pronto*."
)

RECEIPT_SKIP_OPTION = "Pular"
