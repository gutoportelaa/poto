"""LLM prompts for anonymous flow.

This module contains all prompts sent to the LLM for analysis.
For user-facing messages, see messages.py.
"""

from langchain_core.prompts import SystemMessagePromptTemplate

# =============================================================================
# CRIME CLASSIFICATION PROMPT (Instructional)
# =============================================================================

crime_classification_prompt = SystemMessagePromptTemplate.from_template("""Classifique a denúncia anônima nas categorias aplicáveis.

## INSTRUÇÕES
1. Para cada categoria, responda "sim" ou "não" com base APENAS no relato
2. Adicione os IDs das respostas "sim" ao resultado
3. crime_detected = "yes" se pelo menos 1 categoria | "no" se nenhuma
4. crime_type_codes = IDs separados por vírgula | null se nenhum

## CATEGORIAS

| ID | Categoria |
|----|-----------|
| 26 | Corrupção, lavagem de dinheiro, desvio de verbas |
| 27 | Envolvimento de menores de idade |
| 28 | Pornografia infantil, abuso de menores |
| 29 | Maus-tratos de animais |
| 30 | Tráfico ou uso de drogas |
| 31 | Violência doméstica |
| 32 | Foragido envolvido |

═══════════════════════════════════════
RELATO: {user_report}
═══════════════════════════════════════
""")

# =============================================================================
# CITY VALIDATION PROMPT (Minimal)
# =============================================================================

city_validation_prompt = SystemMessagePromptTemplate.from_template("""Identifique se há nome de cidade na mensagem.

RESULTADO:
- Cidade identificada → is_valid="yes", city_name="nome da cidade"
- Sem cidade → is_valid="no", city_name=null

═══════════════════════════════════════
MENSAGEM: {user_input}
═══════════════════════════════════════
""")
