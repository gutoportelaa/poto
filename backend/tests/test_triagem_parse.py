"""Robustez da triagem para modelos nano: parse tolerante, normalização de
rótulos e o caminho de `classificar_triagem` com um LLM falso (sem Ollama)."""

from __future__ import annotations

from app.agents import graph
from app.models import Gravidade, TipoOcorrencia


class _FakeLLM:
    def __init__(self, resposta: str) -> None:
        self.resposta = resposta

    def invoke(self, _prompt):  # noqa: ANN001
        return type("R", (), {"content": self.resposta})()


def test_parse_json_tolerante():
    assert graph._parse_json('{"tipo":"saude"}') == {"tipo": "saude"}
    # cerca markdown + texto ao redor
    assert graph._parse_json('```json\n{"tipo":"mulher"}\n```') == {"tipo": "mulher"}
    assert graph._parse_json('claro: {"tipo":"seguranca"} pronto') == {"tipo": "seguranca"}
    # aspas simples de modelo pequeno
    assert graph._parse_json("{'tipo': 'saude'}") == {"tipo": "saude"}
    assert graph._parse_json("sem json aqui") is None
    assert graph._parse_json("") is None


def test_normalizacao_rotulos():
    tipos = TipoOcorrencia._value2member_map_
    grav = Gravidade._value2member_map_
    assert graph._norm("segurança", graph._TIPO_ALIAS, tipos) == "seguranca"
    assert graph._norm("SAÚDE", graph._TIPO_ALIAS, tipos) == "saude"
    assert graph._norm("assédio", graph._TIPO_ALIAS, tipos) == "mulher"
    assert graph._norm("reclamação", graph._TIPO_ALIAS, tipos) == "ouvidoria"
    assert graph._norm("imediato", graph._GRAV_ALIAS, grav) == "risco_imediato"
    assert graph._norm("média", graph._GRAV_ALIAS, grav) == "risco_potencial"
    assert graph._norm("baixa", graph._GRAV_ALIAS, grav) == "orientacao"
    assert graph._norm("xpto", graph._TIPO_ALIAS, tipos) is None
    assert graph._norm(None, graph._TIPO_ALIAS, tipos) is None


def _classificar_com(monkeypatch, resposta: str):
    monkeypatch.setattr(graph, "_chat", lambda *a, **k: _FakeLLM(resposta))
    return graph.classificar_triagem("mensagem de teste")


def test_classificar_json_limpo(monkeypatch):
    r = _classificar_com(monkeypatch, '{"tipo":"saude","gravidade":"risco_imediato","confianca":0.9}')
    assert r == {"tipo": "saude", "gravidade": "risco_imediato", "confianca": 0.9}


def test_classificar_com_acentos_e_cerca(monkeypatch):
    r = _classificar_com(monkeypatch, '```json\n{"tipo":"Segurança","gravidade":"Imediato"}\n```')
    assert r["tipo"] == "seguranca"
    assert r["gravidade"] == "risco_imediato"
    assert r["confianca"] == 0.6  # default quando ausente


def test_classificar_tipo_invalido_vira_none(monkeypatch):
    assert _classificar_com(monkeypatch, '{"tipo":"banana"}') is None


def test_classificar_sem_gravidade(monkeypatch):
    r = _classificar_com(monkeypatch, '{"tipo":"ouvidoria","confianca":0.5}')
    assert r == {"tipo": "ouvidoria", "confianca": 0.5}
