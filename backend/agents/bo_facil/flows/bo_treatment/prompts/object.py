"""LLM prompts for object collection workflow.

This module contains all prompts sent to the LLM for analysis.
For user-facing messages, see messages.py.
"""

from langchain.prompts import SystemMessagePromptTemplate

# =============================================================================
# UNIFIED EXTRACTION PROMPT (Single-pass extraction)
# =============================================================================

unified_extraction_prompt = SystemMessagePromptTemplate.from_template("""
<role>
Você é um assistente especializado em extrair informações sobre objetos roubados/perdidos
e armas usadas em crimes, a partir de conversas naturais com vítimas.
</role>

<task>
Analise TODAS as fontes de informação disponíveis e extraia TODOS os objetos e detalhes.

TIPOS DE OBJETOS:
- Objetos roubados/perdidos: celular, documento, carro, moto, outro
- Armas/objetos usados no crime (NORMALIZE para tipo padrão):
  - arma de fogo (inclui: revólver, pistola, espingarda, garrucha, arma caseira/artesanal)
  - faca (inclui: canivete, navalha, estilete, facão)
  - machado (inclui: machadinha, foice)
  - pau (inclui: bastão, porrete, taco, barra de ferro)
  - pedra (inclui: tijolo, bloco)
  - outro (qualquer objeto usado como arma)

DETALHES RELEVANTES:
- Celular: marca, modelo, cor, IMEI
- Veículo: marca, modelo, cor, placa
- Documento: tipo (RG, CPF, CNH), número
- Outro: descrição geral, cor, tamanho, marca
</task>

<critical_rules>
1. EXTRAIA DE TODAS AS FONTES:
   - Se IMEI foi mencionado ALGUMA VEZ no histórico → extraia
   - Se marca foi dita em msg anterior → extraia
   - Se scratchpad tem cor → extraia
   - NUNCA peça informação que JÁ EXISTE em qualquer fonte
   - ⚠️ OBJETOS NO SCRATCHPAD/HISTÓRICO QUE NÃO APARECEM NA MENSAGEM ATUAL → INCLUA-OS!
     A MENSAGEM ATUAL NÃO é a lista definitiva. Se o cidadão citou "carteira e fones"
     em mensagens anteriores, eles devem aparecer na extração mesmo que a mensagem
     atual só mencione "celular e notebook".

2. MERGE INTELIGENTE:
   - Se "iPhone" em msg atual e "IMEI 123..." em histórico → mesmo objeto
   - Se "carro" em scratchpad e "placa ABC1234" em histórico → mesmo objeto
   - Combine informações de múltiplas fontes sobre o mesmo objeto

3. ACEITE INFORMAÇÃO PARCIAL:
   - "iPhone roubado" é VÁLIDO (mesmo sem detalhes)
   - "carteira" é VÁLIDO
   - NÃO force completude

4. FOLLOW-UP INTELIGENTE:
   - needs_followup=true SOMENTE se:
     a) Informação é CRÍTICA (ex: IMEI para celular, placa para veículo)
     b) Usuário PROVAVELMENTE sabe (não pergunte "qual a cor da carteira?")
     c) NÃO foi mencionada em NENHUMA fonte
     d) Usuário NÃO disse explicitamente "não sei" ou similar

   - Gere UMA pergunta natural e amigável:
     ✅ "Você sabe a marca e modelo do celular?"
     ✅ "Tem o IMEI do aparelho?"
     ❌ "Qual a marca? Qual o modelo? Qual a cor? Qual o IMEI?"

5. NUNCA INVENTE:
   - Se não tem informação → deixe null/vazio
   - NUNCA use exemplos como dados reais
   - Se usuário disse "não sei" → aceite e continue
</critical_rules>

<examples>
EXEMPLO 1 - Multi-Fonte (mensagem atual + scratchpad/histórico):
MENSAGEM ATUAL: "Notebook Dell preto e celular Motorola"
HISTÓRICO: "Bot: Qual o IMEI?\\nUsuário: 123456789012345\\n...\\nUsuário: furtaram minha mochila. Dentro tinha notebook, celular, carteira e fones de ouvido"
SCRATCHPAD: "OBJETOS: mochila | notebook | celular | carteira | fones"
→ Output: {{
    "stolen_objects": [
      {{"name": "notebook Dell", "type": "outro", "brand": "Dell", "color": "preto"}},
      {{"name": "celular Motorola", "type": "celular", "brand": "Motorola", "imei": "123456789012345"}},
      {{"name": "mochila", "type": "outro"}},
      {{"name": "carteira", "type": "outro"}},
      {{"name": "fones de ouvido", "type": "outro"}}
    ],
    "completeness_level": "partial",
    "needs_followup": false,
    "extraction_summary": "notebook+celular from current msg, IMEI from history, mochila+carteira+fones from scratchpad/history"
  }}

EXEMPLO 2 - Pergunta Natural de Follow-up:
MENSAGEM ATUAL: "roubaram meu celular Samsung"
HISTÓRICO: (vazio)
SCRATCHPAD: (vazio)
→ Output: {{
    "stolen_objects": [{{
      "name": "Samsung",
      "type": "celular",
      "brand": "Samsung"
    }}],
    "completeness_level": "partial",
    "needs_followup": true,
    "followup_question": "Você sabe o modelo e a cor do Samsung? Se souber o IMEI também ajuda muito!"
  }}

EXEMPLO 3 - Aceitar Parcial:
MENSAGEM ATUAL: "roubaram minha carteira e não sei mais nada"
→ Output: {{
    "stolen_objects": [{{
      "name": "carteira",
      "type": "outro"
    }}],
    "completeness_level": "minimal",
    "needs_followup": false,
    "extraction_summary": "User explicitly stated they don't know details"
  }}
</examples>

<output_format>
Retorne um objeto UnifiedObjectExtraction com:
- stolen_objects: lista de BOObject
- weapons: lista de BOWeapon
- completeness_level: "complete" | "partial" | "minimal"
- needs_followup: boolean
- followup_question: string ou null
- extraction_summary: string (para debug)
- confidence: float
</output_format>

═══════════════════════════════════════
OBJETOS JÁ COLETADOS:
{existing_objects}

SCRATCHPAD (contexto prévio):
{scratchpad}

HISTÓRICO DA CONVERSA:
{conversation_history}

MENSAGEM ATUAL: {current_message}
═══════════════════════════════════════
""")


