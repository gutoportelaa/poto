"""Access Token do Twilio Voice (JS SDK) — gerado com PyJWT (sem a lib pesada).

O token concede ao navegador o direito de originar chamadas pelo TwiML App e de
receber chamadas (cliente↔cliente). Formato conforme a especificação do Twilio:
header com `cty: twilio-fpa;v=1` e grant de voz no payload.
"""

from __future__ import annotations

import time

try:
    import jwt
except ModuleNotFoundError:  # PyJWT é opcional: sem ela, só o Voice SDK fica indisponível
    jwt = None

from .config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY_SECRET,
    TWILIO_API_KEY_SID,
    TWILIO_TWIML_APP_SID,
)


def configurado() -> bool:
    return bool(jwt and TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET and TWILIO_TWIML_APP_SID)


def gerar_access_token(identity: str, ttl: int = 3600) -> str:
    """JWT de Access Token do Voice SDK para `identity` (válido por `ttl` s)."""
    if jwt is None:
        raise RuntimeError("PyJWT não instalado — rode 'uv sync' no backend")
    now = int(time.time())
    payload = {
        "jti": f"{TWILIO_API_KEY_SID}-{now}",
        "iss": TWILIO_API_KEY_SID,
        "sub": TWILIO_ACCOUNT_SID,
        "nbf": now,
        "exp": now + ttl,
        "grants": {
            "identity": identity,
            "voice": {
                "incoming": {"allow": True},
                "outgoing": {"application_sid": TWILIO_TWIML_APP_SID},
            },
        },
    }
    return jwt.encode(
        payload,
        TWILIO_API_KEY_SECRET,
        algorithm="HS256",
        headers={"cty": "twilio-fpa;v=1"},
    )


def status() -> dict:
    return {"configurado": configurado(), "api_key": TWILIO_API_KEY_SID or None}
