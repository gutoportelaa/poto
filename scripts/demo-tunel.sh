#!/usr/bin/env bash
#
# demo-tunel.sh — sobe um túnel cloudflared efêmero e reconfigura tudo que
# depende da URL pública, num comando só. Pensado para a demo do P.O.T.O
# enquanto não houver domínio próprio (túnel nomeado/estável).
#
# O que faz:
#   1. Sobe `cloudflared` (protocolo http2, evita o erro de QUIC) apontando
#      para o backend local (porta 8000) e captura a URL nova.
#   2. Grava POTO_PUBLIC_BASE_URL no backend/.env (statusCallback + áudio Piper).
#   3. Atualiza o Voice URL do TwiML App no Twilio via API (chamada do Voice SDK).
#   4. Segura o túnel em primeiro plano — Ctrl+C encerra o túnel.
#
# Uso (na rasp):
#   1) Terminal A:  bash scripts/demo-tunel.sh
#   2) Terminal B:  make dev          # lê o .env já atualizado
#
set -euo pipefail

# ---- localizar a raiz do repo (este script vive em scripts/) -------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# O túnel aponta para o FRONTEND (Bun 5173), que serve as páginas/assets e faz
# reverse-proxy de /api/* (HTTP+WS) para o backend. Assim uma origem só serve tudo.
ENV_FILE="$ROOT/backend/.env"
PORT="${POTO_FRONTEND_PORT:-5173}"

[ -f "$ENV_FILE" ] || { echo "ERRO: $ENV_FILE não encontrado." >&2; exit 1; }
command -v cloudflared >/dev/null || { echo "ERRO: cloudflared não está no PATH." >&2; exit 1; }

# ---- subir o túnel e capturar a URL --------------------------------------
LOG="$(mktemp -t poto-tunel-XXXX.log)"
echo "› Subindo cloudflared (http2) → http://localhost:$PORT ..."
cloudflared tunnel --protocol http2 --url "http://localhost:$PORT" >"$LOG" 2>&1 &
CF_PID=$!
trap 'echo; echo "› Encerrando túnel (pid $CF_PID)…"; kill "$CF_PID" 2>/dev/null || true; rm -f "$LOG"' INT TERM EXIT

URL=""
for _ in $(seq 1 40); do   # ~40s de tolerância
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  [ -n "$URL" ] && break
  kill -0 "$CF_PID" 2>/dev/null || { echo "ERRO: cloudflared morreu. Log:" >&2; cat "$LOG" >&2; exit 1; }
  sleep 1
done
[ -n "$URL" ] || { echo "ERRO: não captei a URL do túnel em 40s. Log:" >&2; cat "$LOG" >&2; exit 1; }
echo "✓ Túnel: $URL"

# ---- gravar POTO_PUBLIC_BASE_URL no .env ---------------------------------
TMP="$(mktemp)"
grep -v '^POTO_PUBLIC_BASE_URL=' "$ENV_FILE" > "$TMP" || true
echo "POTO_PUBLIC_BASE_URL=$URL" >> "$TMP"
cp "$TMP" "$ENV_FILE"; rm -f "$TMP"
echo "✓ .env: POTO_PUBLIC_BASE_URL atualizado"
# Obs.: a chamada A/V ao vivo é WebRTC P2P nativo (não depende de túnel/Twilio).
# O POTO_PUBLIC_BASE_URL acima serve só ao alerta PSTN (statusCallback + áudio).

# ---- pronto --------------------------------------------------------------
cat <<EOF

──────────────────────────────────────────────────────────────
 Túnel pronto e configurado.  URL: $URL
 Agora, em OUTRO terminal:    make dev
 (o backend vai ler o .env já atualizado)

 Ctrl+C aqui encerra o túnel.
──────────────────────────────────────────────────────────────
EOF

wait "$CF_PID"
