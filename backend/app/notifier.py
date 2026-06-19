"""Camada de notificação externa — adapters plugáveis (log, webhook, telegram).

Payload mínimo (LGPD): protocolo, tipo, gravidade, totem — sem relato detalhado.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Protocol

import httpx

from . import db
from .config import (
    CANAIS,
    CONTACT_OVERRIDE,
    NOTIF_PROVIDER,
    NOTIF_WEBHOOK_TOKEN,
    NOTIF_WEBHOOK_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM,
    TWILIO_MODE,
    contato_canal,
)

log = logging.getLogger("poto.notifier")

TIPO_NOME = {
    "seguranca": "Segurança",
    "mulher": "Atendimento à Mulher",
    "saude": "Saúde",
    "ouvidoria": "Ouvidoria",
}
GRAV_NOME = {
    "risco_imediato": "IMEDIATO",
    "risco_potencial": "POTENCIAL",
    "orientacao": "Orientação",
}


class NotificationProvider(Protocol):
    async def enviar(self, destino: str, mensagem: str, meta: dict) -> tuple[bool, str | None]: ...


def montar_mensagem(chamado: dict, canal: str, *, escalonamento: bool = False) -> str:
    info = CANAIS.get(canal, {"nome": canal})
    prefixo = "ESCALONADO" if escalonamento else "ALERTA"
    tipo = TIPO_NOME.get(chamado.get("tipo_ocorrencia", ""), chamado.get("tipo_ocorrencia"))
    grav = GRAV_NOME.get(chamado.get("gravidade", ""), chamado.get("gravidade"))
    return (
        f"POTO {prefixo}. Protocolo {chamado['chamado_id']}. "
        f"Tipo {tipo}. Gravidade {grav}. Totem {chamado.get('totem_id', '?')}. "
        f"Canal {info['nome']}."
    )


def _format_e164(destino: str) -> str | None:
    """Normaliza número para E.164 (+5586…). Retorna None se não for telefone."""
    if "@" in destino:
        return None
    digits = re.sub(r"\D", "", destino)
    if len(digits) < 10:
        return None
    return f"+{digits}"


class LogProvider:
    async def enviar(self, destino: str, mensagem: str, meta: dict) -> tuple[bool, str | None]:
        log.info("NOTIF → %s | %s", destino, mensagem.replace("\n", " | "))
        return True, "registrado em log"


class WebhookProvider:
    async def enviar(self, destino: str, mensagem: str, meta: dict) -> tuple[bool, str | None]:
        if not NOTIF_WEBHOOK_URL:
            return False, "POTO_NOTIF_WEBHOOK_URL não configurada"
        headers = {"content-type": "application/json"}
        if NOTIF_WEBHOOK_TOKEN:
            headers["apikey"] = NOTIF_WEBHOOK_TOKEN
        payload = {
            "number": destino,
            "text": mensagem,
            "meta": meta,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(NOTIF_WEBHOOK_URL, json=payload, headers=headers)
                r.raise_for_status()
            return True, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)


class TelegramProvider:
    async def enviar(self, destino: str, mensagem: str, meta: dict) -> tuple[bool, str | None]:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False, "POTO_TELEGRAM_BOT_TOKEN ou POTO_TELEGRAM_CHAT_ID ausente"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    url,
                    json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem},
                )
                r.raise_for_status()
            return True, "telegram ok"
        except Exception as e:
            return False, str(e)


class TwilioProvider:
    """Alerta por voz (TwiML Say) ou SMS via API REST Twilio."""

    async def enviar(self, destino: str, mensagem: str, meta: dict) -> tuple[bool, str | None]:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM:
            return False, "Credenciais Twilio incompletas (SID, TOKEN ou FROM)"
        to = _format_e164(destino)
        if not to:
            return False, f"Destino não é telefone E.164: {destino}"
        base = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"
        auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if TWILIO_MODE == "sms":
                    r = await client.post(
                        f"{base}/Messages.json",
                        auth=auth,
                        data={"To": to, "From": TWILIO_FROM, "Body": mensagem},
                    )
                else:
                    fala = html.escape(mensagem)
                    twiml = (
                        f'<?xml version="1.0" encoding="UTF-8"?>'
                        f"<Response><Say language=\"pt-BR\">{fala}</Say></Response>"
                    )
                    r = await client.post(
                        f"{base}/Calls.json",
                        auth=auth,
                        data={"To": to, "From": TWILIO_FROM, "Twiml": twiml},
                    )
                r.raise_for_status()
                data = r.json()
                sid = data.get("sid", "?")
            modo = "sms" if TWILIO_MODE == "sms" else "voice"
            return True, f"twilio {modo} sid={sid}"
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response else ""
            return False, f"HTTP {e.response.status_code}: {body}"
        except Exception as e:
            return False, str(e)


def _provider() -> NotificationProvider:
    if NOTIF_PROVIDER == "webhook":
        return WebhookProvider()
    if NOTIF_PROVIDER == "telegram":
        return TelegramProvider()
    if NOTIF_PROVIDER == "twilio":
        return TwilioProvider()
    return LogProvider()


async def enviar_para_canal(
    chamado: dict,
    canal: str,
    *,
    escalonamento: bool = False,
) -> bool:
    destino = contato_canal(canal)
    mensagem = montar_mensagem(chamado, canal, escalonamento=escalonamento)
    meta = {
        "chamado_id": chamado["chamado_id"],
        "canal": canal,
        "destino": destino,
        "escalonamento": escalonamento,
    }
    prov = _provider()
    ok, detalhe = await prov.enviar(destino, mensagem, meta)
    db.add_notificacao(
        chamado["chamado_id"],
        canal,
        destino,
        NOTIF_PROVIDER,
        ok,
        mensagem,
        detalhe=detalhe,
        escalonamento=escalonamento,
    )
    return ok


async def notificar_chamado(chamado: dict) -> tuple[bool, dict]:
    """Notifica o canal primário e atualiza o status do chamado."""
    ok = await enviar_para_canal(chamado, chamado["canal_roteado"])
    novo_status = "notificado" if ok else "falha_notificacao"
    atualizado = db.update_chamado(chamado["chamado_id"], status=novo_status)
    return ok, atualizado or chamado


async def escalonar_chamado(chamado: dict) -> dict | None:
    """Escalona para o canal fallback após SLA expirado."""
    fallback = chamado.get("fallback")
    if not fallback:
        return db.update_chamado(
            chamado["chamado_id"],
            status="escalonado",
            observacao="SLA expirado — sem canal fallback",
        )
    db.update_chamado(chamado["chamado_id"], status="escalonado")
    escalado = db.get_chamado(chamado["chamado_id"]) or chamado
    ok = await enviar_para_canal(escalado, fallback, escalonamento=True)
    status = "notificado" if ok else "falha_notificacao"
    return db.update_chamado(chamado["chamado_id"], status=status)


def status() -> dict:
    return {
        "provider": NOTIF_PROVIDER,
        "override": bool(CONTACT_OVERRIDE),
        "webhook_configurado": bool(NOTIF_WEBHOOK_URL),
        "telegram_configurado": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        "twilio_configurado": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM),
        "twilio_modo": TWILIO_MODE if NOTIF_PROVIDER == "twilio" else None,
    }
