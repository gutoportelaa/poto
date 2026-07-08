"""Esquemas Pydantic e enums do domínio P.O.T.O."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TipoOcorrencia(str, Enum):
    seguranca = "seguranca"
    mulher = "mulher"
    saude = "saude"
    ouvidoria = "ouvidoria"


class Modo(str, Enum):
    normal = "normal"
    discreto = "discreto"


class OrigemAcionamento(str, Enum):
    botao_fisico = "botao_fisico"
    touch = "touch"
    panico = "panico"


class Gravidade(str, Enum):
    risco_imediato = "risco_imediato"
    risco_potencial = "risco_potencial"
    orientacao = "orientacao"


class StatusChamado(str, Enum):
    recebido = "recebido"
    roteado = "roteado"
    pendente_validacao = "pendente_validacao"  # "suposto perigo": aguarda o operador confirmar
    notificado = "notificado"
    alerta_ativo = "alerta_ativo"  # pânico em curso, persistente até atendimento
    reconhecido = "reconhecido"
    em_atendimento = "em_atendimento"
    encerrado = "encerrado"
    escalonado = "escalonado"
    falha_notificacao = "falha_notificacao"
    cancelado = "cancelado"


class NivelRisco(str, Enum):
    """Regime de autonomia da triagem (Fase 1 — validação humana em 3 níveis).

    - claro: sinal crítico/risco_imediato -> aciona já, humano acompanha (não é gate).
    - suposto: risco_potencial/ameaça difusa/baixa confiança -> aguarda validação humana,
      com escalonamento automático por timeout (fail-safe protetivo).
    - normal: orientação com confiança alta -> bot conduz e encaminha sozinho.
    """

    claro = "claro"
    suposto = "suposto"
    normal = "normal"


# --- Entrada: evento do totem --------------------------------------------
class EventoIn(BaseModel):
    evento_id: str = Field(..., description="UUID v4 gerado no totem (idempotência).")
    totem_id: str = Field(..., examples=["TOTEM-CCS-01"])
    tipo_ocorrencia: TipoOcorrencia
    modo: Modo = Modo.normal
    origem_acionamento: OrigemAcionamento = OrigemAcionamento.touch
    timestamp_local: str | None = None
    firmware_versao: str | None = None
    texto_livre: str | None = Field(None, description="Texto opcional para triagem por IA.")
    assinatura: str | None = None


class InstrucaoTotem(BaseModel):
    mensagem_tela: str
    feedback_sonoro: bool = True
    tela_neutra: bool = False


class EventoOut(BaseModel):
    chamado_id: str
    status: StatusChamado
    canal_roteado: str
    gravidade: Gravidade
    instrucao_totem: InstrucaoTotem
    duplicado: bool = False


# --- Pânico (broadcast + escalonamento manual, DESIGN.md §13.2) -----------
class PanicoIn(BaseModel):
    evento_id: str = Field(..., description="UUID v4 gerado no totem (idempotência).")
    totem_id: str = Field(..., examples=["TOTEM-CCS-01"])
    modo: Modo = Modo.normal
    timestamp_local: str | None = None


class CanalResultado(BaseModel):
    canal: str
    nome: str
    destino: str
    sucesso: bool
    detalhe: str | None = None


class CanalOpcao(BaseModel):
    canal: str
    nome: str
    destino: str


class PanicoOut(BaseModel):
    chamado_id: str
    status: StatusChamado
    gravidade: Gravidade
    resultados: list[CanalResultado] = Field(default_factory=list)
    escalonamento_disponivel: list[CanalOpcao] = Field(default_factory=list)
    duplicado: bool = False


class EscalonamentoIn(BaseModel):
    canal: str = Field(..., description="Canal de autoridade do estado (ex.: samu_192).")


class ValidacaoIn(BaseModel):
    """Decisão do operador sobre um chamado em 'pendente_validacao' (nível suposto)."""

    decisao: str = Field(..., description="'confirmar' | 'reclassificar' | 'falso_alarme'")
    tipo_ocorrencia: TipoOcorrencia | None = Field(
        None, description="Novo tipo, obrigatório quando decisao='reclassificar'."
    )
    observacao: str | None = None


# --- Triagem por agentes (conversacional) --------------------------------
class TriagemIn(BaseModel):
    texto: str
    modo: Modo = Modo.normal


class TriagemOut(BaseModel):
    tipo_sugerido: TipoOcorrencia
    gravidade: Gravidade
    confianca: float
    mensagem_acolhimento: str
    canal_sugerido: str
    escalonar_humano: bool
    fonte: str = Field(description="'agentes' (LLM) ou 'heuristica' (fallback).")
    nivel: NivelRisco = Field(
        NivelRisco.normal,
        description="Regime de autonomia: claro (aciona já) | suposto (gate humano) | normal (autônomo).",
    )


# --- Conversa por voz (triagem multi-turno) ------------------------------
class ConversaTurn(BaseModel):
    papel: str = Field(description="'usuario' ou 'assistente'.")
    texto: str


class ConversaIn(BaseModel):
    historico: list[ConversaTurn]
    modo: Modo = Modo.normal


class ConversaOut(BaseModel):
    fala: str = Field(description="O que o atendimento deve falar em seguida (TTS).")
    concluido: bool
    tipo_sugerido: TipoOcorrencia | None = None
    gravidade: Gravidade | None = None
    canal_sugerido: str | None = None
    escalonar_humano: bool = False
    nivel: NivelRisco | None = None


class AbandonoIn(BaseModel):
    """Registro de abandono da conversa (sem o texto — minimização LGPD)."""

    totem_id: str = "TOTEM-?"
    motivo: str = Field("desistencia", description="'desistencia' (manual) ou 'inatividade' (10 min).")
    turnos: int = 0


# --- Painel ---------------------------------------------------------------
class ChamadoUpdate(BaseModel):
    status: StatusChamado | None = None
    observacao: str | None = None


class HeartbeatIn(BaseModel):
    online: bool = True
    bateria: int | None = None
    conectividade: str | None = None
    tamper: bool = False
