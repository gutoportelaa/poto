"""LLM prompts for the classification service.

Principle shared by all three prompts: the BO Fácil exists to register incidents,
so reporting a crime — however serious, violent or distressing — is the expected
use and does not justify a redirect. The class is decided by timing (emergency only
if danger is in progress now) and by the citizen's explicit request (human only when
asked), never by the severity of the facts.
"""

# =============================================================================
# EMERGENCY DETECTION
# =============================================================================

EMERGENCY_DETECTION_PROMPT = """Identifique se há perigo físico iminente em curso NESTE momento (is_emergency).

## CRITÉRIO
A vítima corre risco físico agora: agressão acontecendo, agressor no local,
ferimento grave atual, pedido de socorro imediato. Fato passado, ameaça sem perigo
imediato ou descrição de arma usada em crime anterior não é emergency.

═══════════════════════════════════════
MENSAGEM ATUAL: {message}
HISTÓRICO: {context}
═══════════════════════════════════════
"""

# =============================================================================
# HUMAN HANDOFF DETECTION
# =============================================================================

HUMAN_HANDOFF_PROMPT = """Identifique se o cidadão pede explicitamente atendimento humano (needs_human).

## CRITÉRIO
Pedido direto para falar com pessoa/atendente, ou recusa explícita do atendimento
automático. Descrever o caso, citar terceiros (autor, suspeito, vítima) ou relatar
um fato não é pedido de humano.

═══════════════════════════════════════
MENSAGEM ATUAL: {message}
HISTÓRICO: {context}
═══════════════════════════════════════
"""

# =============================================================================
# COMBINED CLASSIFICATION (emergency / human / neutral)
# =============================================================================

COMBINED_CLASSIFICATION_PROMPT = """Classifique a mensagem do cidadão em EMERGENCY, HUMAN ou NEUTRAL.

O BO Fácil serve para registrar ocorrências. Relatar um crime — ainda que grave,
violento ou angustiante — é o uso esperado e deve ser NEUTRAL. A gravidade do fato
não altera a classe; o que decide é o momento do perigo e o pedido do cidadão.

## EMERGENCY
Perigo físico em curso agora: agressão acontecendo, agressor no local, ferimento
grave atual, pedido de socorro imediato. Fato passado ou ameaça sem perigo imediato
não é emergency.

## HUMAN
Pedido explícito para falar com pessoa/atendente, ou recusa do atendimento
automático. Menção a terceiros do caso (autor, suspeito, vítima) não conta.

## NEUTRAL
Todo o resto, incluindo relatos de fato e respostas ao fluxo. Na dúvida entre HUMAN
e NEUTRAL durante um registro, escolha NEUTRAL.

═══════════════════════════════════════
MENSAGEM ATUAL: {message}
HISTÓRICO: {context}
═══════════════════════════════════════
"""
