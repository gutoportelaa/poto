# P.O.T.O — Plataforma de Orientação, Triagem e Ouvidoria

Totem Inteligente de Emergência para a UFPI (Campus Ministro Petrônio Portella).
Protótipo: **backend FastAPI** + **interface PWA** (totem + painel), com **agentes de
IA** (LangGraph + Ollama) para triagem e conversação.

> A logo (`poto-logo-3.png`) traz a expansão "Orientação, Triagem e Ouvidoria",
> adotada como identidade. Documentação de produto: [`docs/relatorio-poto.html`](docs/relatorio-poto.html)

## Arquitetura

```
frontend/ (Bun + TS)              backend/ (FastAPI + uv)
  totem  (kiosk, online/offline) ── HTTP/WS ──► API de Eventos
  painel (tempo real)                            Roteador determinístico
                                                 Banco (SQLite)
                                                 Agentes (LangGraph + Ollama)
```

- **Online**: o totem posta o evento no backend; os agentes rodam no servidor (Ollama local).
- **Offline**: service worker + fila local (`store-and-forward`); a confirmação é
  imediata e a fila é drenada ao reconectar. O envio é **idempotente** (UUID por evento).
- **Fallback determinístico**: se Ollama/LangGraph falharem, o roteamento crítico
  continua por regras (`app/router_engine.py`).

## Pré-requisitos

`uv`, `bun` e (opcional, para IA) `ollama`.

## Como rodar

```bash
make setup          # uv sync + bun install
make agents-pull    # baixa o modelo (llama3.2:3b) — opcional
make seed           # chamados de exemplo — opcional
make dev            # backend :8000 + frontend :5173
```

- Totem:  http://localhost:5173/
- Painel: http://localhost:5173/painel
- API/Docs: http://localhost:8000/docs

### Alvos úteis

| Comando | O que faz |
|---|---|
| `make backend` | Sobe só a API (uvicorn, reload) |
| `make frontend` | Builda e serve só a PWA |
| `make agents-check` | Mostra se está em modo `agentes` ou `heuristica` |
| `make studio` | Abre o **LangGraph Studio** (visualiza e testa o fluxo) |
| `make graph` | Exporta o grafo em Mermaid → `docs/agent-graph.mmd` |
| `make stt-setup` | Instala o Whisper local (faster-whisper) p/ transcrição |
| `make smoke` | Roteia um evento sem subir servidor |
| `make test` | Testes do backend (pytest) |
| `make clean` | Remove `dist/`, venv e banco local |

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
|---|---|---|
| `POTO_OLLAMA_MODEL` | `llama3.2:3b` | Modelo do Ollama (ex.: `qwen2.5:14b`) |
| `POTO_OLLAMA_URL` | `http://localhost:11434` | Endpoint do Ollama |
| `POTO_AGENTS_ENABLED` | `true` | Liga/desliga a camada de IA |
| `POTO_DB_PATH` | `backend/poto.db` | Caminho do SQLite |
| `POTO_STT_PROVIDER` | `none` | `none` ou `faster-whisper` (transcrição de voz) |
| `POTO_WHISPER_MODEL` | `base` | Modelo Whisper (`tiny`/`base`/`small`...) |

No frontend, o endpoint da API pode ser sobrescrito em `localStorage.poto_api`.

## Voz / áudio no totem

A tela **"Descrever a situação"** (totem → "Não sei classificar") aceita **fala**.
Fluxo: gravar → enviar ao backend (`POST /transcrever`) → texto na caixa → triagem.

A interface mostra uma **animação branda** do microfone com estados claros e um
painel de **logs** ao vivo:

| Estado | UI | Quando |
|---|---|---|
| a receber (ocioso) | respiração lenta | pronto para gravar |
| solicitando | pulso curto | pedindo permissão do microfone |
| recebendo | anel reativo ao volume da voz | gravando |
| processando | anel tracejado girando | enviando/transcrevendo |
| concluído | tom verde + ✓ | áudio transcrito ou recebido |
| erro | tom ferrugem + tremor | permissão negada / falha de rede |

> A captura de áudio funciona sempre. A **transcrição automática** exige um provedor
> de STT local: `make stt-setup` e depois `POTO_STT_PROVIDER=faster-whisper` no
> `backend/.env`. Sem provedor, o áudio é recebido e a UI pede o texto digitado
> (degradação graciosa — nenhuma fala sai da máquina).

## Visualizar e testar o fluxo agêntico (LangGraph Studio)

O grafo dos agentes (`conversa → triagem → guardrails → roteamento`) é exposto para
o **LangGraph Studio** — o equivalente ao LangSmith Studio / ADK web para *plotar*
e *executar* o fluxo passo a passo.

```bash
make studio          # sobe o servidor de dev em http://127.0.0.1:2024
```

O comando imprime três URLs:

- **API**: `http://127.0.0.1:2024` (servidor local; nada sai da sua máquina)
- **Studio UI**: `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`
- **Docs**: `http://127.0.0.1:2024/docs`

### Como visualizar e testar o chat

1. Rode `make studio` e abra a **Studio UI** no navegador (login gratuito na
   LangSmith; o front é hospedado, mas conecta no seu servidor local).
2. No painel esquerdo aparece o **grafo** `triagem` com os nós e arestas.
3. No campo de **Input**, informe o estado inicial e clique **Submit**:
   ```json
   { "texto": "um homem está me seguindo perto do bloco 7", "modo": "normal" }
   ```
4. Acompanhe a execução **nó a nó** (entrada/saída de cada agente, tempo, e o
   estado final com `tipo`, `gravidade`, `canal_sugerido`, `escalonar_humano`).
5. Edite o input e reexecute para comparar caminhos (ex.: texto com sinal crítico
   leva ao `escalonar_humano = true`).

### Alternativa 100% offline (sem login)

```bash
make graph                       # gera docs/agent-graph.mmd (Mermaid)
```

Cole o conteúdo em qualquer visualizador Mermaid, ou veja o fluxo já renderizado
na seção 6 do relatório (`docs/relatorio-poto.html`). Para testar o chat por linha
de comando, sem UI:

```bash
cd backend && uv run python -c "from app.agents.graph import triagem_conversacional; \
from app.models import Modo; import json; \
print(json.dumps(triagem_conversacional('estou passando mal, quase desmaiando', Modo.normal), ensure_ascii=False, indent=2))"
```

### Tracing no LangSmith (opcional)

Para registrar cada execução na nuvem do LangSmith, preencha no `backend/.env`:
`LANGSMITH_API_KEY`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=poto-triagem`.

## Modo standalone (Pi offline)

Se `frontend/dist` existir, o backend serve a PWA em `/app` — útil para um totem
único que roda tudo localmente:

```bash
make build-frontend && make backend
# totem:  http://localhost:8000/app/index.html
```
