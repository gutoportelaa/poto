# Comparação de triagem (issue #10)

Protocolo do harness (`scripts/compare_triagem.py`): treino `treino`, teste de 97 frases distintas, IC 95% por bootstrap. Latência medida na CPU da workstation (não no Pi 5); o tamanho é o do modelo em KB.

## 1. Encoders isolados



Teste: 97 frases distintas · teste com ruído: 194 · CV 5-fold em 242 frases. IC 95% por bootstrap.

| alternativa | CV tipo | CV grav | CV rec.imediato | teste tipo | teste grav | **teste rec.imediato** | imediato→orientação | ruído tipo | lat. mediana | p95 | tamanho |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pipeline | 71% | 76% | 86% | 79% [71%–87%] | 88% [80%–94%] | **93% [83%–100%]** | 0% | 72% | 1.51 ms | 1.60 ms | 751 KB |
| e5small_lr | 88% | 84% | 81% | 90% [84%–96%] | 88% [81%–94%] | **83% [69%–93%]** | 3% | 86% | 10.25 ms | 10.64 ms | 459597 KB |
| e5base_lr | 91% | 88% | 84% | 88% [80%–94%] | 88% [80%–94%] | **83% [69%–97%]** | 0% | 86% | 20.38 ms | 21.15 ms | 1086130 KB |
| bertimbau | 91% | 93% | 94% | 88% [80%–94%] | 89% [81%–95%] | **90% [76%–100%]** | 0% | 79% | 17.65 ms | 18.15 ms | 425502 KB |

## Matriz de confusão da gravidade (teste; linhas = real, colunas = previsto)

**pipeline**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 27 | 2 | 0 |
| risco_potencial | 6 | 25 | 1 |
| orientacao | 2 | 1 | 33 |

**e5small_lr**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 24 | 4 | 1 |
| risco_potencial | 4 | 27 | 1 |
| orientacao | 1 | 1 | 34 |

**e5base_lr**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 24 | 5 | 0 |
| risco_potencial | 4 | 28 | 0 |
| orientacao | 2 | 1 | 33 |

**bertimbau**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 26 | 3 | 0 |
| risco_potencial | 5 | 26 | 1 |
| orientacao | 0 | 2 | 34 |


## 2. Com merge protetivo de produção (+merge)



Teste: 97 frases distintas · teste com ruído: 194 · CV 5-fold em 242 frases. IC 95% por bootstrap.

| alternativa | CV tipo | CV grav | CV rec.imediato | teste tipo | teste grav | **teste rec.imediato** | imediato→orientação | ruído tipo | lat. mediana | p95 | tamanho |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pipeline | 71% | 76% | 86% | 79% [71%–87%] | 88% [80%–94%] | **93% [83%–100%]** | 0% | 72% | 1.48 ms | 1.57 ms | 751 KB |
| tfidf+merge | 71% | 76% | 86% | 79% [71%–88%] | 88% [81%–94%] | **93% [83%–100%]** | 0% | 72% | 1.49 ms | 1.68 ms | 751 KB |
| e5small_lr+merge | 88% | 76% | 83% | 88% [81%–94%] | 87% [79%–93%] | **90% [76%–100%]** | 0% | 84% | 10.45 ms | 10.90 ms | 459597 KB |
| e5base_lr+merge | 90% | 80% | 86% | 87% [79%–93%] | 87% [80%–93%] | **90% [79%–100%]** | 0% | 86% | 20.47 ms | 21.30 ms | 1086130 KB |
| bertimbau+merge | 90% | 84% | 94% | 85% [77%–92%] | 88% [80%–94%] | **97% [90%–100%]** | 0% | 78% | 17.85 ms | 18.21 ms | 425502 KB |

## Matriz de confusão da gravidade (teste; linhas = real, colunas = previsto)

**pipeline**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 27 | 2 | 0 |
| risco_potencial | 6 | 25 | 1 |
| orientacao | 2 | 1 | 33 |

**tfidf+merge**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 27 | 2 | 0 |
| risco_potencial | 6 | 25 | 1 |
| orientacao | 2 | 1 | 33 |

**e5small_lr+merge**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 26 | 3 | 0 |
| risco_potencial | 6 | 25 | 1 |
| orientacao | 1 | 2 | 33 |

**e5base_lr+merge**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 26 | 3 | 0 |
| risco_potencial | 6 | 26 | 0 |
| orientacao | 3 | 1 | 32 |

**bertimbau+merge**

| real \ prev | risco_imediato | risco_potencial | orientacao |
|---|---|---|---|
| risco_imediato | 28 | 1 | 0 |
| risco_potencial | 7 | 24 | 1 |
| orientacao | 1 | 2 | 33 |


## 3. Teste ampliado (208 frases distintas, 66 de risco imediato) e novas alternativas

O teste ganhou 111 frases geradas por LLM local (gemma3:12b gera, qwen3:8b verifica às cegas; só entram as frases em que o verificador concorda nos dois rótulos — as demais estão em `scripts/dataset_v2/revisao_ext.json` para revisão humana). Frases de LLM são mais "limpas" que as de pessoas; o conjunto dá poder estatístico, não substitui teste com usuários. A célula ouvidoria × risco_potencial ficou com 2 frases (o verificador discorda do gerador nela).

Linhas de base e zero-shot/LLM (`--teste teste,teste_ext`; precisão de risco imediato calculada das matrizes de confusão):

| alternativa | tipo | gravidade | rec. imediato | **prec. imediato** | latência | observação |
|---|---|---|---|---|---|---|
| pipeline (atual) | 75% | 74% | 89% [82–95] | 66% | 1,5 ms | referência |
| e5small_lr+merge | 82% | 74% | 85% [76–92] | 67% | 11 ms | melhor tipo, robusto a ruído (84%) |
| bertimbau+merge | 81% | 73% | 83% [74–91] | 70% | 19 ms | CV 94% de rec. imediato |
| llm_qwen3_8b_fs (logprobs, 3 exemplos/rótulo) | 75% | 65% | 94% [88–98] | 50% | 330 ms | alarma demais; sem treino |
| zs_mdeberta (NLI zero-shot) | 45% | 42% | 100% | 36% | 15 ms | **degenerado**: prevê imediato para quase tudo |
| zs_modernbert (NLI, inglês) | 29% | 44% | 20% | 48% | 19 ms | inadequado para português |
| llm_gemma3_4b (zero-shot) | 14% | 15% | 2% | 1% | 1250 ms | viés de letra neste formato de prompt; não conclusivo |
| llm_gemma3_4b_fs | 18% | 34% | 23% | 19% | 1420 ms | idem |

Leitura: no teste ampliado todas as alternativas treinadas caem de 90–97% para 83–89% de revocação de risco imediato, e a diferença entre elas fica dentro do IC. Revocação isolada engana (mDeBERTa "acerta" 100% alarmando tudo): reporte sempre com a precisão. Zero-shot (NLI e gemma3:4b) não serve para esta tarefa em português; o LLM maior com logprobs é viável como refino, não como governante.
