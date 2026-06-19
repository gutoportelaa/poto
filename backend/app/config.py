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

# --- Vídeo: registro (evidência) e transmissão (WebRTC) -------------------
EVIDENCIA_ENABLED = _bool("POTO_EVIDENCIA_ENABLED", True)
EVIDENCIA_DIR = os.getenv("POTO_EVIDENCIA_DIR", str(BASE_DIR / "evidencias"))
EVIDENCIA_MAX_MB = int(os.getenv("POTO_EVIDENCIA_MAX_MB", "80"))

# ICE servers para WebRTC. Em LAN/localhost os "host candidates" bastam; o STUN
# ajuda atrás de NAT. TURN só é necessário em NAT simétrico (deixar vazio no PoC).
STUN_URL = os.getenv("POTO_STUN_URL", "stun:stun.l.google.com:19302")
TURN_URL = os.getenv("POTO_TURN_URL", "")
TURN_USER = os.getenv("POTO_TURN_USER", "")
TURN_PASS = os.getenv("POTO_TURN_PASS", "")

# --- Notificação externa ---------------------------------------------------
# Redireciona todos os destinos para um número (testes em bancada).
CONTACT_OVERRIDE = os.getenv("POTO_CONTACT_OVERRIDE", "").strip()
NOTIF_PROVIDER = os.getenv("POTO_NOTIF_PROVIDER", "log").strip().lower()
NOTIF_WEBHOOK_URL = os.getenv("POTO_NOTIF_WEBHOOK_URL", "").strip()
NOTIF_WEBHOOK_TOKEN = os.getenv("POTO_NOTIF_WEBHOOK_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("POTO_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("POTO_TELEGRAM_CHAT_ID", "").strip()
SLA_CHECK_INTERVAL = int(os.getenv("POTO_SLA_CHECK_INTERVAL", "30"))

# Twilio (voz ou SMS)
TWILIO_ACCOUNT_SID = os.getenv("POTO_TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("POTO_TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM = os.getenv("POTO_TWILIO_FROM", "").strip()
TWILIO_MODE = os.getenv("POTO_TWILIO_MODE", "voice").strip().lower()  # voice | sms

# Contatos por canal (E.164 ou e-mail). Usados quando CONTACT_OVERRIDE está vazio.
_CONTACTS_RAW = {
    "csv": os.getenv("POTO_CONTACT_CSV", "558632155591"),
    "sala_lilas": os.getenv("POTO_CONTACT_SALA_LILAS", "5586994287263"),
    "sapsi": os.getenv("POTO_CONTACT_SAPSI", "sapsi@ufpi.edu.br"),
    "ouvidoria": os.getenv("POTO_CONTACT_OUVIDORIA", "ouvidoria@ufpi.br"),
    "samu_192": os.getenv("POTO_CONTACT_SAMU", "192"),
    "pm_190": os.getenv("POTO_CONTACT_PM", "190"),
    "central_180": os.getenv("POTO_CONTACT_180", "180"),
}

CANAIS = {
    key: {"nome": nome, "contato": _CONTACTS_RAW[key]}
    for key, nome in [
        ("csv", "CSV / PREUNI"),
        ("sala_lilas", "Sala Lilás"),
        ("sapsi", "SAPSI / PRAEC"),
        ("ouvidoria", "Ouvidoria UFPI / Fala.BR"),
        ("samu_192", "SAMU"),
        ("pm_190", "Polícia Militar"),
        ("central_180", "Central de Atendimento à Mulher"),
    ]
}


def contato_canal(canal: str) -> str:
    """Resolve o destino efetivo (override de testes ou contato do canal)."""
    if CONTACT_OVERRIDE:
        return CONTACT_OVERRIDE
    return _CONTACTS_RAW.get(canal, canal)
