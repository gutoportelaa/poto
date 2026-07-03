# Inferência sem Hailo — modelos por tarefa na CPU da Pi

Decisão de projeto (02/07/2026): **descartar o Hailo** e priorizar modelos
**mini/nano ou especializados** rodando na **CPU da Raspberry Pi 5 (8GB)**. O papel
que o Hailo ocuparia (classificador de borda) passa a ser cumprido por um modelo
pequeno na CPU — escolhido **por dados**, não por chute.

## Dois papéis, hoje separados

O totem tem duas tarefas de IA, com exigências diferentes:

| Tarefa | Natureza | Rede de segurança | Modelo |
|---|---|---|---|
| **Triagem** | classificação (tipo × gravidade), label space fixo | roteador determinístico (`router_engine.py`) | `POTO_TRIAGEM_MODEL` |
| **Conversa** | generativa (acolhimento, follow-up) | — | `POTO_CONVERSA_MODEL` (**sempre local**) |

Ambas caem no `POTO_OLLAMA_MODEL` se as vars por tarefa ficarem vazias. A **conversa
roda sempre local** (offline total) — nunca depende de rede.

No código: `app/agents/graph.py` seleciona o modelo por tarefa via `_chat(model)`
(cache por modelo); `classificar_triagem(texto, modelo=...)` isola a etapa de
classificação (sem os guardrails determinísticos) e é o que o benchmark mede.

## Escolher a triagem por dados: `make bench`

```bash
# na Pi, com Ollama no ar e os modelos baixados
make bench
make bench ARGS="--models qwen2.5:0.5b,qwen2.5:1.5b,llama3.2:1b,gemma2:2b"
make bench ARGS="--json"
```

Mede, sobre um conjunto rotulado de frases pt-BR (`scripts/bench.py`, embutido ou
`--dataset`), para cada modelo presente: **acurácia de tipo**, **acurácia de
gravidade**, **falhas** (JSON inválido) e **latência** (média / p95) na CPU.

> Já observado no workstation: `llama3.2:3b` acerta ~27% do tipo com muitas falhas
> de JSON — fraco para classificação. Rode o bench na Pi para comparar com os nano
> (`qwen2.5:0.5b/1.5b`, `llama3.2:1b`, `gemma2:2b`) e definir o `POTO_TRIAGEM_MODEL`.

## Próximo passo possível (se os nano não bastarem)

Classificador **especializado** de CPU: embeddings pt multilingues (MiniLM em ONNX,
~20ms) + cabeça linear, ou fastText/TF-IDF+LogReg — latência de milissegundos e
determinístico. Entra como mais um "modelo" comparável no mesmo `make bench`.

## Acompanhamento

`make selftest` (auto-teste modular) reporta, no módulo `agentes`, o modo, o modelo
e a latência da triagem — use para ver o impacto de cada troca de modelo.
