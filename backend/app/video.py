"""Registro de vídeo (evidência) e configuração de transmissão (WebRTC).

Princípios (ver §14 da projeção final):
- Privacy-by-design: a evidência é gravada sob política, com metadados mínimos.
- A transmissão ao vivo (WebRTC) usa o backend apenas como **sinalização** (SDP/ICE);
  o vídeo trafega peer-to-peer entre o totem e o operador da central.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    EVIDENCIA_DIR,
    EVIDENCIA_ENABLED,
    STUN_URL,
    TURN_PASS,
    TURN_URL,
    TURN_USER,
)

log = logging.getLogger("poto.video")
_dir = Path(EVIDENCIA_DIR)


class EvidenciaDesativada(RuntimeError):
    """Registro de evidência desativado por configuração."""


def salvar_evidencia(dados: bytes, chamado_id: str, totem_id: str, sufixo: str = ".webm") -> dict:
    if not EVIDENCIA_ENABLED:
        raise EvidenciaDesativada("POTO_EVIDENCIA_ENABLED está desativado.")
    _dir.mkdir(parents=True, exist_ok=True)
    ev_id = uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc)
    base = f"{ts:%Y%m%d-%H%M%S}_{totem_id}_{ev_id}"
    arquivo = base + sufixo
    (_dir / arquivo).write_bytes(dados)
    meta = {
        "evidencia_id": ev_id,
        "arquivo": arquivo,
        "chamado_id": chamado_id,
        "totem_id": totem_id,
        "bytes": len(dados),
        "criado_em": ts.isoformat(),
    }
    (_dir / (base + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    log.info("Evidência registrada: %s (%d bytes)", arquivo, len(dados))
    return meta


def listar_evidencias() -> list[dict]:
    if not _dir.is_dir():
        return []
    out = []
    for j in sorted(_dir.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(j.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def ice_servers() -> list[dict]:
    servers: list[dict] = []
    if STUN_URL:
        servers.append({"urls": STUN_URL})
    if TURN_URL:
        servers.append({"urls": TURN_URL, "username": TURN_USER, "credential": TURN_PASS})
    return servers


def status() -> dict:
    return {
        "evidencia_enabled": EVIDENCIA_ENABLED,
        "evidencias": len(listar_evidencias()),
        "ice_servers": len(ice_servers()),
    }
