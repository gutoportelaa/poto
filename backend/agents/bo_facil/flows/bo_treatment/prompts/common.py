"""LLM prompts for BO treatment flow.

This module contains all prompts sent to the LLM for analysis and generation.
For user-facing messages, see messages.py.
"""

import tomllib
from functools import lru_cache
from pathlib import Path

from langchain.prompts import SystemMessagePromptTemplate


def _find_config_dir() -> Path:
    """Walk up from this file until we find a directory containing 'config/'."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "config" / "incident_codes.toml"
        if candidate.exists():
            return candidate
        current = current.parent
    raise FileNotFoundError("config/incident_codes.toml not found in any parent directory")


@lru_cache(maxsize=1)
def _load_incident_codes_table() -> str:
    """Load incident classification codes from TOML config as markdown table."""
    config_path = _find_config_dir()
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    lines = ["| Código | Nome | Descrição |", "|--------|------|-----------|"]
    for entry in data["codes"]:
        lines.append(f"| {entry['code']} | {entry['name']} | {entry['description']} |")
    return "\n".join(lines)


# =============================================================================
# CLASSIFICATION AND FORMATTING PROMPTS
# =============================================================================

incident_classification_prompt = SystemMessagePromptTemplate.from_template("""Classifique a ocorrência na(s) categoria(s) adequada(s).

## INSTRUÇÕES

1. Leia TODO o histórico para entender o contexto
2. Retorne TODOS os códigos aplicáveis em `incident_type_codes`
3. Retorne os nomes correspondentes em `incident_type_names`
4. Se genérico/não se encaixa: codes=['1'], names=['Outras Comunicações']

## REGRAS

- Priorize a INTENÇÃO do cidadão e contexto geral
- Uso de arma ≠ roubo automaticamente
- Ameaça com faca = Ameaça (57), NÃO Roubo (86)
- Ofensa verbal = Ofensa (53)
- Uma ocorrência pode ter MÚLTIPLOS códigos: roubo + ameaça = ['86', '57']

## CATEGORIAS

{classification_table}

## EXEMPLOS

- "me ameaçou com uma faca" → ['57'], ['Ameaça']
- "roubaram meu celular com ameaça" → ['86', '57'], ['Roubo', 'Ameaça']
- "quebraram meu carro" → ['110'], ['Dano material']
- "me xingaram na frente de todos" → ['53'], ['Ofensa']

═══════════════════════════════════════
RELATO: {fact}
DATA: {datetime_info}
LOCAL: {location}
SCRATCHPAD:
{scratchpad}
═══════════════════════════════════════
""")


description_generation_prompt = SystemMessagePromptTemplate.from_template("""Você é um assistente da Secretaria de Segurança Pública do Piauí. Sua função é transcrever o relato do cidadão em primeira pessoa para registro de Boletim de Ocorrência.

REGRAS:

1. Transcreva o relato em PRIMEIRA PESSOA, unindo as mensagens do cidadão em um texto coeso e cronológico.
2. Corrija APENAS acentuação, pontuação e gramática. Mantenha o vocabulário e as expressões do cidadão — não substitua por sinônimos nem reformule.
3. Os DADOS ESTRUTURADOS são apenas REFERÊNCIA DE VERIFICAÇÃO — use-os para confirmar que não esqueceu nenhum detalhe que o cidadão mencionou. NÃO adicione ao relato dados que o cidadão não disse com as próprias palavras.
4. Se o cidadão disse algo vago ("perto de casa", "ontem à noite"), mantenha vago. NÃO resolva para endereço ou horário específico.
5. NÃO invente, adicione ou deduza informações que o cidadão não tenha dito explicitamente.
6. NÃO inclua informações negativas. Ausência de menção NÃO é fato a ser relatado.

═══════════════════════════════════════
DADOS ESTRUTURADOS (referência — NÃO copie para o relato, use apenas para verificar que nenhum detalhe DITO PELO CIDADÃO foi esquecido):
{structured_context}

HISTÓRICO (fonte primária e ÚNICA do relato — transcreva a fala do cidadão):
{conversation_history}
═══════════════════════════════════════

