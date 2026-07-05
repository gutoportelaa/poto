#!/usr/bin/env python3
"""Smoke-test do canal de sinalização WebRTC (`/rtc/{sala}`) — a via por onde a
faixa de áudio (áudio-only) negocia a conexão totem↔central.

Simula dois pares na mesma sala (totem publicando + operador) e verifica que o
backend RELÊ offer/answer/ICE corretamente e emite `video_ativo` ao publicar.
NÃO testa a mídia em si (RTP/áudio) — isso exige dois navegadores com mic; ver as
instruções ao final. Roda em processo (valida o código implantado), sem servidor.

Uso:
    cd backend && uv run python ../scripts/rtc_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

SALA = "CALL-SMOKE"
URL = f"/api/v1/rtc/{SALA}"


def main() -> None:
    from starlette.testclient import TestClient

    from app import db
    from app.main import app
    db.init_db()

    ok = []
    def check(nome: str, cond: bool) -> None:
        ok.append(cond)
        print(f"  {'[OK]' if cond else '[FALHOU]'} {nome}")

    c = TestClient(app)
    with c.websocket_connect(URL) as totem, c.websocket_connect(URL) as oper:
        # 1. presença: o totem é avisado quando o operador entra na sala
        check("totem detecta operador na sala (peer-entrou)",
              totem.receive_json().get("tipo") == "peer-entrou")

        # 2. o totem publica a faixa de áudio (audio-only) → relé + video_ativo
        totem.send_json({"tipo": "publicando", "totem_id": "TOTEM-CCS-01"})
        totem.send_json({"tipo": "totem-pronto"})
        tipos_oper = {oper.receive_json().get("tipo") for _ in range(2)}
        check("operador recebe 'publicando' e 'totem-pronto'",
              {"publicando", "totem-pronto"} <= tipos_oper)

        # 3. handshake SDP: operador-pronto → offer → answer
        oper.send_json({"tipo": "operador-pronto"})
        check("totem recebe 'operador-pronto'",
              totem.receive_json().get("tipo") == "operador-pronto")
        totem.send_json({"tipo": "offer", "sdp": {"type": "offer", "sdp": "v=0 (audio)"}})
        check("operador recebe a 'offer' do totem",
              oper.receive_json().get("tipo") == "offer")
        oper.send_json({"tipo": "answer", "sdp": {"type": "answer", "sdp": "v=0 (audio)"}})
        check("totem recebe a 'answer' da central",
              totem.receive_json().get("tipo") == "answer")

        # 4. troca de candidatos ICE (bidirecional)
        totem.send_json({"tipo": "ice", "candidate": {"candidate": "cand-totem"}})
        check("ICE totem→central relê", oper.receive_json().get("tipo") == "ice")
        oper.send_json({"tipo": "ice", "candidate": {"candidate": "cand-central"}})
        check("ICE central→totem relê", totem.receive_json().get("tipo") == "ice")

    total, passou = len(ok), sum(ok)
    print(f"\n  {passou}/{total} verificações de sinalização OK\n")
    if passou == total:
        print("Sinalização /rtc validada. Para validar a MÍDIA (áudio real), 2 navegadores:")
        print("  1. Totem  → dispare um chamado e toque 'Falar com a central' (sem câmera = áudio-only).")
        print("  2. Painel → abra o chamado e 'Atender' — fale; o áudio deve ir nos dois sentidos.")
        print("  (contexto seguro: localhost ou HTTPS; STUN em /rtc/config.)")
    sys.exit(0 if passou == total else 1)


if __name__ == "__main__":
    main()
