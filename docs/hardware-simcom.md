# Canal GSM/2G real — SIMCom A7670SA (voz + SMS)

Substitui o número virtual do Twilio na perna de **alerta PSTN**: com um SIM real, o
totem disca de **número próprio**. É o degrau "GSM(SMS+voz)" da escada de emissão
(ver `docs/` / memória de arquitetura). A chamada A/V ao vivo totem↔central continua
sendo **WebRTC P2P nativo** (`video.ts`) — o A7670SA cuida só do alerta ao telefone.

> ⚠️ **Segurança de discagem.** Em bancada, deixe `POTO_CONTACT_OVERRIDE=<seu número>`
> no `.env` para **não** discar 190/192/193/180 de verdade. Só remova o override em
> produção, com os contatos reais validados.

## 1. O que o A7670SA faz (e não faz)

| | |
|---|---|
| Bandas | LTE + GSM da América do Sul (Brasil ok). |
| SMS | ✅ funciona em LTE Cat-1 **ou** GSM. |
| Voz | ⚠️ **sem VoLTE** — só via **fallback 2G/GSM (CSFB)**. Exige cobertura 2G local. |
| Áudio | codec integrado: 1 MIC analógico + 1 SPK analógico (e PCM/USB). |
| Locução pt-BR | o `AT+CTTS` do chip é **só Chinês/Inglês** → para falar português na ligação, toca-se o **WAV do Piper** pela linha de áudio (ver §5). |

Por isso o provider força **2G-only** (`AT+CNMP=13`) antes de discar quando
`POTO_SIMCOM_FORCE_GSM=true` (padrão). Se sua região já não tem 2G, a **voz** não
completa — use `POTO_SIMCOM_MODE=sms` (o SMS sai em LTE).

## 2. Conexão física (USB)

O módulo USB enumera **vários** `/dev/ttyUSB*` (AT, dados/PPP, diag, às vezes áudio).
Descubra a porta AT:

```bash
python3 scripts/simcom_test.py --scan     # a porta que responde 'OK' ao AT é a AT
# ou manualmente:
ls -l /dev/ttyUSB*
```

Anote a porta AT em `POTO_SIMCOM_PORT` (costuma ser `/dev/ttyUSB2` ou `ttyUSB3`).
Garanta permissão de acesso à serial:

```bash
sudo usermod -aG dialout "$USER"   # relogar depois
```

## 3. Dependência de software

Só na rasp (o `pyserial` é extra opcional; o backend roda sem ele nas demos sem módulo):

```bash
cd backend && uv sync --extra simcom
```

## 4. Configuração (`backend/.env`)

```env
POTO_NOTIF_PROVIDER=simcom
POTO_CONTACT_OVERRIDE=5586981804692   # SEU número em teste!
POTO_SIMCOM_PORT=/dev/ttyUSB2
POTO_SIMCOM_MODE=both                 # both = liga + SMS com o protocolo (recomendado)
POTO_SIMCOM_FORCE_GSM=true            # 2G p/ a voz (CSFB)
POTO_SIMCOM_CALL_SEG=20
```

Confira em `GET /api/v1/health` (bloco `notificacao.simcom`) o modo/porta ativos.

## 5. Locução pt-BR dentro da ligação (opcional)

A ligação "crua" só **toca** (ring) — já é um alerta real. Para **falar** o protocolo
em pt-BR na chamada, reaproveite a locução do Piper (a mesma do Twilio `<Play>`):

1. Ligue o Piper: `POTO_VOICE_TTS=local` + `POTO_PIPER_MODEL=~/piper/pt_BR-...onnx`.
   O notifier gera o WAV e passa o caminho ao provider.
2. Aponte o áudio do WAV para a ligação com `POTO_SIMCOM_AUDIO_CMD` (template `{wav}`):
   - **Áudio USB do módulo** (se o A7670SA expõe placa ALSA):
     `POTO_SIMCOM_AUDIO_CMD=aplay -D plughw:CARD=Module,DEV=0 {wav}`
     (descubra o nome com `aplay -l`; pode exigir `AT+CPCMREG=1`.)
   - **Saída SPK analógica**: alto-falante ligado aos pinos SPK do módulo; roteie a
     placa de áudio do Pi para lá conforme sua montagem.
3. `POTO_SIMCOM_SPK_DEVICE=3` (viva-voz) via `AT+CSDVC`, se necessário.

Sem `POTO_SIMCOM_AUDIO_CMD`, a ligação fica só no ring por `POTO_SIMCOM_CALL_SEG` — e
o **SMS** (modo `both`) carrega os detalhes do protocolo. Este é o caminho robusto.

## 6. Microfone USB (STT do totem) — componente separado

O mic USB é as "orelhas" do totem (captura → Whisper → `/conversa`), **independente**
do A7670SA. Não confunda: ele não entra na linha de áudio da ligação celular.

```bash
arecord -l                    # achar o card do mic USB
POTO_STT_PROVIDER=faster-whisper   # habilita a transcrição (ver .env.example / stt.py)
```

## 7. Roteiro de teste (na rasp)

```bash
# 1. porta e diagnóstico (read-only: SIM, sinal, registro, modo de rede)
python3 scripts/simcom_test.py --scan
python3 scripts/simcom_test.py --port /dev/ttyUSB2

# 2. SMS real para o SEU número
python3 scripts/simcom_test.py --port /dev/ttyUSB2 --sms +5586981804692 --text "POTO teste"

# 3. ligação de voz real (força 2G) para o SEU número
python3 scripts/simcom_test.py --port /dev/ttyUSB2 --call +5586981804692 --seconds 15

# 4. fim-a-fim pelo backend: dispare um chamado e cheque a tabela de notificações
```

Sinais saudáveis: `+CPIN: READY`, `+CSQ` com RSSI ≠ 99, `+CREG: 0,1` (registrado).
Se a voz não completa mas o registro CS está ok, quase sempre é ausência de 2G na
região — confirme com a operadora ou caia para `POTO_SIMCOM_MODE=sms`.
```
