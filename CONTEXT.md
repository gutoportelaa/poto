# P.O.T.O — Contexto do Projeto

**P.O.T.O** = **P**lataforma de **O**rientação, **T**riagem e **O**uvidoria — um totem
inteligente de emergência para a UFPI (Campus Ministro Petrônio Portella, Teresina).
Uma pessoa em situação de risco (segurança, saúde, violência contra a mulher, ouvidoria)
aciona o totem por **toque, voz, chat de texto ou botão de pânico**; o sistema faz a
**triagem** (regras + IA), **roteia** para o canal certo (CSV/PREUNI, Sala Lilás, SAPSI,
SAMU/PM/Bombeiros/Central 180) e **notifica** a autoridade, com **vídeo/áudio ao vivo**
para a central quando necessário.

Este documento é o mapa vivo do repositório: **o que já existe**, **para onde vai**,
**como usar** e **como testar**. Documentação de produto detalhada em
[`docs/relatorio-poto.html`](docs/relatorio-poto.html) (projeção final) e
[`docs/relatorio-prototipo.html`](docs/relatorio-prototipo.html) (entrega inicial).

---

## 1. Estado atual — o que já foi implementado

### Backend (`backend/`, FastAPI + `uv`, SQLite stdlib sem ORM)
- **API de eventos e chamados** (`app/main.py`, prefixo `/api/v1`) — criação de evento,
  pânico, triagem, conversa, ACK, escalonamento, métricas, auditoria, heartbeat de totens.
- **Roteador determinístico** (`app/router_engine.py`) — a rede de segurança: mesmo sem
  IA, todo evento é roteado por regras (tipo/modo → canal + fallback + SLA).
- **Agentes de IA** (`app/agents/graph.py`) — LangGraph + `langchain-ollama`, com **merge
  protetivo**: a LLM nunca rebaixa tipo/gravidade; em sinal crítico o roteamento segue a
  heurística. Fluxo `conversa → triagem → guardrails → roteamento`.
- **STT plugável** (`app/stt.py`) — transcrição de voz local via faster-whisper (opcional).
- **Locução de voz local** (`app/voz.py`) — TTS offline (Piper) na borda; gera o WAV do
  alerta com custo de TTS zero.
- **SLA e escalonamento** (`app/sla.py`) — chamados sem ACK no prazo (2 min imediato /
  10 min potencial) escalonam para o canal fallback automaticamente.
- **Persistência e auditoria** (`app/db.py`) — SQLite append-friendly; tabelas de
  chamados, notificações, evidências, eventos de conversa (minimização LGPD).

### Notificação externa (`app/notifier.py`, adapters plugáveis)
Payload mínimo (LGPD): protocolo, tipo, gravidade, totem — **sem relato detalhado**.
Provedores selecionáveis por `POTO_NOTIF_PROVIDER`:
- **`log`** (padrão) — registra no console + tabela `notificacoes`.
- **`webhook`** — POST JSON `{number, text, meta}` (compatível Evolution API / n8n).
- **`telegram`** — bot + chat_id.
- **`twilio`** — liga (voz, TwiML/Polly ou `<Play>` do WAV Piper) ou SMS. Status ao vivo
  (tocando/atendida) via `statusCallback` → WS → chips nas telas.
- **`simcom`** ⚠️ *em validação* — **canal GSM/2G real** via módulo SIMCom A7670SA + SIM
  próprio (ver §2). Substitui o número virtual do Twilio na perna de alerta PSTN.

### Frontend (`frontend/`, Bun + TypeScript, PWA)
- **Totem** (kiosk) e **Painel** (central em tempo real). Identidade: preto + laranja-
  ferrugem, wordmark Zilla Slab, corpo Inter. Online/offline com **service worker + fila
  local** (store-and-forward) e envio **idempotente** (UUID por evento).
- `src/voice.ts` — **conversa hands-free**: VAD → Whisper (`/transcrever`) → agente
  (`/conversa`) → TTS `speechSynthesis` pt-BR. Conclui na hora em sinal crítico.
