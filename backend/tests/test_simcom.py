"""Testes do canal SIMCom A7670SA — diálogo AT sobre um link falso (sem hardware).

Cobrem os três modos (voice/sms/both), o force-GSM da voz, o handshake de SMS
(prompt ">" + Ctrl-Z) e o caminho de erro (NO CARRIER). Nada abre porta serial:
o `FakeLink` injeta as respostas do modem.
"""

from __future__ import annotations

import pytest

from app import simcom
from app.simcom import CTRL_Z


class FakeLink:
    """`ATLink` roteirizado. Emite 'OK' por padrão; respostas específicas por
    comando via `responses`. Modela o prompt '>' e o eco do +CMGS do SMS."""

    def __init__(self, responses: dict[str, list[str]] | None = None) -> None:
        self.responses = responses or {}
        self.outbox: list[str] = []
        self.written: list[str] = []

    def write(self, data: str) -> None:
        self.written.append(data)
        cmd = data.strip()
        if cmd.startswith('AT+CMGS="'):
            self.outbox.append(">")  # prompt do corpo do SMS
            return
        if data.endswith(CTRL_Z):
            self.outbox.extend(["+CMGS: 42", "OK"])  # SMS aceito
            return
        if cmd == "":  # comando vazio: só drena a resposta pendente
            return
        self.outbox.extend(self.responses.get(cmd, ["OK"]))

    def readline(self, timeout: float) -> str:
        return self.outbox.pop(0) if self.outbox else ""

    def close(self) -> None:  # noqa: D401
        pass


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """Zera o tempo no ar para os testes não dormirem."""
    monkeypatch.setattr(simcom, "SIMCOM_CALL_SEG", 0)
    monkeypatch.setattr(simcom, "SIMCOM_AUDIO_CMD", "")
    monkeypatch.setattr(simcom, "SIMCOM_SPK_DEVICE", "")


def test_discavel_normaliza():
    assert simcom._so_discavel("+55 (86) 98180-4692") == "+5586981804692"
    assert simcom._so_discavel("190") == "190"
    assert simcom._so_discavel("") == ""


def test_voz_forca_gsm_e_desliga(monkeypatch):
    monkeypatch.setattr(simcom, "SIMCOM_MODE", "voice")
    monkeypatch.setattr(simcom, "SIMCOM_FORCE_GSM", True)
    link = FakeLink()
    ok, detalhe = simcom.executar("+5586981804692", "ignorado no modo voz", link=link)
    assert ok, detalhe
    assert "voz ok" in detalhe
    escritos = "".join(link.written)
    assert "AT+CNMP=13" in escritos  # forçou 2G p/ CSFB
    assert "ATD+5586981804692;" in escritos  # discou voz (';')
    assert "AT+CHUP" in escritos  # desligou


def test_sms_handshake(monkeypatch):
    monkeypatch.setattr(simcom, "SIMCOM_MODE", "sms")
    link = FakeLink()
    ok, detalhe = simcom.executar("+5586981804692", "POTO ALERTA. Protocolo 123.", link=link)
    assert ok, detalhe
    assert "sms +CMGS: 42" in detalhe
    escritos = "".join(link.written)
    assert "AT+CMGF=1" in escritos  # modo texto
    assert 'AT+CMGS="+5586981804692"' in escritos
    assert escritos.endswith(CTRL_Z) or CTRL_Z in escritos  # corpo terminou com Ctrl-Z
    # No modo só-SMS não força GSM nem disca.
    assert "AT+CNMP=13" not in escritos
    assert "ATD" not in escritos


def test_both_faz_sms_e_voz(monkeypatch):
    monkeypatch.setattr(simcom, "SIMCOM_MODE", "both")
    link = FakeLink()
    ok, detalhe = simcom.executar("+5586981804692", "alerta", link=link)
    assert ok, detalhe
    assert "sms" in detalhe and "voz ok" in detalhe


def test_voz_no_carrier_falha(monkeypatch):
    monkeypatch.setattr(simcom, "SIMCOM_MODE", "voice")
    link = FakeLink(responses={"ATD+5586981804692;": ["NO CARRIER"]})
    ok, detalhe = simcom.executar("+5586981804692", "alerta", link=link)
    assert not ok
    assert "NO CARRIER" in detalhe


def test_destino_invalido():
    ok, detalhe = simcom.executar("", "alerta", link=FakeLink())
    assert not ok
    assert "inválido" in detalhe


def test_status_reporta_config():
    st = simcom.status()
    assert set(st) >= {"porta", "modo", "force_gsm", "audio_locucao"}
