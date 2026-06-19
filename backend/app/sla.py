"""Worker de SLA — escalonamento automático quando ACK não chega a tempo."""

from __future__ import annotations

import asyncio
import logging

from . import db, notifier
from .config import SLA_CHECK_INTERVAL

log = logging.getLogger("poto.sla")


async def verificar_sla(hub) -> None:
    for chamado in db.chamados_sla_expirado():
        log.warning("SLA expirado: %s — escalonando para %s", chamado["chamado_id"], chamado.get("fallback"))
        atualizado = await notifier.escalonar_chamado(chamado)
        if atualizado:
            await hub.broadcast("atualizado", atualizado)


async def sla_loop(hub) -> None:
    while True:
        try:
            await verificar_sla(hub)
        except Exception:
            log.exception("Erro no ciclo de SLA")
        await asyncio.sleep(SLA_CHECK_INTERVAL)
