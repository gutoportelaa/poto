"""Smoke test da integração evento → notificação."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    db_path = tmp_path / "smoke.db"
    monkeypatch.setattr("app.config.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db._conn", None)
    monkeypatch.setattr("app.config.NOTIF_PROVIDER", "log")
    monkeypatch.setattr("app.config.CONTACT_OVERRIDE", "5586981804692")
    db.init_db()
    yield


def test_post_evento_notifica_e_muda_status():
    with TestClient(app) as client:
        ev = {
            "evento_id": str(uuid.uuid4()),
            "totem_id": "TOTEM-CCS-01",
            "tipo_ocorrencia": "seguranca",
            "modo": "normal",
            "origem_acionamento": "touch",
        }
        r = client.post("/api/v1/eventos", json=ev)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "notificado"
        chamado = client.get(f"/api/v1/chamados/{body['chamado_id']}").json()
        assert chamado["status"] == "notificado"
        assert len(chamado["notificacoes"]) == 1
        assert chamado["notificacoes"][0]["destino"] == "5586981804692"


def test_health_inclui_notificacao():
    with TestClient(app) as client:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert "notificacao" in r.json()