- `src/chat.ts` — **chat de texto** reusando `/conversa` (multi-turno), timeout de
  inatividade de 10 min, abandono logado (LGPD).
- `src/audio.ts` — captura de áudio com animação por estados.
- `src/video.ts` — câmera + **evidência** (`/evidencia`) + **chamada A/V ao vivo
  bidirecional** totem↔central via **WebRTC P2P nativo** (sinalização `ws /rtc/{sala}`,
  STUN em `/rtc/config`; vídeo P2P). No modo discreto (trilha mulher) o vídeo não inicia.

### Agentes / observabilidade
- `langgraph.json` expõe `app.agents.graph:graph`. `make studio` abre o **LangGraph
  Studio** (:2024) para plotar e executar o fluxo passo a passo. `make graph` exporta
  Mermaid → `docs/agent-graph.mmd`.
- Modelos Ollama: `llama3.2:3b` (padrão) e `qwen2.5:14b` (melhor). LLM pesado pode rodar
  remoto via túnel SSH reverso (ver `docs/teste-ollama-remoto.md`).

---

## 2. Canal celular real — SIMCom A7670SA (em validação)

Objetivo: dar ao totem um **número de telefone de verdade** (SIM próprio) para o alerta
PSTN, **sem o número virtual do Twilio** (que apresentou problemas). É o degrau
"GSM(SMS+voz)" da escada de emissão. A chamada A/V ao vivo totem↔central continua sendo
WebRTC P2P nativo — o A7670SA cuida **só** da perna de alerta ao telefone.

**Implementado** (`app/simcom.py`, `SimcomProvider` em `notifier.py`):
- Modem AT sobre serial com transporte **injetável** (pyserial em produção; fake nos
  testes). Discagem de voz (`ATD…;`), SMS (`AT+CMGS` + Ctrl-Z), força 2G (`AT+CNMP=13`),
  lock que serializa o modem no broadcast de pânico, degradação graciosa sem o módulo.
- Modos `voice | sms | both` (padrão `both`: liga **e** manda SMS com o protocolo).
- Locução pt-BR do Piper tocada **dentro** da ligação via `POTO_SIMCOM_AUDIO_CMD`.
- 7 testes com link fake, `scripts/simcom_test.py` (diagnóstico/SMS/voz), doc completa em
  [`docs/hardware-simcom.md`](docs/hardware-simcom.md).

**Constraint de hardware verificado:** o A7670SA **não tem VoLTE** → voz só via fallback
**2G/GSM (CSFB)** (exige cobertura 2G); `AT+CTTS` do chip é só CN/EN, por isso a fala
pt-BR na ligação é o WAV do Piper pela linha de áudio. **SMS** sai em LTE ou GSM.

**Status da validação na rasp** (`raspvigia@100.101.0.3`): módulo detectado
(`1e0e:9011 A76XX`), porta AT respondendo (`AT→OK` em `ttyUSB2`). Dois pontos abertos:
1. **ModemManager** disputa a serial (sintoma `multiple access on port`) → mascarar
   (`sudo systemctl mask --now ModemManager`) ou udev `ID_MM_DEVICE_IGNORE`.
2. **Alimentação**: o módulo puxa picos ~2A no TX 2G; alimentado pela USB da Pi pode
   causar brownout/reboot. Usar fonte dedicada / hub com fonte, e conferir PWRKEY.

Rastreado no **PR #3** (`feat/simcom-a7670sa-voz`).

---

## 3. Estrutura do repositório

