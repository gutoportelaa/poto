"""Canal GSM/2G real via módulo SIMCom A7670SA (AT sobre serial).

Alternativa ao Twilio para a perna de alerta PSTN: com um SIM real o totem disca
de verdade a partir de número próprio — sem número virtual. O A7670SA **não tem
VoLTE**, então a voz só sai por fallback 2G (`AT+CNMP=13`); SMS sai em LTE ou GSM.

Design testável: a conversa AT roda sobre uma abstração `ATLink` (write/readline
com timeout). Em produção é `SerialLink` (pyserial, importado preguiçosamente, só
quando o provider é usado); nos testes é um link falso com respostas roteirizadas.
Nada aqui bloqueia o event loop — o notifier chama via `asyncio.to_thread`.

Segurança de discagem: o destino vem de `contato_canal` (respeita
POTO_CONTACT_OVERRIDE). Em testes de bancada, aponte o override para o SEU número
para não discar 190/192/193/180 de verdade.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from typing import Protocol

from .config import (
    SIMCOM_AT_TIMEOUT,
    SIMCOM_AUDIO_CMD,
    SIMCOM_BAUD,
    SIMCOM_CALL_SEG,
    SIMCOM_FORCE_GSM,
    SIMCOM_MODE,
    SIMCOM_PORT,
    SIMCOM_SPK_DEVICE,
)

log = logging.getLogger("poto.simcom")

# Terminadores que encerram a resposta de um comando AT.
_FINAL_OK = ("OK",)
_FINAL_ERR = ("ERROR", "+CME ERROR", "+CMS ERROR", "NO CARRIER", "NO DIALTONE", "BUSY")
CTRL_Z = "\x1a"

# Serializa o acesso ao modem: há UM módulo, mas o broadcast de pânico dispara
# vários canais em paralelo (asyncio.gather). Sem isto, comandos AT se cruzariam
# na mesma porta serial. Com o lock, as ligações saem uma de cada vez.
_lock = threading.Lock()


class ATLink(Protocol):
    """Transporte de linha para o diálogo AT (implementado por serial ou fake)."""

    def write(self, data: str) -> None: ...
    def readline(self, timeout: float) -> str: ...
    def close(self) -> None: ...


class SerialLink:
    """`ATLink` real sobre pyserial. Importa pyserial só aqui (dep opcional)."""

    def __init__(self, port: str, baud: int) -> None:
        import serial  # type: ignore  # dep opcional (extra "simcom")

        self._ser = serial.Serial(port, baud, timeout=0.5)

    def write(self, data: str) -> None:
        self._ser.write(data.encode("utf-8", "ignore"))
        self._ser.flush()

    def readline(self, timeout: float) -> str:
        self._ser.timeout = timeout
        raw = self._ser.readline()
        return raw.decode("utf-8", "ignore").strip()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001 — fechar é best-effort
            pass


class ATError(RuntimeError):
    """Comando AT devolveu ERROR/NO CARRIER/etc. ou estourou o timeout."""


class ATModem:
    """Diálogo AT de alto nível sobre um `ATLink`."""

    def __init__(self, link: ATLink, at_timeout: float = SIMCOM_AT_TIMEOUT) -> None:
        self.link = link
        self.at_timeout = at_timeout

    def cmd(self, command: str, *, timeout: float | None = None,
            final_ok: tuple[str, ...] = _FINAL_OK) -> list[str]:
        """Envia `command` e lê linhas até um terminador. Retorna as linhas de
        resposta (sem o terminador). Levanta ATError em falha/timeout."""
        to = self.at_timeout if timeout is None else timeout
        self.link.write(command + "\r\n")
        linhas: list[str] = []
        prazo = time.monotonic() + to
        while time.monotonic() < prazo:
            linha = self.link.readline(min(1.0, to))
            if not linha:
                continue
            if linha == command:  # eco do comando (ATE1) — ignora
                continue
            if linha in final_ok:
                return linhas
            if any(linha.startswith(e) for e in _FINAL_ERR):
                raise ATError(f"{command!r} → {linha}")
            linhas.append(linha)
        raise ATError(f"{command!r} → timeout ({to}s)")

    def enviar_sms(self, numero: str, texto: str) -> str:
        """Envia SMS em modo texto. Retorna a referência (+CMGS: n)."""
        self.cmd("AT+CMGF=1")  # modo texto
        # AT+CMGS abre um prompt ">" e só então recebe o corpo + Ctrl-Z.
        self.link.write(f'AT+CMGS="{numero}"\r')
        prazo = time.monotonic() + 5.0
        while time.monotonic() < prazo:  # espera o prompt ">"
            linha = self.link.readline(1.0)
            if ">" in linha or not linha:
                break
        self.link.write(texto + CTRL_Z)
        resp = self.cmd("", timeout=max(self.at_timeout, 15.0))  # aguarda +CMGS/OK
        ref = next((ln for ln in resp if ln.startswith("+CMGS")), "+CMGS: ?")
        return ref


def _so_discavel(numero: str) -> str:
    """Mantém apenas dígitos e um '+' inicial (ATD aceita curto e E.164)."""
    n = numero.strip()
    mais = n.startswith("+")
    d = re.sub(r"\D", "", n)
    return ("+" + d) if mais else d


def _tocar_wav(caminho: str) -> None:
    """Toca o WAV da locução dentro da ligação, se POTO_SIMCOM_AUDIO_CMD estiver
    configurado. Best-effort: falha de áudio não derruba o alerta (a ligação
    ainda chama). O comando é um template com {wav}."""
    cmd = SIMCOM_AUDIO_CMD.format(wav=caminho)
    try:
        subprocess.run(cmd, shell=True, capture_output=True, timeout=SIMCOM_CALL_SEG + 5)
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("Áudio da ligação falhou (%s) — segue como ring.", e)


def _sessao(numero: str, mensagem: str, wav: str | None,
            *, link: ATLink | None = None) -> str:
    """Abre o modem, executa voz e/ou SMS conforme SIMCOM_MODE e devolve um
    resumo textual. Roda inteiro sob `_lock` (um modem por vez). Síncrono —
    o chamador deve invocar via asyncio.to_thread."""
    proprio = link is None
    if link is None:
        link = SerialLink(SIMCOM_PORT, SIMCOM_BAUD)
    partes: list[str] = []
    try:
        with _lock:
            m = ATModem(link)
            m.cmd("AT")  # sanidade
            m.cmd("ATE0")  # desliga eco p/ parser previsível
            if SIMCOM_FORCE_GSM and SIMCOM_MODE in ("voice", "both"):
                # 2 = auto, 13 = GSM-only, 38 = LTE-only. Voz exige 2G (sem VoLTE).
                try:
                    m.cmd("AT+CNMP=13")
                except ATError as e:
                    log.warning("AT+CNMP=13 (force GSM) falhou: %s", e)

            if SIMCOM_MODE in ("sms", "both"):
                try:
                    ref = m.enviar_sms(numero, mensagem)
                    partes.append(f"sms {ref}")
                except ATError as e:
                    partes.append(f"sms falhou ({e})")

            if SIMCOM_MODE in ("voice", "both"):
                if SIMCOM_SPK_DEVICE:
                    try:
                        m.cmd(f"AT+CSDVC={SIMCOM_SPK_DEVICE}")
                    except ATError as e:
                        log.warning("AT+CSDVC falhou: %s", e)
                m.cmd(f"ATD{_so_discavel(numero)};")  # ';' = chamada de voz
                if wav and SIMCOM_AUDIO_CMD:
                    _tocar_wav(wav)  # toca a locução; consome parte do tempo no ar
                else:
                    time.sleep(SIMCOM_CALL_SEG)
                try:
                    m.cmd("AT+CHUP")  # desliga
                except ATError:
                    pass
                partes.append("voz ok")
        return "; ".join(partes) or "nada a fazer (modo desconhecido)"
    finally:
        if proprio:
            link.close()


def executar(numero: str, mensagem: str, wav: str | None = None,
             *, link: ATLink | None = None) -> tuple[bool, str]:
    """Ponto de entrada síncrono usado pelo provider. Nunca levanta — devolve
    (ok, detalhe). `link` injetável para testes."""
    alvo = _so_discavel(numero)
    if not alvo:
        return False, f"destino inválido para discagem: {numero!r}"
    try:
        detalhe = _sessao(numero, mensagem, wav, link=link)
        ok = "falhou" not in detalhe and "nada a fazer" not in detalhe
        return ok, f"simcom {SIMCOM_MODE}: {detalhe}"
    except ATError as e:
        return False, f"simcom AT: {e}"
    except Exception as e:  # noqa: BLE001 — inclui falta de pyserial / porta ausente
        return False, f"simcom erro: {e}"


def status() -> dict:
    return {
        "porta": SIMCOM_PORT,
        "baud": SIMCOM_BAUD,
        "modo": SIMCOM_MODE,
        "force_gsm": SIMCOM_FORCE_GSM,
        "audio_locucao": bool(SIMCOM_AUDIO_CMD),
        "call_seg": SIMCOM_CALL_SEG,
    }
