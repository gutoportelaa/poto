"""Agente de classificação inicial para Boletins de Ocorrência (B.O.)."""

from agents.bo_facil.core.states import BOState
from agents.bo_facil.workflow import bo_facil_agent

__all__ = ["bo_facil_agent", "BOState"]