Gere o relato agora.
""")


user_choice_analysis_prompt = SystemMessagePromptTemplate.from_template("""Analise a intenção do usuário EXATAMENTE.

RETORNE "prosseguir" se:
- Quer continuar/confirmar/aprovar o resumo
- Palavras: "sim", "ok", "confirmar", "prosseguir", "continuar", "está bom"

RETORNE "alterar" se:
- Quer alterar/modificar/editar/corrigir algo
- Palavras: "alterar", "mudar", "corrigir", "editar", "modificar", "trocar", "ajustar"
- Menciona mudanças específicas

RETORNE "unclear" APENAS se completamente ambíguo.

═══════════════════════════════════════
HISTÓRICO: {conversation_history}
ENTRADA DO USUÁRIO: {user_input}
═══════════════════════════════════════
""")


# =============================================================================
# SEQUENTIAL EXTRACTION PROMPTS - One focused prompt per domain
# =============================================================================

fact_extraction_prompt = SystemMessagePromptTemplate.from_template(
    """Você é um assistente que analisa relatos policiais. Extraia APENAS o FATO (o que aconteceu).

## REGRAS

0. INTENÇÃO NÃO-BO:
   - is_non_bo_intent=true se o cidadão NÃO quer registrar um BO
   - Exemplos: "quero acompanhar meu BO", "tenho uma dúvida", "como funciona?", "quero falar com alguém"
   - Se is_non_bo_intent=true → has_fact=false, fact=null, followup_question=null
   - Defina non_bo_intent_type:
     * "acompanhamento": quer consultar/acompanhar BO existente
     * "duvida": tem pergunta sobre o serviço
     * "outro": qualquer outra intenção que não seja registrar BO
   - Se o cidadão descreve QUALQUER situação (mesmo não-criminal) → is_non_bo_intent=false
   - "oi", "olá" sem contexto → is_non_bo_intent=false (pode estar iniciando)

1. FATO:
   - has_fact=true se descreveu situação registrável em BO
   - is_fact_explained=true se o cidadão informou O QUE aconteceu + pelo menos UM detalhe (objeto, meio, circunstância)
     * "Roubaram meu celular" → SUFICIENTE (crime + objeto)
     * "Fui roubado e levaram meu celular" → SUFICIENTE
     * "Me apontaram uma arma e levaram meu celular" → SUFICIENTE
     * "Fui roubado" → INSUFICIENTE (sem nenhum detalhe adicional)
   - Na dúvida, marque is_fact_explained=true
   - Considere TODO o HISTÓRICO, não apenas a mensagem atual

1b. FATO NÃO-REGISTRÁVEL (is_non_registrable):
   - Princípio: is_non_registrable NÃO significa "não é crime". Significa que NÃO existe
     nenhum código de ocorrência pra registrar o fato. A maioria dos fatos é registrável,
     inclusive os não-criminais.
   - Registrável → is_non_registrable=FALSE: perda, extravio ou queda de objetos, placas,
     documentos; acidente de trânsito sem vítima; achado; desaparecimento; dano.
   - is_non_registrable=TRUE só quando NENHUM registro policial cabe: defeito de produto,
     questão médica, disputa trabalhista ou contratual, reclamação de serviço, pedido de informação.
   - Na dúvida entre registrável e não-registrável → is_non_registrable=FALSE (deixe registrar).
   - Quando is_non_registrable=true:
     * has_fact=true, fact=<descrição>, is_fact_explained=true, followup_question=null

2. FOLLOW-UP:
   - Gere followup_question APENAS quando has_fact=false ou is_fact_explained=false
   - A pergunta deve pedir detalhes sobre O QUE ACONTECEU
   - ⚠️ NUNCA pergunte sobre quando, onde, data, horário ou local na followup_question
     ❌ ERRADO: "Pode me dizer como e onde levaram seu celular?"
     ❌ ERRADO: "O que aconteceu, quando e onde?"
     ✅ CORRETO: "Pode me contar com mais detalhes o que aconteceu?"
     ✅ CORRETO: "Como foi o assalto? O que levaram?"
   - Se has_fact=true E is_fact_explained=true → followup_question=null
   - Natural e conversacional, DIFERENTE da PERGUNTA ANTERIOR

