# Montagem do Totem Físico — Raspberry Pi 5

Guia para a fase hardware do P.O.T.O v1.0, após o software estar validado em bancada.

## Pré-requisitos de software

1. Backend rodando e acessível na rede local (`make dev` ou `make build-frontend && make backend`).
2. `.env` configurado em `backend/.env` (copie de `.env.example`).
3. Critérios de aceite validados (`make test` + `make acceptance`).

## BOM (núcleo)

| Item | Modelo sugerido |
|------|-----------------|
| Controlador | Raspberry Pi 5 — 8 GB |
| Câmera | Pi Camera Module 3 Wide **ou** Logitech C920 |
| Microfone | USB array **ou** embutido na C920 |
| Tela touch | Pi Touch Display 2 (7") **ou** HDMI + touch USB |
| Botão pânico | Botão arcade 60 mm + jumpers GPIO |
| Fonte | USB-C PD 27 W oficial |
| Armazenamento | microSD 64 GB A2 |

## 1. Sistema operacional

```bash
# No Pi: instalar Raspberry Pi OS (64-bit, desktop ou lite + Chromium)
sudo apt update && sudo apt install -y chromium-browser unclutter
```

## 2. Kiosk Chromium

Crie `/home/pi/poto-kiosk.sh`:

```bash
#!/bin/bash
# Ajuste SERVER para o IP do notebook/servidor na LAN
SERVER="http://192.168.1.100:8000"
exec chromium-browser \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --autoplay-policy=no-user-gesture-required \
  "${SERVER}/app/index.html"
```

```bash
chmod +x ~/poto-kiosk.sh
```

### Autostart (desktop)

Em `~/.config/labwc/autostart` ou via `raspi-config` → Desktop Autologin:

```
@/home/pi/poto-kiosk.sh
@unclutter -idle 0
```

## 3. Botão de pânico (GPIO)

Exemplo mínimo com `gpiozero` (BCM GPIO 17 → GND via botão normally-open):

```python
# /home/pi/poto-panic.py — aciona endpoint ou simula tecla
from gpiozero import Button
import urllib.request, json, uuid

TOTEM_ID = "TOTEM-CCS-01"
API = "http://192.168.1.100:8000/api/v1/eventos"

def acionar():
    ev = {
        "evento_id": str(uuid.uuid4()),
        "totem_id": TOTEM_ID,
        "tipo_ocorrencia": "seguranca",
        "modo": "normal",
        "origem_acionamento": "botao_fisico",
        "timestamp_local": __import__("datetime").datetime.now().isoformat(),
    }
    req = urllib.request.Request(
        API, data=json.dumps(ev).encode(),
        headers={"content-type": "application/json"}, method="POST",
    )
    urllib.request.urlopen(req, timeout=5)

Button(17, pull_up=True).when_pressed = acionar
from signal import pause; pause()
```

```bash
pip install gpiozero
python3 ~/poto-panic.py &
```

> Alternativa: mapear GPIO para tecla F12 e capturar no totem — o botão `#panic` da PWA já envia `botao_fisico`.

## 4. Variáveis no totem

No console do Chromium (ou via script de injeção):

```javascript
localStorage.setItem("poto_api", "http://192.168.1.100:8000/api/v1");
localStorage.setItem("poto_totem_id", "TOTEM-CCS-01");
```

## 5. HTTPS em LAN (WebRTC)

`getUserMedia` exige contexto seguro fora de `localhost`. Opções:

- Reverse proxy Caddy/nginx com certificado autoassinado na LAN
- Túnel Tailscale/Cloudflare para demo

STUN default (`stun.l.google.com`) basta na maioria das LANs; configure TURN no `.env` se NAT simétrico bloquear WebRTC.

## 6. Checklist de demonstração

| # | Teste |
|---|-------|
| 1 | Botão GPIO + touch → chamado na central ≤ 3 s |
| 2 | 4 trilhas roteiam corretamente |
| 3 | Voz → STT → triagem (requer `POTO_STT_PROVIDER=faster-whisper`) |
| 4 | Trilha mulher: tela neutra, sem som |
| 5 | Sinal crítico escala (ex.: ideação suicida) |
| 6 | Offline: fila local + sync idempotente |
| 7 | Central: ACK e estados em tempo real |
| 8 | WebRTC: vídeo visível no painel |

## 7. Notificação externa

Com `POTO_CONTACT_OVERRIDE=5586981804692` e `POTO_NOTIF_PROVIDER=log`, alertas aparecem nos logs do backend. Para WhatsApp real, configure Evolution API:

```env
POTO_NOTIF_PROVIDER=webhook
POTO_NOTIF_WEBHOOK_URL=http://localhost:8080/message/sendText/sua-instancia
POTO_NOTIF_WEBHOOK_TOKEN=sua-api-key
```

Payload enviado: `{ "number": "5586981804692", "text": "...", "meta": {...} }`.