```
backend/
  app/
    main.py           # API FastAPI (endpoints /api/v1)
    router_engine.py  # roteamento determinístico (rede de segurança)
    agents/graph.py   # LangGraph + Ollama (triagem + conversa)
    notifier.py       # notificação externa (log/webhook/telegram/twilio/simcom)
    simcom.py         # canal GSM/2G real (SIMCom A7670SA, AT/serial)
    voz.py            # locução TTS local (Piper)
    stt.py            # transcrição de voz (faster-whisper)
    video.py          # evidência + sinalização WebRTC
    sla.py db.py models.py config.py seed.py
  tests/              # pytest (test_simcom, test_notifier, test_smoke_api, ...)
frontend/
  src/                # totem.ts painel.ts voice.ts chat.ts video.ts audio.ts api.ts
docs/                 # relatórios, hardware-pi.md, hardware-simcom.md, demo-twilio.md
scripts/              # doctor.sh, demo-tunel.sh, simcom_test.py
Makefile              # orquestra setup/dev/studio/test/...
```

### Endpoints principais (`/api/v1`)
`GET /health` · `GET /canais` · `GET /metricas` · `POST /eventos` · `POST /panico` ·
`POST /triagem` · `POST /conversa` · `POST /conversa/abandono` ·
`POST /chamados/{id}/escalonar` · `POST /chamados/{id}/ack` · `GET /chamados[/{id}]` ·
`GET /chamados/{id}/auditoria` · `POST /transcrever` · `POST /evidencia` ·
`GET /evidencias` · `GET /rtc/config` · `WS /rtc/{sala}` · `WS /ws` ·
`GET /totens` · `POST /totens/{id}/heartbeat` · `POST /twilio/status` · `GET /audio/{nome}`.

---

## 4. Pretensões futuras (roadmap)

1. **Fechar a validação do SIMCom** — ModemManager mascarado + alimentação dedicada;
   validar SMS e ligação reais; definir `POTO_SIMCOM_AUDIO_CMD` conforme o áudio do módulo
   (USB ALSA vs SPK analógico) para a locução pt-BR na chamada.
2. **Seam de inferência** (`app/inference.py`) — separar **triagem** (classificação) de
   **conversa** (generativa), espelhando `notifier.py`/`stt.py`, com providers
   `ollama-remote` / `ollama-local` / `hailo` / `heuristica` e **curto-circuito de
   emergência** (despachar pelo seed heurístico em sinal crítico sem esperar o timeout).
3. **Hailo-8L** (edge TPU, quando chegar) — roda o **classificador compacto** de triagem
   (NÃO um LLM); entra como provider plugável sem refatorar o resto. Conversa generativa
   segue remota.
4. **LLM destilada/quantizada local** para comparativo de relatório (skill `sbc-article`):
   heurística → destilada local (qwen2.5:0.5b/1.5b, llama3.2:1b, gemma2:2b Q4) →
   llama3.2:3b → qwen2.5:14b remoto. `make bench` (latência tok/s na CPU da Pi + acurácia).
5. **Emissão multi-protocolo** (escada de fallback completa): API → MQTT → **GSM(SMS+voz,
   já em curso)** → LoRa → sirene/relé, com dedupe por idempotency-key.
6. **Caixa-preta** (adiada): watchdog de disponibilidade + log forense append-only
   tamper-evident.
7. **Hardware do totem** — gabinete, botão de pânico GPIO, tela touch kiosk, HTTPS em LAN
   para WebRTC (ver `docs/hardware-pi.md`).
8. **Projeção final** — triagem **offline em TPU** como fallback resiliente; A/V processado
   no **edge** (privacy-by-design, só metadados saem); Central NOC + event store.

---

## 5. Manual de uso

### Pré-requisitos
`uv` (backend), `bun` (frontend) e, opcional para IA, `ollama`. Para o SIMCom (só na
rasp): módulo A7670SA + SIM + `uv sync --extra simcom`.

### Subir em desenvolvimento
```bash
make setup          # uv sync + bun install
make agents-pull    # baixa llama3.2:3b (opcional)
make seed           # chamados de exemplo (opcional)
make dev            # backend :8000 + frontend :5173
```
- Totem: http://localhost:5173/  ·  Painel: http://localhost:5173/painel  ·
  API/Docs: http://localhost:8000/docs

