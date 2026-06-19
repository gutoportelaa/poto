"""Testes dos critérios de aceite do protótipo (relatorio-prototipo.md §8)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import db, notifier
from app.agents.graph import _heuristica
from app.models import Gravidade, Modo, TipoOcorrencia
from app.router_engine import FUSO_PI, rotear


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    db_path = tmp_path / "accept.db"
    monkeypatch.setattr("app.config.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db._conn", None)
    monkeypatch.setattr("app.config.NOTIF_PROVIDER", "log")
    db.init_db()
    yield


def _terca(hora: int) -> datetime:
    return datetime(2026, 6, 16, hora, 0, tzinfo=FUSO_PI)


def _evento(tipo: TipoOcorrencia, modo=Modo.normal, texto=None):
    return {
        "evento_id": str(uuid.uuid4()),
        "totem_id": "TOTEM-CCS-01",
        "tipo_ocorrencia": tipo.value,
        "modo": modo.value,
        "origem_acionamento": "touch",
        "texto_livre": texto,
    }


# Critério 2 — 4/4 trilhas roteiam corretamente
def test_aceite_trilhas():
    assert rotear(TipoOcorrencia.seguranca, Modo.normal, agora=_terca(3))["canal_roteado"] == "csv"
    assert rotear(TipoOcorrencia.mulher, Modo.normal, agora=_terca(10))["canal_roteado"] == "sala_lilas"
    assert rotear(TipoOcorrencia.saude, Modo.normal, agora=_terca(10))["canal_roteado"] == "sapsi"
    assert rotear(TipoOcorrencia.ouvidoria, Modo.normal)["canal_roteado"] == "ouvidoria"


# Critério 4 — modo discreto
def test_aceite_modo_discreto():
    r = rotear(TipoOcorrencia.mulher, Modo.normal, agora=_terca(10))
    assert r["instrucao"].tela_neutra is True
    assert r["instrucao"].feedback_sonoro is False


# Critério 5 — sinal crítico escala
def test_aceite_sinal_critico():
    out = _heuristica("estou pensando em suicídio", Modo.normal)
    assert out["escalonar_humano"] is True
    assert out["gravidade"] == Gravidade.risco_imediato.value


# Critério 6 — idempotência
def test_aceite_idempotencia():
    ev = _evento(TipoOcorrencia.seguranca)
    routing = rotear(TipoOcorrencia.seguranca, Modo.normal)
    c1 = db.create_chamado(ev, routing, None)
    c2 = db.create_chamado(ev, routing, None)
    assert c1["chamado_id"] == c2["chamado_id"]
    assert c2.get("_duplicado") is True


# Critério 7 — notificação muda status
@pytest.mark.asyncio
async def test_aceite_notificacao_status():
    ev = _evento(TipoOcorrencia.seguranca)
    routing = rotear(TipoOcorrencia.seguranca, Modo.normal)
    c = db.create_chamado(ev, routing, None)
    assert c["status"] == "roteado"
    _, atualizado = await notifier.notificar_chamado(c)
    assert atualizado["status"] == "notificado"


# SLA — escalonamento após expiração
def test_aceite_sla_expirado(monkeypatch):
    ev = _evento(TipoOcorrencia.seguranca)
    routing = rotear(TipoOcorrencia.seguranca, Modo.normal)
    c = db.create_chamado(ev, routing, None)
    db.update_chamado(c["chamado_id"], status="notificado")
    antigo = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with db._lock:
        db.conn().execute(
            "UPDATE chamados SET updated_at = ? WHERE chamado_id = ?",
            (antigo, c["chamado_id"]),
        )
        db.conn().commit()
    expirados = db.chamados_sla_expirado()
    assert any(x["chamado_id"] == c["chamado_id"] for x in expirados)
