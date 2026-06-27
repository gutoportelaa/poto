"""Camada de notificação externa — adapters plugáveis (log, webhook, telegram).

Payload mínimo (LGPD): protocolo, tipo, gravidade, totem — sem relato detalhado.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Protocol
from urllib.parse import urlencode

import httpx

from . import db, voz
from .config import (
    CANAIS,
    CANAIS_INTERNOS,
    CONTACT_OVERRIDE,
    NOTIF_PROVIDER,
    NOTIF_WEBHOOK_TOKEN,
    NOTIF_WEBHOOK_URL,
    PUBLIC_BASE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM,
    TWILIO_MODE,
    TWILIO_VOICE,
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


def montar_mensagem(
    chamado: dict, canal: str, *, escalonamento: bool = False, prefixo: str | None = None
) -> str:
    info = CANAIS.get(canal, {"nome": canal})
    if prefixo is None:
        prefixo = "ESCALONADO" if escalonamento else "ALERTA"
    tipo = TIPO_NOME.get(chamado.get("tipo_ocorrencia", ""), chamado.get("tipo_ocorrencia"))
    grav = GRAV_NOME.get(chamado.get("gravidade", ""), chamado.get("gravidade"))
    return (
        f"POTO {prefixo}. Protocolo {chamado['chamado_id']}. "
        f"Tipo {tipo}. Gravidade {grav}. Totem {chamado.get('totem_id', '?')}. "
        f"Canal {info['nome']}."
    )


# --- Locução de voz (TwiML/SSML, Polly pt-BR) -----------------------------
_GRAV_FALADA = {
    "risco_imediato": "imediata",
    "risco_potencial": "potencial",
    "orientacao": "orientação",
}


def _totem_falado(totem_id: str) -> str:
    """Identificador do totem legível pela TTS: tira o prefixo 'TOTEM-' e troca
    hifens por espaços para ser soletrado com clareza ao telefone."""
    ident = totem_id or ""
    up = ident.upper()
    for pre in ("TOTEM-", "TOTEM_", "TOTEM "):
        if up.startswith(pre):
            ident = ident[len(pre):]
            break
    return ident.replace("-", " ").replace("_", " ").strip() or (totem_id or "")


def _twiml_simples(texto: str) -> str:
    """Fallback de voz: lê o texto puro (sem SSML)."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say voice="{html.escape(TWILIO_VOICE)}" language="pt-BR">'
        f"{html.escape(texto)}</Say></Response>"
    )


