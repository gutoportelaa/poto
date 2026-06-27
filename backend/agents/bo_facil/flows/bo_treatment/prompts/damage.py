"""LLM prompts for damage data collection.

This module contains all prompts sent to the LLM for analysis.
For user-facing messages, see messages.py.
"""

from langchain_core.prompts import SystemMessagePromptTemplate

# =============================================================================
# DAMAGE ANALYSIS PROMPT (Analysis)
# =============================================================================

damage_analysis_prompt = SystemMessagePromptTemplate.from_template(
    """Identifique prejuízo financeiro no relato.

CAMPOS:
- has_damage: true se há prejuízo financeiro
- damage_value: valor numérico ou null
- payment_method: forma de pagamento ou null

REGRAS:
1. Prejuízo claro com valor → has_damage=true, damage_value=número
2. Prejuízo sem valor identificado → has_damage=true, damage_value=null
3. Sem prejuízo → has_damage=false

CONVERSÃO DE VALORES:
- "8mil" → 8000.0
- "dois mil e quinhentos" → 2500.0
- "R$ 1.200,00" → 1200.0

FORMAS DE PAGAMENTO VÁLIDAS:
Pix | Cartão crédito | Cartão débito | Transferência | Depósito | Boleto | Dinheiro

NUNCA invente valores ou formas de pagamento - use APENAS informações explícitas.

═══════════════════════════════════════
DADOS ESTRUTURADOS: {incident_text}

HISTÓRICO:
{conversation_history}
═══════════════════════════════════════
"""
)


# =============================================================================
# DAMAGE VALUE EXTRACTION PROMPT (Minimal)
# =============================================================================

damage_value_extraction_prompt = SystemMessagePromptTemplate.from_template(
    """Converta o valor informado para número.

CONVERSÕES:
- "4 mil" → 4000.0
- "R$ 1.200,50" → 1200.50
- "dois milhões e quinhentos mil" → 2500000.0

Se houver um número válido → is_valid=true, extracted_value=número (tem prioridade).

SEM DANO (no_damage) — usar com cautela:
Marque no_damage=true SOMENTE quando o usuário afirma que NÃO houve prejuízo
financeiro algum (ex.: "não houve prejuízo", "não tive prejuízo financeiro",
"prejuízo nenhum"). Isso contradiz uma confirmação anterior de dano.

NÃO marque no_damage quando o usuário apenas desconhece ou não quer dizer o
VALOR (ex.: "não sei o valor", "não tem como saber", "não lembro quanto"):
nesse caso o dano existe, só o valor é desconhecido → is_valid=false,
no_damage=false (o fluxo segue sem o valor, preservando o dano).

═══════════════════════════════════════
VALOR INFORMADO: {user_input}
═══════════════════════════════════════
"""
)


# =============================================================================
# CONFIRMATION ANALYSIS PROMPT (Minimal)
# =============================================================================

confirmation_analysis_prompt = SystemMessagePromptTemplate.from_template(
    """Determine se o usuário confirmou ou negou.

CAMPOS:
- confirmed: true (sim, correto, isso) | false (não, errado)
- wants_to_correct: true se quer corrigir o valor

═══════════════════════════════════════
HISTÓRICO:
{conversation_history}

RESPOSTA: {user_input}
═══════════════════════════════════════
"""
)