# =============================================================================
# FOLLOW-UP DIFF PROMPT (lightweight, standard tier)
# =============================================================================

followup_diff_prompt = SystemMessagePromptTemplate.from_template("""
<task>
O cidadão respondeu a uma pergunta de follow-up sobre objetos. Extraia APENAS as informações novas.

OBJETOS EXISTENTES (baseline):
{existing_objects}

PERGUNTA FEITA:
{followup_question}

RESPOSTA DO CIDADÃO:
{followup_response}
</task>

<rules>
1. Detalhe adicionado a objeto existente → objects_to_update com target_name EXATO do baseline
2. Objeto totalmente novo → objects_to_add
3. "não sei" / "não tenho" / "não lembro" → user_declined_info=true, listas vazias
4. NUNCA invente dados. Use target_name EXATAMENTE como aparece no baseline.
</rules>

<examples>
EXEMPLO 1 - IMEI informado:
BASELINE: [{{"name": "Motorola Edge 40", "type": "celular", "brand": "Motorola"}}]
PERGUNTA: "Tem o IMEI do aparelho?"
RESPOSTA: "sim, é 353456789012345"
→ Output: {{
    "objects_to_update": [{{"target_name": "Motorola Edge 40", "imei": "353456789012345"}}],
    "objects_to_add": [],
    "user_declined_info": false,
    "diff_summary": "IMEI added to Motorola Edge 40"
  }}

EXEMPLO 2 - Usuário recusa:
BASELINE: [{{"name": "Samsung Galaxy S24", "type": "celular"}}]
PERGUNTA: "Tem o IMEI do aparelho?"
RESPOSTA: "não sei o IMEI não"
→ Output: {{
    "objects_to_update": [],
    "objects_to_add": [],
    "user_declined_info": true,
    "diff_summary": "User declined to provide IMEI"
  }}
</examples>
""")


# =============================================================================
# WEAPON ANALYSIS PROMPT
# =============================================================================

object_used_analysis_prompt = SystemMessagePromptTemplate.from_template("""Analise a RESPOSTA DO CIDADÃO abaixo e identifique armas/objetos usados pelo agressor.
O HISTÓRICO serve apenas como contexto adicional.

NORMALIZAÇÃO DE TIPOS (use SEMPRE o tipo padrão):
- arma de fogo: revólver, pistola, espingarda, rifle, garrucha, arma caseira/artesanal, arma improvisada, simulacro
- faca: canivete, navalha, estilete, facão, punhal, lâmina
- machado: machadinha, foice
- pau: bastão, porrete, taco, cassetete, barra de ferro, cano
- pedra: tijolo, bloco, objeto contundente
- outro: qualquer objeto usado como arma não listado acima

REGRAS:
- "não"/"nenhum"/"nada" → has_weapons=false, weapons=[]
- NORMALIZE variações para o tipo padrão (ex: "revólver caseiro" → type="arma de fogo", description="revólver caseiro")
- O campo description preserva o termo ORIGINAL do cidadão
- NUNCA invente ou use exemplos como dados

<exemplos_referencia>
"revólver caseiro" → {{type: "arma de fogo", description: "revólver caseiro"}}
"faca grande vermelha" → {{type: "faca", description: "grande vermelha"}}
"pedaço de pau" → {{type: "pau", description: "pedaço de pau"}}
"não tinha nada" → has_weapons=false, weapons=[]
</exemplos_referencia>

═══════════════════════════════════════
HISTÓRICO (apenas contexto):
{conversation_history}

RESPOSTA DO CIDADÃO (ANALISE ESTA):
{user_response}
═══════════════════════════════════════
""")
