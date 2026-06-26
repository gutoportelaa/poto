# Demonstração — alerta por voz (Twilio free tier)

Roteiro para demonstrar o **alerta telefônico** do P.O.T.O com a conta **trial** do
Twilio. O vídeo/áudio ao vivo NÃO usa Twilio — é o WebRTC P2P próprio
(`video.ts` ↔ painel). Aqui o Twilio cobre só a **perna de voz do alerta**.

## O que o trial permite (e o que molda a demo)

- **Só disca para números verificados** no console (Verified Caller IDs). Por isso
  **190/192/193/180 estão fora** — códigos de emergência o Twilio nunca disca. A demo
  usa números de bancada da equipe.
- **Preâmbulo de trial**: a ligação começa com "You have a Twilio trial account…"
  antes da locução. Some no upgrade.
- Voz: TwiML `<Say voice="Polly.Camila" language="pt-BR">` (Polly pt-BR soa bem
  melhor que a voz padrão). `statusCallback` dá o estado ao vivo (tocando/atendida).

## Pré-requisitos (uma vez)

1. **Verificar os números** em *Phone Numbers → Verified Caller IDs* no console Twilio:
   - `+55 99 99210-4327` (canal CSV / PM / Bombeiros na demo)
   - `+55 99 98467-2268` (canal Sala Lilás / SAMU / Central 180)
2. `backend/.env` já está configurado para a demo (override **desligado**, um número
   por canal, `POTO_TWILIO_VOICE=Polly.Camila`). Credenciais Twilio já presentes.

## Subir a demo

```bash
# 1) Túnel público p/ o backend (status ao vivo da ligação chega via statusCallback)
cloudflared tunnel --url http://localhost:8000      # ou: ngrok http 8000
#    copie a URL https e cole em backend/.env:
#    POTO_PUBLIC_BASE_URL=https://<algo>.trycloudflare.com

# 2) Backend + frontend
make dev        # backend :8000 (carrega .env) + frontend :5173
```

> Sem `POTO_PUBLIC_BASE_URL` a ligação ainda sai — mas não aparece o status
> "Tocando → Atendida" nas telas (totem e painel). Para a demo completa, use o túnel.

## Roteiro

1. No totem (`http://localhost:5173`), acione **PÂNICO**.
2. O broadcast liga em paralelo para **CSV** e **Sala Lilás** (os dois celulares da
   equipe). Cada um atende e ouve a locução pt-BR do alerta (protocolo, tipo, totem).
3. A tela de **alerta ativo** do totem mostra os chips de ligação ao vivo:
   `Tocando` (âmbar) → `Atendida` (verde) → `Encerrada`. O **painel** reflete o mesmo
   nos chips do card do chamado.
4. Em **Acionar autoridades do estado**, os botões (PM/SAMU/Bombeiros/Central 180)
   também tocam de verdade (reaproveitam os 2 números verificados).

## Telas que mostram "o que está ocorrendo"

- **Totem · alerta ativo**: status do chamado + cronômetro + **chips de ligação por
  canal** (Twilio statusCallback via WS `ligacao`).
- **Painel · card do chamado**: mesmos chips de ligação por canal, em tempo real.

## Mapa técnico

| Peça | Onde |
|---|---|
| Locução de voz (Polly pt-BR) | `notifier.py::TwilioProvider` (`POTO_TWILIO_VOICE`) |
| statusCallback → status ao vivo | `notifier.py` (StatusCallback) → `POST /api/v1/twilio/status` → WS `ligacao` |
| Chips no totem | `totem.ts::alertaAtivo` (`onLigacao`) |
| Chips no painel | `painel.ts::conectarWS` (evento `ligacao`) |
| A/V ao vivo (separado do Twilio) | `video.ts` ↔ `painel.ts::assistir` (WebRTC P2P) |

## Limpeza pós-demo

Para voltar ao modo bancada (um número só), em `backend/.env`:
`POTO_CONTACT_OVERRIDE=<seu número verificado>`.
