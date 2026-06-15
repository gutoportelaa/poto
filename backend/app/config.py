"""Configuração via variáveis de ambiente (12-factor)."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# --- Banco de dados -------------------------------------------------------
DB_PATH = os.getenv("POTO_DB_PATH", str(BASE_DIR / "poto.db"))

# --- Agentes / Ollama -----------------------------------------------------
# Online  = backend acessível, agentes rodam aqui (Ollama local).
# Offline = totem opera em store-and-forward; backend pode estar fora.
AGENTS_ENABLED = _bool("POTO_AGENTS_ENABLED", True)
OLLAMA_BASE_URL = os.getenv("POTO_OLLAMA_URL", "http://localhost:11434")
# Modelo pequeno e presente por padrão; troque por qwen2.5:14b para mais qualidade.
OLLAMA_MODEL = os.getenv("POTO_OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = float(os.getenv("POTO_OLLAMA_TIMEOUT", "20"))

# --- Frontend estático (modo standalone: o backend serve a PWA) ----------
FRONTEND_DIST = os.getenv("POTO_FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))

# --- Horários de funcionamento dos serviços (America/Fortaleza, UTC-3) ----
# Sala Lilás / SAPSI: seg–sex, 08–12 e 14–17.
HORARIO_COMERCIAL = {
    "dias": {0, 1, 2, 3, 4},  # 0 = segunda ... 4 = sexta
    "janelas": [(8, 12), (14, 17)],
}

# --- SLA por gravidade (segundos para ACK) --------------------------------
SLA_SEGUNDOS = {
    "risco_imediato": 120,
    "risco_potencial": 600,
    "orientacao": None,
}