### Alvos úteis do Makefile
| Comando | O que faz |
|---|---|
| `make backend` / `make frontend` | sobe só a API / só a PWA |
| `make doctor` | verifica ferramentas, agentes, STT, câmera, microfone, serviços |
| `make studio` | LangGraph Studio (:2024) |
| `make graph` | exporta o grafo (Mermaid) |
| `make stt-setup` | instala Whisper local |
| `make test` / `make acceptance` | testes / critérios de aceite |
| `make smoke` | roteia um evento sem subir servidor |

### Variáveis de ambiente-chave (`backend/.env`, veja `.env.example`)
| Variável | Padrão | Descrição |
|---|---|---|
| `POTO_OLLAMA_MODEL` | `llama3.2:3b` | modelo do Ollama |
| `POTO_AGENTS_ENABLED` | `true` | liga/desliga a IA |
| `POTO_STT_PROVIDER` | `faster-whisper` | `none` ou `faster-whisper` |
| `POTO_CONTACT_OVERRIDE` | — | manda **todos** os alertas para um número (testes) |
| `POTO_NOTIF_PROVIDER` | `log` | `log`/`webhook`/`telegram`/`twilio`/`simcom` |
| `POTO_VOICE_TTS` / `POTO_PIPER_MODEL` | `say` / — | locução local (Piper) |
| `POTO_SIMCOM_PORT` | `/dev/ttyUSB2` | porta AT do A7670SA |
| `POTO_SIMCOM_MODE` | `both` | `voice` / `sms` / `both` |
| `POTO_SIMCOM_FORCE_GSM` | `true` | força 2G p/ voz (CSFB) |
| `POTO_SIMCOM_AUDIO_CMD` | — | template `{wav}` p/ tocar a locução na ligação |

---

## 6. Como testar o que já foi implementado

### Testes automatizados (backend)
```bash
make test          # suíte completa (pytest) — inclui os 7 testes do SIMCom (link fake)
make acceptance    # critérios de aceite (roteamento, §8 do protótipo)
```
Os testes do SIMCom **não exigem hardware**: o modem AT é exercido sobre um transporte
falso roteirizado (`tests/test_simcom.py`).

### Fluxo agêntico (triagem/conversa)
```bash
make studio        # UI passo a passo, ou:
cd backend && uv run python -c "from app.agents.graph import triagem_conversacional; \
from app.models import Modo; import json; \
print(json.dumps(triagem_conversacional('um homem está me seguindo perto do bloco 7', Modo.normal), ensure_ascii=False, indent=2))"
```

### Fluxo ponta a ponta (manual)
1. `make dev`, abra o **totem** e o **painel** em duas abas.
2. Dispare um chamado (toque/voz/chat/pânico); veja aparecer no painel em tempo real.
3. Confira a **notificação** (com `POTO_NOTIF_PROVIDER=log`, sai no console + tabela
   `notificacoes`). Dê **ACK**; deixe estourar o SLA para ver o **escalonamento**.
4. **Vídeo ao vivo**: no totem "Abrir vídeo com a central"; no painel "Ver vídeo".

### Canal SIMCom (na rasp, com o módulo)
> Segurança: mantenha `POTO_CONTACT_OVERRIDE` no **seu** número para não discar
> 190/192/193/180 de verdade. Ver `docs/hardware-simcom.md`.
```bash
sudo systemctl mask --now ModemManager          # libera a porta serial
cd backend && uv sync --extra simcom
python3 scripts/simcom_test.py --scan           # acha a porta AT
python3 scripts/simcom_test.py --port /dev/ttyUSB2               # diagnóstico read-only
python3 scripts/simcom_test.py --port /dev/ttyUSB2 --sms +55SEUNUM --text "POTO teste"
python3 scripts/simcom_test.py --port /dev/ttyUSB2 --call +55SEUNUM --seconds 15
```
Sinais saudáveis: `+CPIN: READY`, `+CSQ` com RSSI ≠ 99, `+CREG: 0,1`. Depois, com
`POTO_NOTIF_PROVIDER=simcom` no `.env`, dispare um chamado pelo backend e confira a
tabela de notificações.
```
