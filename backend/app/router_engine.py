"""Roteador determinístico de chamados.

Decide canal primário, fallback, gravidade default e instrução de tela a partir do
tipo de ocorrência, do modo e do horário. É a camada que NUNCA depende da IA — se
os agentes falharem, este módulo garante o encaminhamento correto.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from .config import CANAIS, HORARIO_COMERCIAL
from .models import Gravidade, InstrucaoTotem, Modo, TipoOcorrencia

# Fuso de Teresina (sem horário de verão): UTC-3.
FUSO_PI = timezone(timedelta(hours=-3))


def _em_horario_comercial(agora: datetime) -> bool:
    if agora.weekday() not in HORARIO_COMERCIAL["dias"]:
        return False
    return any(ini <= agora.hour < fim for ini, fim in HORARIO_COMERCIAL["janelas"])


def rotear(
    tipo: TipoOcorrencia,
    modo: Modo,
    *,
    emergencia: bool = False,
    agora: datetime | None = None,
) -> dict:
    """Retorna {canal_roteado, fallback, gravidade, instrucao}."""
    agora = agora or datetime.now(FUSO_PI)
    comercial = _em_horario_comercial(agora)
    discreto = modo == Modo.discreto

    if tipo == TipoOcorrencia.seguranca:
        canal, fallback = "csv", "pm_190"
        gravidade = Gravidade.risco_imediato
        msg = "Pedido de segurança enviado. Mantenha a calma, ajuda a caminho."

    elif tipo == TipoOcorrencia.mulher:
        # Sempre discreto nesta trilha.
        discreto = True
        if comercial:
            canal, fallback = "sala_lilas", "central_180"
        else:
            canal, fallback = "central_180", "pm_190"
        gravidade = Gravidade.risco_potencial
        msg = "Recebido. Você está sendo encaminhada com sigilo."

    elif tipo == TipoOcorrencia.saude:
        if emergencia:
            canal, fallback = "samu_192", "csv"
            gravidade = Gravidade.risco_imediato
            msg = "Emergência de saúde acionada. Socorro a caminho (SAMU 192)."
        else:
            canal = "sapsi" if comercial else "ouvidoria"
            fallback = "ouvidoria"
            gravidade = Gravidade.orientacao
            msg = "Seu pedido de apoio foi registrado. A equipe entrará em contato."

    else:  # ouvidoria
        canal, fallback = "ouvidoria", "ouvidoria"
        gravidade = Gravidade.orientacao
        msg = "Manifestação registrada. Use o Fala.BR para o registro formal."

    instrucao = InstrucaoTotem(
        mensagem_tela="Seu pedido foi enviado. Aguarde atendimento." if discreto else msg,
        feedback_sonoro=not discreto,
        tela_neutra=discreto,
    )
    return {
        "canal_roteado": canal,
        "fallback": fallback,
        "gravidade": gravidade,
        "instrucao": instrucao,
        "horario_comercial": comercial,
    }