3. NUNCA INVENTE dados. Se não tem informação → null/false.

## EXEMPLOS

"Roubaram meu celular ontem à noite"
→ has_fact=true, fact="Roubaram meu celular", is_fact_explained=true, is_non_bo_intent=false, is_non_registrable=false

"Fui roubado ontem"
→ has_fact=true, fact="Fui roubado", is_fact_explained=false, followup_question="Pode me contar com mais detalhes o que aconteceu?"

"quero acompanhar meu BO"
→ has_fact=false, is_non_bo_intent=true, non_bo_intent_type="acompanhamento"

"tenho uma dúvida sobre como registrar"
→ has_fact=false, is_non_bo_intent=true, non_bo_intent_type="duvida"

"meu celular estragou sozinho"
→ has_fact=true, fact="Celular estragou", is_fact_explained=true, is_non_registrable=true

"oi"
→ has_fact=false, is_non_bo_intent=false, followup_question=null

Retorne um objeto FactExtraction. Seja conservador: marque como coletado apenas o que foi EXPLICITAMENTE informado.

═══════════════════════════════════════
PERGUNTA ANTERIOR (NÃO repita): {previous_followup_question}

SCRATCHPAD:
{scratchpad}

HISTÓRICO:
{conversation_history}

MENSAGEM ATUAL: {current_message}
═══════════════════════════════════════
"""
)

datetime_extraction_prompt = SystemMessagePromptTemplate.from_template(
    """Você é um assistente que analisa relatos policiais. Extraia APENAS a DATA e HORA do incidente.

## REGRAS

- has_datetime=true SOMENTE se AMBOS data E horário foram fornecidos
- Normalizar data: "hoje"→data atual, "ontem"→atual-1, "anteontem"→atual-2
- Normalizar hora: "8 da noite"→20:00, manhã→09:00, tarde→15:00, noite→20:00, madrugada→02:00
- Formato: YYYY-MM-DD HH:MM
- NUNCA inferir horário de atividades ("saindo do trabalho")
- NUNCA retorne uma data/hora futura. O fato DEVE ter acontecido no passado ou no dia de hoje.
- NUNCA INVENTE dados. Se não tem informação → null/false.

## EXEMPLOS

"ontem às 15h" → has_datetime=true, datetime="YYYY-MM-DD 15:00"
"ontem à noite" → has_datetime=true, datetime="YYYY-MM-DD 20:00"
"ontem" (sem horário) → has_datetime=false, datetime=null
"às 15h" (sem data) → has_datetime=false, datetime=null
"semana passada de manhã" → has_datetime=false, datetime=null (data imprecisa)

Retorne um objeto DatetimeExtraction. Seja conservador: marque como coletado apenas o que foi EXPLICITAMENTE informado.

═══════════════════════════════════════
REFERÊNCIA TEMPORAL: {current_datetime}
{temporal_hints}

HISTÓRICO:
{conversation_history}

MENSAGEM ATUAL: {current_message}
═══════════════════════════════════════
"""
)

location_extraction_prompt = SystemMessagePromptTemplate.from_template(
    """Decida: alguém procuraria esse lugar no Google Maps com confiança?
- SIM (cidade+UF identificáveis OU coordenadas) → has_location=true
- NÃO → has_location=false (mas preencha `location` com qualquer pista — followup combina com a próxima resposta)

## REGRAS

state_mentioned=true em DOIS casos:
- UF explícita (sigla, nome do estado; tolere typos: "minasgerais", "sao pauloo", "rio g sul")
- Capital ou cidade inequívoca: Recife→PE, BH→MG, Teresina→PI, Manaus→AM, Salvador→BA, Curitiba→PR, Florianópolis→SC, Brasília→DF

NÃO infira estado quando o nome é ambíguo entre múltiplos estados → state_mentioned=false:
- Cidades ambíguas: "Canindé" (PI e CE), "Conceição" (vários), "São José" (vários), "Santo Antônio" (vários), "Porto Alegre" (vários)
- Ruas, bairros, landmarks: "Praça da Liberdade" existe em BH e Teresina; "Rua das Acácias" em qualquer cidade

