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
# Modelo POR TAREFA (decisão sem Hailo: triagem e conversa podem usar modelos
# diferentes, priorizando mini/nano na CPU da Pi). Vazio = usa POTO_OLLAMA_MODEL.
# A CONVERSA roda sempre local (offline total); use `make bench` para escolher a
# triagem por dados. Ver docs/inferencia.md.
TRIAGEM_MODEL = os.getenv("POTO_TRIAGEM_MODEL", "").strip() or OLLAMA_MODEL
CONVERSA_MODEL = os.getenv("POTO_CONVERSA_MODEL", "").strip() or OLLAMA_MODEL

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

# --- Totens / heartbeat ----------------------------------------------------
# Um totem é considerado offline se o último heartbeat for mais antigo que isto.
# Deve ser folgado o bastante para o intervalo de envio do totem (15s).
TOTEM_OFFLINE_SEG = int(os.getenv("POTO_TOTEM_OFFLINE_SEG", "45"))

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
# Voz da locução do alerta (TwiML <Say>). Polly pt-BR soa bem melhor que a voz
# padrão; troque por "Polly.Camila-Neural" se a conta tiver vozes neurais.
TWILIO_VOICE = os.getenv("POTO_TWILIO_VOICE", "Polly.Camila").strip()
# Alerta PSTN (ligação ao celular do contato). Em demos de chamada ao vivo
# (Voice SDK navegador↔navegador) convém desligar para não gastar crédito do
# trial a cada ocorrência: POTO_ALERTA_PSTN=off. A chamada ao vivo não é afetada.
ALERTA_PSTN_ENABLED = os.getenv("POTO_ALERTA_PSTN", "on").strip().lower() not in (
    "off", "0", "false", "no", "nao", "não",
)

# URL pública do backend (túnel cloudflared/ngrok) para os callbacks do Twilio.
# Sem ela, a ligação ainda sai, mas não há status ao vivo (statusCallback).
PUBLIC_BASE_URL = os.getenv("POTO_PUBLIC_BASE_URL", "").strip().rstrip("/")

# --- SIMCom A7670SA: canal GSM/2G real (voz + SMS via AT/serial) -----------
# Provider notifier alternativo ao Twilio: com um SIM real o totem ganha número
# próprio e disca de verdade — sem número virtual. O A7670SA NÃO tem VoLTE, então
# a VOZ só sai via fallback 2G/GSM (por isso FORCE_GSM manda AT+CNMP=13). SMS sai
# tanto em LTE quanto em GSM. O módulo enumera vários /dev/ttyUSB*; PORT é a porta AT.
SIMCOM_PORT = os.getenv("POTO_SIMCOM_PORT", "/dev/ttyUSB2").strip()
SIMCOM_BAUD = int(os.getenv("POTO_SIMCOM_BAUD", "115200"))
# voice = só liga (ATD)  | sms = só SMS  | both = liga E manda SMS com os detalhes.
# "both" é o mais robusto: a ligação chama atenção e o SMS carrega o protocolo.
SIMCOM_MODE = os.getenv("POTO_SIMCOM_MODE", "both").strip().lower()
# Quanto tempo manter a ligação no ar (toca/toca a locução) antes de AT+CHUP.
SIMCOM_CALL_SEG = int(os.getenv("POTO_SIMCOM_CALL_SEG", "20"))
# Forçar 2G-only (AT+CNMP=13) na inicialização — necessário p/ voz confiável (CSFB).
SIMCOM_FORCE_GSM = _bool("POTO_SIMCOM_FORCE_GSM", True)
SIMCOM_AT_TIMEOUT = float(os.getenv("POTO_SIMCOM_AT_TIMEOUT", "10"))
# Como tocar a locução pt-BR (WAV do Piper) DENTRO da ligação. Template com {wav}.
# Ex.: "aplay -D plughw:CARD=Module,DEV=0 {wav}" quando o A7670SA expõe áudio USB,
# ou um alto-falante ligado à saída SPK analógica do módulo. Vazio = só toca (ring).
SIMCOM_AUDIO_CMD = os.getenv("POTO_SIMCOM_AUDIO_CMD", "").strip()
# Dispositivo de voz do módulo (AT+CSDVC): 1=handset, 3=viva-voz. Vazio = não mexe.
SIMCOM_SPK_DEVICE = os.getenv("POTO_SIMCOM_SPK_DEVICE", "").strip()

# --- Locução de voz: como o áudio da ligação é gerado ----------------------
# say   = TwiML <Say> (Polly/básica; depende de POTO_TWILIO_VOICE)
# local = TTS offline (Piper) na borda; o Twilio só toca o WAV via <Play>
#         (custo de TTS zero). Exige POTO_PUBLIC_BASE_URL (o Twilio busca o áudio).
VOICE_TTS = os.getenv("POTO_VOICE_TTS", "say").strip().lower()
PIPER_BIN = os.getenv("POTO_PIPER_BIN", "piper").strip()
PIPER_MODEL = os.getenv("POTO_PIPER_MODEL", "").strip()  # caminho do .onnx
AUDIO_DIR = os.getenv("POTO_AUDIO_DIR", str(BASE_DIR / "audio_cache"))
AUDIO_TTL_SEG = int(os.getenv("POTO_AUDIO_TTL_SEG", "900"))  # limpa WAVs antigos

# Chamada A/V ao vivo totem↔central = WebRTC P2P nativo (ver video.ts / SignalingHub).
# Twilio é usado apenas na perna de alerta PSTN (notifier).

# Contatos por canal (E.164 ou e-mail). Usados quando CONTACT_OVERRIDE está vazio.
_CONTACTS_RAW = {
    "csv": os.getenv("POTO_CONTACT_CSV", "558632155591"),
    "sala_lilas": os.getenv("POTO_CONTACT_SALA_LILAS", "5586994287263"),
    "sapsi": os.getenv("POTO_CONTACT_SAPSI", "sapsi@ufpi.edu.br"),
    "ouvidoria": os.getenv("POTO_CONTACT_OUVIDORIA", "ouvidoria@ufpi.br"),
    "samu_192": os.getenv("POTO_CONTACT_SAMU", "192"),
    "pm_190": os.getenv("POTO_CONTACT_PM", "190"),
    "bombeiros_193": os.getenv("POTO_CONTACT_BOMBEIROS", "193"),
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
        ("bombeiros_193", "Corpo de Bombeiros"),
        ("central_180", "Central de Atendimento à Mulher"),
    ]
}

# Grupos para o fluxo de PÂNICO (DESIGN.md §13.2):
# - INTERNOS: autoridades da universidade acionadas no broadcast (P1).
# - ESTADO: autoridades externas oferecidas para escalonamento manual (P3).
# O broadcast usa, por padrão, os canais internos alcançáveis por voz; ajustável
# por POTO_PANICO_CANAIS (lista separada por vírgula).
CANAIS_INTERNOS = [
    c.strip()
    for c in os.getenv("POTO_PANICO_CANAIS", "csv,sala_lilas").split(",")
    if c.strip() in _CONTACTS_RAW
]
CANAIS_ESTADO = ["pm_190", "samu_192", "bombeiros_193", "central_180"]


def contato_canal(canal: str) -> str:
    """Resolve o destino efetivo (override de testes ou contato do canal)."""
    if CONTACT_OVERRIDE:
        return CONTACT_OVERRIDE
    return _CONTACTS_RAW.get(canal, canal)
