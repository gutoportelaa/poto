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


async def verificar_validacao(hub) -> None:
    """Fail-safe do nível 'suposto perigo': se o operador não validar a tempo,
    notifica sozinho em vez de deixar o pedido parado (silêncio humano não arquiva)."""
    for chamado in db.chamados_validacao_expirada():
        log.warning(
            "Validação humana expirada: %s — notificando automaticamente.",
            chamado["chamado_id"],
        )
        db.update_chamado(
            chamado["chamado_id"],
            observacao="Validação humana expirada — notificado automaticamente (fail-safe).",
        )
        _, atualizado = await notifier.notificar_chamado(chamado)
        await hub.broadcast("atualizado", atualizado)


async def sla_loop(hub) -> None:
    while True:
        try:
            await verificar_sla(hub)
            await verificar_validacao(hub)
        except Exception:
            log.exception("Erro no ciclo de SLA")
        await asyncio.sleep(SLA_CHECK_INTERVAL)
