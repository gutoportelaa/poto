# Comparação de triagem — treino: `treino`

Teste: 97 frases distintas · teste com ruído: 194 · CV 5-fold em 242 frases. IC 95% por bootstrap.

| alternativa | CV tipo | CV grav | CV rec.imediato | teste tipo | teste grav | **teste rec.imediato** | imediato→orientação | ruído tipo | lat. mediana | p95 | tamanho |
|---|---|---|---|---|---|---|---|---|---|---|---|
| heuristica | 35% | 40% | 23% | 32% [23%–41%] | 49% [39%–59%] | **34% [21%–52%]** | 59% | 30% | 0.01 ms | 0.01 ms | 0 KB |
| tfidf | 69% | 81% | 80% | 80% [72%–88%] | 86% [78%–92%] | **79% [62%–93%]** | 3% | 71% | 1.44 ms | 1.51 ms | 751 KB |
| pipeline | 71% | 75% | 83% | 78% [70%–87%] | 85% [77%–92%] | **83% [69%–97%]** | 3% | 70% | 1.54 ms | 1.73 ms | 751 KB |

## Matriz de confusão da gravidade (teste; linhas = real, colunas = previsto)

**heuristica**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 10 | 2 | 17 |
| risco_potencial | 3 | 4 | 25 |
| orientacao | 1 | 1 | 34 |

**tfidf**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 23 | 5 | 1 |
| risco_potencial | 5 | 26 | 1 |
| orientacao | 1 | 1 | 34 |

**pipeline**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 24 | 4 | 1 |
| risco_potencial | 6 | 25 | 1 |
| orientacao | 2 | 1 | 33 |

