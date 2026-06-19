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


class Gravidade(str, Enum):
    risco_imediato = "risco_imediato"
    risco_potencial = "risco_potencial"
    orientacao = "orientacao"


class StatusChamado(str, Enum):
    recebido = "recebido"
    roteado = "roteado"
    notificado = "notificado"
    reconhecido = "reconhecido"
    em_atendimento = "em_atendimento"
    encerrado = "encerrado"
    escalonado = "escalonado"
    falha_notificacao = "falha_notificacao"
    cancelado = "cancelado"


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


# --- Painel ---------------------------------------------------------------
class ChamadoUpdate(BaseModel):
    status: StatusChamado | None = None
    observacao: str | None = None


class HeartbeatIn(BaseModel):
    online: bool = True
    bateria: int | None = None
    conectividade: str | None = None
    tamper: bool = False
