"""LLM prompts for person collection workflow - simplified.

This module contains the prompt for extracting persons from user descriptions.
"""

from langchain.prompts import SystemMessagePromptTemplate

persons_analysis_prompt = SystemMessagePromptTemplate.from_template(
    """Identifique pessoas envolvidas no incidente.

CAMPOS POR PESSOA:
- name: Nome ou "Suspeito", "Testemunha"
- type: "suspeito", "testemunha" ou "outro_envolvido"
- description: TODAS características em UM texto

REGRAS ANTI-DUPLICAÇÃO (CRÍTICO):
- Múltiplas características = UMA pessoa, NÃO várias
- "cabelo platinado e tatuagem" = 1 pessoa
- "homem armado com faca" = 1 pessoa
- Múltiplas pessoas SÓ se explícito: "dois homens", "eram três"
- Prefira MENOS pessoas do que criar duplicatas

has_persons:
- true: identificou pelo menos uma pessoa
- false: "não", "ninguém", "não havia"

<exemplos_referencia>
"cara de cabelo platinado e tatuagem, andava de moto" → 1 PESSOA: {{name: "Suspeito", description: "cabelo platinado, tatuagem, andava de moto"}}
"eram dois, um de capuz e outro com faca" → 2 PESSOAS (explícito "eram dois")
"não vi ninguém" → has_persons=false, persons=[]
</exemplos_referencia>

═══════════════════════════════════════
HISTÓRICO:
{conversation_history}

RESPOSTA: "{user_response}"
═══════════════════════════════════════
"""
)
