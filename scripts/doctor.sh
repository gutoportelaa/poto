#!/usr/bin/env bash
# P.O.T.O — verificação de módulos do setup (diagnóstico read-only).
# Uso: make doctor   |   bash scripts/doctor.sh
# Cada linha mostra: [OK] disponível · [!!] ausente/atenção · [--] opcional ausente.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACK="$ROOT/backend"
FRONT="$ROOT/frontend"
API="${POTO_API:-http://127.0.0.1:8000}"
FRONT_URL="${POTO_FRONT:-http://127.0.0.1:5173}"

g=$'\e[32m'; r=$'\e[31m'; y=$'\e[33m'; b=$'\e[1m'; d=$'\e[2m'; n=$'\e[0m'
ok(){   printf "  ${g}[OK]${n} %-22s %s\n" "$1" "${2:-}"; }
bad(){  printf "  ${r}[!!]${n} %-22s %s\n" "$1" "${2:-}"; }
opt(){  printf "  ${y}[--]${n} %-22s %s\n" "$1" "${2:-}"; }
titulo(){ printf "\n${b}%s${n}\n" "$1"; }
have(){ command -v "$1" >/dev/null 2>&1; }

printf "${b}P.O.T.O — diagnóstico de setup${n}  ${d}(%s)${n}\n" "$(date '+%d/%m/%Y %H:%M')"

# ------------------------------------------------------------- ferramentas
titulo "Ferramentas"
for t in uv bun ollama python3 node; do
  if have "$t"; then ok "$t" "$($t --version 2>&1 | head -1)"; else bad "$t" "não encontrado no PATH"; fi
done
have arecord || opt "alsa-utils" "arecord/aplay ausentes (teste de áudio limitado)"
have v4l2-ctl || opt "v4l-utils" "v4l2-ctl ausente (teste de câmera limitado)"
have ffmpeg || opt "ffmpeg" "ausente (captura de teste de cam/mic indisponível)"

# ----------------------------------------------------------------- backend
titulo "Backend (Python / uv)"
if [ -d "$BACK/.venv" ]; then ok "venv" "$BACK/.venv"; else bad "venv" "rode: make setup-backend"; fi
if (cd "$BACK" && uv run python -c "import app.main" >/dev/null 2>&1); then
  ok "import app.main" "ok"
else
  bad "import app.main" "deps faltando? rode: cd backend && uv sync"
fi

# ------------------------------------------------------------------ agentes
titulo "Agentes / Ollama"
if curl -sf --max-time 3 "${OLLAMA_HOST:-http://127.0.0.1:11434}/api/tags" >/dev/null 2>&1; then
  ok "ollama serve" "respondendo"
  modelo="${POTO_OLLAMA_MODEL:-llama3.2:3b}"
  if curl -s --max-time 3 "${OLLAMA_HOST:-http://127.0.0.1:11434}/api/tags" | grep -q "\"$modelo\""; then
    ok "modelo" "$modelo presente"
  else
    opt "modelo" "$modelo ausente — rode: make agents-pull"
  fi
else
  opt "ollama serve" "fora do ar — agentes caem na heurística"
fi

# -------------------------------------------------------------------- STT
titulo "STT (transcrição de voz)"
prov="${POTO_STT_PROVIDER:-none}"
if [ "$prov" = "faster-whisper" ]; then
  if (cd "$BACK" && uv run python -c "import faster_whisper" >/dev/null 2>&1); then
    ok "faster-whisper" "instalado (modelo: ${POTO_WHISPER_MODEL:-base})"
  else
    bad "faster-whisper" "POTO_STT_PROVIDER=faster-whisper mas pacote ausente — rode: make stt-setup"
  fi
else
  opt "STT" "POTO_STT_PROVIDER=none — voz só registra; sem transcrição (make stt-setup)"
fi

# ----------------------------------------------------------- módulos físicos
titulo "Módulos físicos (câmera / microfone / áudio)"
# Câmera
cams=$(ls /dev/video* 2>/dev/null)
if [ -n "$cams" ]; then ok "câmera" "$(echo "$cams" | tr '\n' ' ')";
elif have libcamera-hello || have rpicam-hello; then opt "câmera" "CSI via libcamera (sem /dev/video*)";
else bad "câmera" "nenhum /dev/video* (módulo ausente ou WSL sem passthrough)"; fi
# Microfone (ALSA)
if have arecord; then
  mics=$(arecord -l 2>/dev/null | grep -c '^card')
  if [ "${mics:-0}" -gt 0 ]; then ok "microfone" "$mics dispositivo(s) de captura"; \
  else bad "microfone" "nenhum dispositivo de captura (módulo ausente)"; fi
else
  opt "microfone" "arecord ausente; no navegador use getUserMedia para testar"
fi
# Saída de áudio
if have aplay; then
  spk=$(aplay -l 2>/dev/null | grep -c '^card')
  [ "${spk:-0}" -gt 0 ] && ok "alto-falante" "$spk dispositivo(s)" || opt "alto-falante" "nenhum dispositivo"
fi
# GPIO (Raspberry Pi)
if ls /dev/gpiochip* >/dev/null 2>&1; then ok "GPIO" "$(ls /dev/gpiochip* | tr '\n' ' ')"; \
else opt "GPIO" "sem /dev/gpiochip* (não é um Raspberry Pi / botão de pânico indisponível)"; fi

# ------------------------------------------------------------- serviços/portas
titulo "Serviços (API / Frontend)"
if curl -sf --max-time 3 "$API/api/v1/health" >/dev/null 2>&1; then
  ok "API" "$API (health ok)"
  curl -s --max-time 3 "$API/api/v1/health" \
    | python3 -c "import sys,json;h=json.load(sys.stdin);print('       ',{'stt':h['stt']['disponivel'],'video':h['video']['evidencia_enabled'],'agentes':h['agentes']['modo']})" 2>/dev/null
else
  opt "API" "$API fora do ar — rode: make backend"
fi
if curl -sf --max-time 3 "$FRONT_URL/" >/dev/null 2>&1; then ok "Frontend" "$FRONT_URL"; \
else opt "Frontend" "$FRONT_URL fora do ar — rode: make frontend"; fi
[ -d "$FRONT/node_modules" ] && ok "node_modules" "instalado" || bad "node_modules" "rode: make setup-frontend"
[ -d "$FRONT/dist" ] && ok "dist (build)" "presente" || opt "dist (build)" "rode: make build-frontend"

titulo "Testes rápidos opcionais"
echo "  ${d}Microfone (3s):${n} arecord -d 3 -f cd /tmp/mic.wav && aplay /tmp/mic.wav"
echo "  ${d}Câmera (foto):${n}  ffmpeg -y -f v4l2 -i /dev/video0 -frames:v 1 /tmp/cam.jpg"
echo "  ${d}No navegador:${n}   o totem usa getUserMedia (precisa de localhost ou HTTPS)"
echo
echo "${d}Legenda: [OK] pronto · [!!] precisa de ação · [--] opcional/ausente.${n}"
