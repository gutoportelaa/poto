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


def test_panico_broadcast_e_alerta_ativo():
    with TestClient(app) as client:
        ev = {"evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-CCS-01"}
        r = client.post("/api/v1/panico", json=ev)
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "alerta_ativo"
        assert body["gravidade"] == "risco_imediato"
        # broadcast aos canais internos padrão (csv, sala_lilas)
        assert {x["canal"] for x in body["resultados"]} == {"csv", "sala_lilas"}
        assert all(x["sucesso"] for x in body["resultados"])
        assert all(x["destino"] == "5586981804692" for x in body["resultados"])
        # autoridades do estado oferecidas p/ escalonamento manual
        canais_estado = {x["canal"] for x in body["escalonamento_disponivel"]}
        assert {"pm_190", "samu_192", "bombeiros_193", "central_180"} <= canais_estado

        chamado = client.get(f"/api/v1/chamados/{body['chamado_id']}").json()
        assert chamado["status"] == "alerta_ativo"
        assert len(chamado["notificacoes"]) == 2


def test_panico_idempotente():
    with TestClient(app) as client:
        evento_id = str(uuid.uuid4())
        ev = {"evento_id": evento_id, "totem_id": "TOTEM-CCS-01"}
        first = client.post("/api/v1/panico", json=ev).json()
        second = client.post("/api/v1/panico", json=ev)
        assert second.status_code == 201
        body = second.json()
        assert body["duplicado"] is True
        assert body["chamado_id"] == first["chamado_id"]
        # não redisparou: continua com 2 notificações do primeiro acionamento
        chamado = client.get(f"/api/v1/chamados/{first['chamado_id']}").json()
        assert len(chamado["notificacoes"]) == 2


def test_escalonamento_manual_mantem_alerta():
    with TestClient(app) as client:
        ev = {"evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-CCS-01"}
        cid = client.post("/api/v1/panico", json=ev).json()["chamado_id"]

        r = client.post(f"/api/v1/chamados/{cid}/escalonar", json={"canal": "samu_192"})
        assert r.status_code == 200
        assert r.json()["sucesso"] is True

        chamado = client.get(f"/api/v1/chamados/{cid}").json()
        assert chamado["status"] == "alerta_ativo"  # alerta segue ativo
        samu = [n for n in chamado["notificacoes"] if n["canal"] == "samu_192"]
        assert len(samu) == 1 and samu[0]["escalonamento"] == 1


def test_escalonamento_canal_invalido():
    with TestClient(app) as client:
        ev = {"evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-CCS-01"}
        cid = client.post("/api/v1/panico", json=ev).json()["chamado_id"]
        r = client.post(f"/api/v1/chamados/{cid}/escalonar", json={"canal": "inexistente"})
        assert r.status_code == 422


def test_escalonamento_chamado_inexistente():
    with TestClient(app) as client:
        r = client.post("/api/v1/chamados/CALL-9999-000001/escalonar", json={"canal": "samu_192"})
        assert r.status_code == 404


def test_auditoria_registra_estados_e_contatos():
    with TestClient(app) as client:
        ev = {"evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-CCS-01"}
        cid = client.post("/api/v1/panico", json=ev).json()["chamado_id"]
        client.post(f"/api/v1/chamados/{cid}/escalonar", json={"canal": "samu_192"})

        a = client.get(f"/api/v1/chamados/{cid}/auditoria").json()
        # destaque de emergência
        assert a["emergencia"] is True
        assert a["gravidade"] == "risco_imediato"
        # contatos acionados registrados (csv, sala_lilas, samu_192)
        assert a["total_contatos_acionados"] == 3
        canais = {c["canal"] for c in a["contatos_acionados"]}
        assert canais == {"csv", "sala_lilas", "samu_192"}
        # estados com duração; último em curso (alerta_ativo)
        assert a["estados"][-1]["para"] == "alerta_ativo"
        assert a["estados"][-1]["em_curso"] is True
        assert all("duracao_segundos" in e for e in a["estados"])
        # linha do tempo unificada e cronológica
        tipos = {x["tipo"] for x in a["linha_do_tempo"]}
        assert {"estado", "notificacao", "escalonamento"} <= tipos
        ts = [x["em"] for x in a["linha_do_tempo"]]
        assert ts == sorted(ts)
        assert a["tempo_total_segundos"] >= 0


def test_totens_agrega_heartbeat_e_atividade():
    with TestClient(app) as client:
        # totem com heartbeat → online + telemetria
        client.post("/api/v1/totens/TOTEM-CCS-01/heartbeat",
                    json={"online": True, "bateria": 87, "conectividade": "wifi"})
        # totem visto só em chamado → aparece offline, sem telemetria
        client.post("/api/v1/eventos", json={
            "evento_id": str(uuid.uuid4()), "totem_id": "TOTEM-RU-09",
            "tipo_ocorrencia": "ouvidoria", "modo": "normal",
        })
        totens = client.get("/api/v1/totens").json()
        por_id = {t["totem_id"]: t for t in totens}

        assert por_id["TOTEM-CCS-01"]["online"] is True
        assert por_id["TOTEM-CCS-01"]["bateria"] == 87
        assert por_id["TOTEM-CCS-01"]["conectividade"] == "wifi"
        assert por_id["TOTEM-CCS-01"]["visto_ha_segundos"] is not None

        assert por_id["TOTEM-RU-09"]["online"] is False
        assert por_id["TOTEM-RU-09"]["ultimo_heartbeat"] is None
        assert por_id["TOTEM-RU-09"]["chamados_total"] == 1


def test_totens_tamper_no_topo():
    with TestClient(app) as client:
        client.post("/api/v1/totens/TOTEM-A/heartbeat", json={"online": True})
        client.post("/api/v1/totens/TOTEM-Z/heartbeat", json={"online": True, "tamper": True})
        totens = client.get("/api/v1/totens").json()
        assert totens[0]["totem_id"] == "TOTEM-Z"  # violação ordenada no topo
        assert totens[0]["tamper"] is True


def test_detalhe_inclui_estados_e_emergencia():
    with TestClient(app) as client:
        ev = {
            "evento_id": str(uuid.uuid4()),
            "totem_id": "TOTEM-CCS-01",
            "tipo_ocorrencia": "seguranca",
            "modo": "normal",
        }
        cid = client.post("/api/v1/eventos", json=ev).json()["chamado_id"]
        c = client.get(f"/api/v1/chamados/{cid}").json()
        assert c["emergencia"] is True  # seguranca → risco_imediato
        assert isinstance(c["estados"], list) and len(c["estados"]) >= 1
        assert "tempo_total_segundos" in c
