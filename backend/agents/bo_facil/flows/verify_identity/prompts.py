"""LLM prompts for verify_identity flow.

This module contains all prompts sent to the LLM for analysis.
For user-facing messages, see messages.py.
"""

# =============================================================================
# VERIFICATION ANALYSIS PROMPTS (Minimal)
# =============================================================================

BIRTH_YEAR_ANALYSIS_PROMPT = """Identifique qual ano de nascimento o usuário escolheu.

OPÇÕES APRESENTADAS: {year_options}
ANO CORRETO: {correct_year}

FORMAS DE RESPOSTA ACEITAS:
- Ano direto: "1990"
- Posição: "primeira", "segunda", "terceira"
- Letras/números: "A", "B", "C", "1", "2", "3"

═══════════════════════════════════════
RESPOSTA DO USUÁRIO: {user_message}
═══════════════════════════════════════
"""

USER_DECISION_ANALYSIS_PROMPT = """Determine a decisão do usuário após falha na verificação.

OPÇÕES:
- "retry": tentar verificação novamente
- "proceed_without_cpf": prosseguir sem CPF

═══════════════════════════════════════
RESPOSTA DO USUÁRIO: {user_message}
═══════════════════════════════════════
"""