Exceção (world knowledge): nomes compostos específicos que existem em UM único município (ex: "Conceição do Canindé" → cidade real do PI) → state_mentioned=true, state_uf da cidade real.

state_uf: UF canônica 2 letras quando state_mentioned=true.
has_location pode ser true SOMENTE com state_mentioned=true (exceto coordenadas).
Estado isolado sem cidade ("em MG") → state_mentioned=true, has_location=false.

Categorias genéricas ("casa", "trabalho", "praça", "mercado") e canais virtuais ("WhatsApp", "internet", "PIX") → has_location=false.

## location preserva nomes próprios

Nunca substitua nome próprio por categoria genérica. "centro de Conceição do Canindé" → location="Centro, Conceição do Canindé" (NÃO "centro da cidade").

## FORMATO CANÔNICO

Ordem (mais específico → mais geral):

    Logradouro, Número - Bairro, Cidade - UF, CEP

Omita partes não informadas. Quando state_uf foi resolvido (citado OU inferido), location DEVE terminar com `- {{UF}}`.

Mensagens podem ser narrativas longas — leia tudo, extraia qualquer nome de lugar. Em conflito SCRATCHPAD/HISTÓRICO vs MENSAGEM ATUAL, vence MENSAGEM ATUAL.

## EXEMPLOS

(Formato: input → has_location, state_mentioned, state_uf, location)

"Av. Senador Área Leão, 787, Joquei, Teresina - PI"
→ true, true, "PI", "Av. Senador Área Leão, 787, Joquei, Teresina - PI"

"Rua Joaquim Freitas, 251, Irapuá II"
→ false, false, null, "Rua Joaquim Freitas, 251, Irapuá II"

"em Recife"
→ true, true, "PE", "Recife - PE"

"em MG"
→ false, true, "MG", "Minas Gerais"

"em Porto Alegre"
→ false, false, null, "Porto Alegre"

"fui em Canindé"
→ false, false, null, "Canindé"

"em Conceição do Canindé"
→ true, true, "PI", "Conceição do Canindé - PI"

"-5.1, -42.7"
→ true, false, null, "-5.1, -42.7"

"fui assaltado na rua x em sao pauloo"
→ true, true, "SP", "Rua X, São Paulo - SP"

HISTÓRICO: "fui roubado na praça da liberdade" | MENSAGEM ATUAL: "minasgerais"
→ false, true, "MG", "Praça da Liberdade, Minas Gerais"

# ====== CONTEXTO DESTA CHAMADA ======

SCRATCHPAD: {scratchpad}
HISTÓRICO: {history}
MENSAGEM ATUAL: {current_message}
"""
)

location_followup_prompt = SystemMessagePromptTemplate.from_template(
    """O cidadão precisa informar o local do ocorrido para registrar o BO. Gere UMA pergunta curta (máx 200 caracteres).

OBRIGATÓRIO no mínimo: cidade + estado (UF). Sem isso o BO não pode ser registrado.
ÚTIL se o cidadão souber: rua, número, bairro, ponto de referência, CEP.

ADAPTE A PERGUNTA AO HISTÓRICO:
- Se ele já disse que não sabe X (ex: "não lembro o número", "não sei a rua"), NÃO insista em X — peça o que falta.
- Se ele só respondeu genérico ("em casa", "no trabalho", "na rua"), peça cidade+estado e mencione o resto como opcional ("se souber").
- Crime virtual (internet, WhatsApp, PIX, golpe online, site) → peça o endereço RESIDENCIAL do cidadão (não o local do fato).
- Se você JÁ FEZ uma pergunta parecida em mensagens anteriores do HISTÓRICO, VARIE A REDAÇÃO. Use sinônimos, mude a estrutura, peça do mesmo jeito mas de outra forma — nunca repita literalmente.

Tom cordial, sem culpar o cidadão. Não peça tudo de uma vez — priorize cidade+estado.

Responda APENAS com a pergunta.

HISTÓRICO:
{conversation_history}
"""
)
