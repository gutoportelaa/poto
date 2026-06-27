"""Locução de voz local (TTS offline) para a ligação de alerta.

Gera o áudio na borda (Piper) e o Twilio só o toca via <Play> — custo de TTS
zero e sem dependência de nuvem. Degrada com elegância: se o Piper não estiver
configurado/disponível, `gerar_audio_local` devolve None e o notifier usa <Say>.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from pathlib import Path

from .config import AUDIO_DIR, AUDIO_TTL_SEG, PIPER_BIN, PIPER_MODEL, VOICE_TTS

log = logging.getLogger("poto.voz")

TIPO_FALADO = {
    "seguranca": "Segurança",
    "mulher": "Atendimento à mulher",
    "saude": "Saúde",
    "ouvidoria": "Ouvidoria",
}
GRAV_FALADA = {
    "risco_imediato": "imediata",
    "risco_potencial": "potencial",
    "orientacao": "orientação",
}
_DIG = {
    "0": "zero", "1": "um", "2": "dois", "3": "três", "4": "quatro",
    "5": "cinco", "6": "seis", "7": "sete", "8": "oito", "9": "nove",
}


def _digitos(s: str) -> str:
    """Lê uma sequência dígito a dígito (000123 -> 'zero zero zero um dois três')."""
    return " ".join(_DIG.get(c, c) for c in s if not c.isspace())


def texto_falado(chamado: dict) -> str:
    """Roteiro único e enxuto, em texto puro (o Piper não usa SSML). Mesmo
    conteúdo do <Say>: tipo, gravidade, totem e protocolo soletrado."""
    tipo = TIPO_FALADO.get(
        chamado.get("tipo_ocorrencia", ""), chamado.get("tipo_ocorrencia") or "ocorrência"
    )
    grav = GRAV_FALADA.get(chamado.get("gravidade", ""), chamado.get("gravidade") or "")
    totem = (chamado.get("totem_id", "") or "").replace("-", " ").replace("_", " ").strip()
    proto = (chamado.get("chamado_id", "") or "").rsplit("-", 1)[-1]
    return (
        f"Alerta. P, O, T, O. {tipo}, gravidade {grav}. "
        f"Totem {totem}. Protocolo {_digitos(proto)}."
    )


def disponivel() -> bool:
    """True quando a locução local está pronta (modo 'local' + modelo Piper presente)."""
    return VOICE_TTS == "local" and bool(PIPER_MODEL) and Path(PIPER_MODEL).is_file()


def _limpar_antigos(dir_: Path) -> None:
    agora = time.time()
    for f in dir_.glob("*.wav"):
        try:
            if agora - f.stat().st_mtime > AUDIO_TTL_SEG:
                f.unlink()
        except OSError:
            pass


def gerar_audio_local(texto: str) -> str | None:
    """Sintetiza `texto` em WAV via Piper. Retorna o NOME do arquivo (em AUDIO_DIR)
    ou None se indisponível/falhar (o chamador cai para <Say>). Deduplica por
    hash do conteúdo: alertas idênticos reusam o mesmo arquivo."""
    if not disponivel():
        return None
    d = Path(AUDIO_DIR)
    d.mkdir(parents=True, exist_ok=True)
    _limpar_antigos(d)
    nome = f"alerta-{hashlib.sha1(texto.encode('utf-8')).hexdigest()[:12]}.wav"
    out = d / nome
    if out.is_file() and out.stat().st_size > 0:
        os.utime(out, None)  # renova o mtime para o TTL não apagar enquanto em uso
        return nome
    try:
        subprocess.run(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", str(out)],
            input=texto.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("Piper indisponível (%s) — locução cai para <Say>.", e)
        return None
    if not out.is_file() or out.stat().st_size == 0:
        return None
    return nome


def status() -> dict:
    return {"modo": VOICE_TTS, "local_disponivel": disponivel(), "modelo": PIPER_MODEL or None}
