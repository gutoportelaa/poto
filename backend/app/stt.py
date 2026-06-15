"""Transcrição de fala (Speech-to-Text) plugável e local.

Provedores suportados via POTO_STT_PROVIDER:
  - "none"            (padrão)  -> transcrição indisponível; o totem pede texto digitado.
  - "faster-whisper"  -> Whisper local (CPU), instalável com `make stt-setup`.

O design segue o princípio do projeto: degrada com elegância. Sem provedor/modelo,
a captura de áudio continua funcionando (a UI mostra "áudio recebido"), apenas a
transcrição automática fica indisponível.
"""

from __future__ import annotations

import logging
import os
import tempfile

log = logging.getLogger("poto.stt")

PROVIDER = os.getenv("POTO_STT_PROVIDER", "none").strip().lower()
WHISPER_MODEL = os.getenv("POTO_WHISPER_MODEL", "base")

_model = None


class STTIndisponivel(RuntimeError):
    """Nenhum provedor de STT configurado/instalado."""


def _faster_whisper_ok() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def disponivel() -> bool:
    return PROVIDER == "faster-whisper" and _faster_whisper_ok()


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("Carregando modelo Whisper '%s' (cpu/int8)…", WHISPER_MODEL)
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcrever(audio: bytes, sufixo: str = ".webm") -> str:
    if not disponivel():
        raise STTIndisponivel("POTO_STT_PROVIDER não configurado ou faster-whisper ausente.")
    with tempfile.NamedTemporaryFile(suffix=sufixo) as f:
        f.write(audio)
        f.flush()
        segmentos, _info = _get_model().transcribe(f.name, language="pt", vad_filter=True)
        texto = " ".join(s.text for s in segmentos).strip()
    log.info("Transcrição concluída (%d caracteres).", len(texto))
    return texto


def status() -> dict:
    return {"provider": PROVIDER, "disponivel": disponivel(), "modelo": WHISPER_MODEL}