def montar_twiml(
    chamado: dict, canal: str, *, audio_url: str | None = None,
    escalonamento: bool = False, prefixo: str | None = None
) -> str:
    """Locução de voz do alerta. Com `audio_url`, toca o WAV pré-gerado na borda
    (Piper) via <Play> — custo de TTS zero. Sem ele, usa <Say>/SSML (Polly/básica):
    roteiro único e enxuto, protocolo em dígitos e totem soletrado."""
    e = html.escape
    if audio_url:
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Play>{e(audio_url)}</Play></Response>"
        )
    tipo = TIPO_NOME.get(
        chamado.get("tipo_ocorrencia", ""), chamado.get("tipo_ocorrencia") or "ocorrência"
    )
    grav = _GRAV_FALADA.get(chamado.get("gravidade", ""), chamado.get("gravidade") or "")
    totem = _totem_falado(chamado.get("totem_id", ""))
    proto = (chamado.get("chamado_id", "") or "").rsplit("-", 1)[-1]
    proto_as = "digits" if proto.isdigit() else "characters"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say voice="{e(TWILIO_VOICE)}" language="pt-BR"><prosody rate="95%">'
        f'Alerta, P O T O. <break time="400ms"/>'
        f'{e(tipo)}, gravidade {e(grav)}. <break time="400ms"/>'
        f'Totem <say-as interpret-as="characters">{e(totem)}</say-as>. <break time="450ms"/>'
        f'Protocolo <say-as interpret-as="{proto_as}">{e(proto)}</say-as>.'
        f"</prosody></Say></Response>"
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
                    # SSML pré-montado (montar_twiml) chega via meta; fallback = texto puro.
                    twiml = meta.get("twiml") or _twiml_simples(mensagem)
                    data: dict = {"To": to, "From": TWILIO_FROM, "Twiml": twiml}
                    # statusCallback ao vivo (tocando/atendida/encerrada) — exige URL pública.
                    # httpx encoda o valor-lista como parâmetro repetido (StatusCallbackEvent).
                    if PUBLIC_BASE_URL:
                        q = urlencode({
                            "chamado_id": meta.get("chamado_id", ""),
                            "canal": meta.get("canal", ""),
                            "escalonamento": int(bool(meta.get("escalonamento"))),
                        })
                        data["StatusCallback"] = f"{PUBLIC_BASE_URL}/api/v1/twilio/status?{q}"
                        data["StatusCallbackEvent"] = ["initiated", "ringing", "answered", "completed"]
                    r = await client.post(f"{base}/Calls.json", auth=auth, data=data)
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
    prefixo: str | None = None,
) -> tuple[bool, str | None]:
    destino = contato_canal(canal)
    mensagem = montar_mensagem(
        chamado, canal, escalonamento=escalonamento, prefixo=prefixo
    )
    # Locução: TTS local (Piper) na borda + <Play> quando pronto e houver túnel
    # (custo de TTS zero); senão cai para <Say>. A síntese roda fora do event loop.
    audio_url = None
    if voz.disponivel() and PUBLIC_BASE_URL:
        nome = await asyncio.to_thread(voz.gerar_audio_local, voz.texto_falado(chamado))
        if nome:
            audio_url = f"{PUBLIC_BASE_URL}/api/v1/audio/{nome}"
    meta = {
        "chamado_id": chamado["chamado_id"],
        "canal": canal,
        "destino": destino,
        "escalonamento": escalonamento,
        "twiml": montar_twiml(
            chamado, canal, audio_url=audio_url, escalonamento=escalonamento, prefixo=prefixo
        ),
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
    return ok, detalhe


async def notificar_chamado(chamado: dict) -> tuple[bool, dict]:
    """Notifica o canal primário e atualiza o status do chamado."""
    ok, _ = await enviar_para_canal(chamado, chamado["canal_roteado"])
    novo_status = "notificado" if ok else "falha_notificacao"
    atualizado = db.update_chamado(chamado["chamado_id"], status=novo_status)
    return ok, atualizado or chamado


async def disparar_panico(
    chamado: dict, canais: list[str] | None = None
) -> list[dict]:
    """Broadcast de PÂNICO (P1, §13.2): aciona em paralelo todas as autoridades
    internas da universidade. Retorna um resultado por canal (não altera o status —
    quem o faz é o endpoint, que marca o chamado como 'alerta_ativo')."""
    canais = canais if canais is not None else CANAIS_INTERNOS

    async def _um(canal: str) -> dict:
        ok, detalhe = await enviar_para_canal(chamado, canal, prefixo="PANICO")
        return {
            "canal": canal,
            "nome": CANAIS.get(canal, {}).get("nome", canal),
            "destino": contato_canal(canal),
            "sucesso": ok,
            "detalhe": detalhe,
        }

    return list(await asyncio.gather(*(_um(c) for c in canais)))


async def escalonar_manual(chamado: dict, canal: str) -> tuple[bool, str | None]:
    """Escalonamento manual (P3, §13.2): a central/totem aciona uma autoridade do
    estado a partir da tela de alerta. Registra a notificação e mantém o alerta
    ativo (não rebaixa o status do chamado)."""
    return await enviar_para_canal(chamado, canal, escalonamento=True, prefixo="ESTADO")


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
    ok, _ = await enviar_para_canal(escalado, fallback, escalonamento=True)
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
        "panico_canais": CANAIS_INTERNOS,
    }
