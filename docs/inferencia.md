# Inferência sem Hailo — classificador especializado governa a triagem

Decisão de projeto: **descartar o Hailo** e rodar a triagem na **CPU da Raspberry
Pi 5**. Medimos os modelos nano na Pi e eles **não serviram** (lentos e imprecisos);
o dado levou a um **classificador especializado** como governante local, com o LLM
(local ou remoto) como refino facilitado por cima.

## Dados que motivaram (medido no held-out `scripts/bench_dataset.json`)

| Abordagem | acc.tipo | acc.grav | latência | onde |
|---|---|---|---|---|
| qwen2.5:0.5b | 29% | 27% | ~5800 ms | CPU do Pi 5 |
| qwen2.5:1.5b | 45% | 48% | ~6100 ms | CPU do Pi 5 |
| llama3.2:3b | 86% | 60% | ~2000 ms | workstation |
| **classificador especializado** | **83%** | **86%** | **~6 ms** | qualquer CPU |

O classificador empata o 3B em tipo, **ganha em gravidade** e é **centenas de vezes
mais rápido** — offline, ~400 KB. Os nano na Pi ficaram perto do acaso e a ~6 s.

## Arquitetura

Triagem (`app/agents/graph.py :: triagem_conversacional`), em ordem de precedência:

1. **Classificador especializado** (`app/classificador.py`) — TF-IDF (palavra + char
   n-grams) + Regressão Logística. **Governa** a classificação; roda offline, sem
   LangGraph/Ollama.
2. **LLM via LangGraph** (`POTO_TRIAGEM_MODEL`; Ollama local ou remoto) — refino/
   fallback, só quando o classificador não está treinado.
3. **Heurística determinística** — rede de segurança final.

Sobre tudo isso roda o **merge protetivo**: nenhuma fonte rebaixa a proteção — em
sinal crítico prevalece a heurística e a gravidade mais alta. A **conversa**
generativa segue por `POTO_CONVERSA_MODEL` (local, offline por padrão).

`status_agentes()` e `make selftest` reportam `modo` (`classificador`/`agentes`/
`heuristica`) e o estado do classificador.

## Treinar / avaliar

```bash
cd backend && uv sync --extra clf
make train-clf          # treina em scripts/triagem_dataset.json e avalia no held-out
make bench              # tabela comparando classificador* vs modelos do Ollama
```

- **Treino**: `scripts/triagem_dataset.json` (rotulado, pt-BR). O artefato
  (`app/data/triagem_clf.joblib`, ~400 KB) é **gerado**, não versionado (gitignore) —
  sempre em sincronia com o dataset. Melhorou? Amplie o dataset e rode `make train-clf`.
- **Avaliação honesta**: mede-se no `bench_dataset.json` (conjunto SEPARADO do treino).
- **Degradação graciosa**: sem `scikit-learn` ou sem o artefato, `disponivel()` é
  False e a triagem cai no LLM/heurística.

## Modelo por tarefa (LLM, quando usado)

`POTO_TRIAGEM_MODEL` / `POTO_CONVERSA_MODEL` (vazio = `POTO_OLLAMA_MODEL`). A conversa
roda local por padrão; o modo remoto (ex.: `qwen2.5:14b` via túnel) é fácil de ligar
apontando `POTO_OLLAMA_URL`, sempre subordinado ao classificador na triagem.

## Próximos passos possíveis

- Ampliar `triagem_dataset.json` (mais frases, gírias regionais) para subir a
  acurácia de tipo acima de 83%.
- Embeddings ONNX (MiniLM) como vetor alternativo ao TF-IDF, se valer o ~100 MB.
- Refino ativo: consultar o LLM só quando a confiança do classificador for baixa,
  sem rebaixar (merge protetivo).
