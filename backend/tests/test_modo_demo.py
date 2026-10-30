"""#14: no modo demo nenhum caminho chega a provedor real e o relato não é persistido."""
import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, notifier
from app.main import app

RELATO = "RELATO-SECRETO-4711 homem armado no corredor do bloco 7"


class _Explode(notifier.NotificationProvider):
    async def enviar(self, *a, **k):  # pragma: no cover — não deve ser chamado
        raise AssertionError("provedor real acionado no modo demo")


@pytest.fixture
def demo(tmp_path, monkeypatch):
    caminho = tmp_path / "demo.db"
    monkeypatch.setattr("app.config.DB_PATH", str(caminho))
    monkeypatch.setattr("app.db.DB_PATH", str(caminho))
    monkeypatch.setattr("app.db._conn", None)
    # Configuração "perigosa" de propósito: provedores reais ligados e PSTN ligado.
    monkeypatch.setattr("app.notifier.NOTIF_PROVIDER", "twilio")
    monkeypatch.setattr("app.notifier.ALERTA_PSTN_ENABLED", True)
    monkeypatch.setattr("app.notifier.DEMO", True)
    monkeypatch.setattr("app.main.DEMO", True)
    for nome in ("WebhookProvider", "TelegramProvider", "TwilioProvider", "SimcomProvider"):
        monkeypatch.setattr(f"app.notifier.{nome}", _Explode)
    db.init_db()
    return caminho


def _evento(**extra) -> dict:
    return {"evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-DEMO", "modo": "normal",
            "tipo_ocorrencia": "seguranca", "origem_acionamento": "touch", **extra}


def test_provedor_e_sempre_log(demo):
    assert isinstance(notifier._provider(), notifier.LogProvider)


def test_evento_e_panico_nao_chegam_a_provedor_real(demo):
    with TestClient(app) as c:
        r = c.post("/api/v1/eventos", json=_evento())
        assert r.status_code == 201
        p = c.post("/api/v1/panico", json={"evento_id": str(uuid.uuid4()),
                                           "totem_id": "TOTEM-DEMO", "modo": "normal"})
        assert p.status_code == 201
        cham = c.get(f"/api/v1/chamados/{r.json()['chamado_id']}").json()
        assert cham["notificacoes"] and all(n["provider"] == "log" for n in cham["notificacoes"])
        esc = c.post(f"/api/v1/chamados/{r.json()['chamado_id']}/escalonar",
                     json={"canal": "pm_190"})
        assert esc.status_code in (200, 400, 404, 422)  # qualquer desfecho, sem provedor real


def test_relato_nao_e_persistido(demo):
    with TestClient(app) as c:
        c.post("/api/v1/eventos", json=_evento(texto_livre=RELATO))
        c.post("/api/v1/triagem", json={"texto": RELATO, "modo": "normal"})
    con = sqlite3.connect(demo)
    dump = "\n".join(con.iterdump())
    assert "RELATO-SECRETO-4711" not in dump
    assert "homem armado" not in dump


def test_aviso_de_demo_visivel(demo):
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
        assert r.headers.get("X-POTO-Demo") == "1"
        assert r.json()["demo"] is True
