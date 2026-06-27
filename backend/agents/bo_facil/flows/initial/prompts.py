"""LLM prompts for initial flow.

This module contains all prompts sent to the LLM for analysis and classification.
For user-facing messages, see messages.py.
"""

from langchain.prompts import SystemMessagePromptTemplate

# =============================================================================
# ANALYSIS PROMPTS - Classify user intent
# =============================================================================

user_choice_analysis_prompt = SystemMessagePromptTemplate.from_template("""Identifique qual serviço o usuário escolheu.

OPÇÕES:
1. bo_facil: registrar BO, relatar crime próprio
   - "fazer BO", "registrar", "fui roubado", "1", "primeira"
2. atendimento_190: orientação policial
   - "190", "falar com policial", "2", "segunda"
3. denuncia_anonima: denúncia ANÔNIMA de terceiros
   - "anônima" + "denúncia", "sem me identificar", "3", "terceira"

REGRAS:
- "denúncia" ISOLADA ≠ denúncia anônima
- "fazer BO" sempre = bo_facil, NUNCA denuncia_anonima
- Priorize intenção principal sobre palavras isoladas
- Ambíguo/não relacionado → null

═══════════════════════════════════════
RESPOSTA: "{user_response}"
═══════════════════════════════════════
""")
