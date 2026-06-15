"""Testes do roteador determinístico e da heurística de triagem."""

from datetime import datetime

from app.models import Gravidade, Modo, TipoOcorrencia
from app.router_engine import FUSO_PI, rotear


def _terca(hora: int) -> datetime:
    # 2026-06-16 é uma terça-feira.
    return datetime(2026, 6, 16, hora, 0, tzinfo=FUSO_PI)


def test_seguranca_sempre_csv():
    r = rotear(TipoOcorrencia.seguranca, Modo.normal, agora=_terca(3))
    assert r["canal_roteado"] == "csv"
    assert r["fallback"] == "pm_190"
    assert r["gravidade"] == Gravidade.risco_imediato


def test_mulher_forca_modo_discreto():
    r = rotear(TipoOcorrencia.mulher, Modo.normal, agora=_terca(10))
    assert r["canal_roteado"] == "sala_lilas"
    assert r["instrucao"].tela_neutra is True
    assert r["instrucao"].feedback_sonoro is False


def test_mulher_fora_do_horario_vai_para_rede_externa():
    r = rotear(TipoOcorrencia.mulher, Modo.normal, agora=_terca(22))
    assert r["canal_roteado"] == "central_180"


def test_saude_emergencia_vai_samu():
    r = rotear(TipoOcorrencia.saude, Modo.normal, emergencia=True, agora=_terca(10))
    assert r["canal_roteado"] == "samu_192"
    assert r["gravidade"] == Gravidade.risco_imediato


def test_saude_nao_emergencial_comercial_vai_sapsi():
    r = rotear(TipoOcorrencia.saude, Modo.normal, agora=_terca(10))
    assert r["canal_roteado"] == "sapsi"
    assert r["gravidade"] == Gravidade.orientacao


def test_heuristica_detecta_sinal_critico():
    from app.agents.graph import _heuristica

    out = _heuristica("estou pensando em suicídio", Modo.normal)
    assert out["escalonar_humano"] is True
    assert out["gravidade"] == Gravidade.risco_imediato.value
