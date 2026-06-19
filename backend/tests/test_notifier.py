"""Testes da camada de notificação."""

import pytest

from app import db, notifier
from app.config import CANAIS, contato_canal
from app.models import Modo, TipoOcorrencia
from app.router_engine import rotear


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db.DB_PATH", str(db_path))
    monkeypatch.setattr("app.db._conn", None)
    db.init_db()
    yield


def _chamado(tipo=TipoOcorrencia.seguranca):
    routing = rotear(tipo, Modo.normal)
    evento = {
        "evento_id": "evt-test-001",
        "totem_id": "TOTEM-TEST",
        "tipo_ocorrencia": tipo.value,
        "modo": "normal",
        "origem_acionamento": "touch",
    }
    return db.create_chamado(evento, routing, None)


def test_montar_mensagem_sem_dados_sensiveis():
    c = _chamado()
    msg = notifier.montar_mensagem(c, "csv")
    assert c["chamado_id"] in msg
    assert "Segurança" in msg
    assert "IMEDIATO" in msg
    assert "TOTEM-TEST" in msg


@pytest.mark.asyncio
async def test_notificar_chamado_atualiza_status(monkeypatch):
    monkeypatch.setattr("app.config.NOTIF_PROVIDER", "log")
    c = _chamado()
    ok, atualizado = await notifier.notificar_chamado(c)
    assert ok is True
    assert atualizado["status"] == "notificado"
    notifs = db.list_notificacoes(c["chamado_id"])
    assert len(notifs) == 1
    assert notifs[0]["sucesso"] == 1


@pytest.mark.asyncio
async def test_contato_override(monkeypatch):
    monkeypatch.setattr("app.config.CONTACT_OVERRIDE", "5586981804692")
    assert contato_canal("csv") == "5586981804692"
    assert contato_canal("sala_lilas") == "5586981804692"


def test_canais_carregados_do_config():
    assert "csv" in CANAIS
    assert CANAIS["csv"]["nome"] == "CSV / PREUNI"


def test_format_e164():
    assert notifier._format_e164("5586981804692") == "+5586981804692"
    assert notifier._format_e164("+5586981804692") == "+5586981804692"
    assert notifier._format_e164("ouvidoria@ufpi.br") is None


@pytest.mark.asyncio
async def test_twilio_voice(monkeypatch):
    monkeypatch.setattr("app.config.NOTIF_PROVIDER", "twilio")
    monkeypatch.setattr("app.config.TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr("app.config.TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr("app.config.TWILIO_FROM", "+14179224849")
    monkeypatch.setattr("app.config.TWILIO_MODE", "voice")
    monkeypatch.setattr("app.notifier.NOTIF_PROVIDER", "twilio")
    monkeypatch.setattr("app.notifier.TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setattr("app.notifier.TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr("app.notifier.TWILIO_FROM", "+14179224849")
    monkeypatch.setattr("app.notifier.TWILIO_MODE", "voice")

    calls: list[dict] = []

    class FakeResp:
        status_code = 201

        def raise_for_status(self): ...

        def json(self):
            return {"sid": "CA123"}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, auth=None, data=None):
            calls.append({"url": url, "data": data, "auth": auth})
            return FakeResp()

    monkeypatch.setattr("app.notifier.httpx.AsyncClient", lambda **k: FakeClient())

    ok, det = await notifier.TwilioProvider().enviar(
        "5586981804692", "POTO ALERTA teste", {}
    )
    assert ok is True
    assert "CA123" in (det or "")
    assert calls[0]["data"]["To"] == "+5586981804692"
    assert "<Say" in calls[0]["data"]["Twiml"]
