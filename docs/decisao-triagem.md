# Decisão: quem governa a triagem (issue #11)

Base: `docs/comparacao-triagem.md` (354 frases revisadas, texto digitado e texto passado por STT).
Princípios do projeto: o totem funciona sem rede; o LLM nunca decide urgência sozinho; o texto
do relato não sai do totem.

## Recomendação

**Manter o pipeline atual como governante, online e offline:** classificador TF-IDF + regressão
logística, heurística determinística como piso de segurança e merge protetivo.

| critério | pipeline | e5small+merge | bertimbau+merge | LLM qwen3:8b | Jev |
|---|---|---|---|---|---|
| revocação de imediato (digitado) | 86% | 85% | 83% | **95%** | a medir |
| precisão de imediato | 56% | 58% | 62% | 44% | a medir |
| revocação com fala (Whisper base) | **72%** | 67% | 69% | não medido | a medir |
| pior caso com fala (tiny + ruído) | **68%** | 57% | 58% | não medido | a medir |
| tipo (digitado) | 72% | 79% | **82%** | 79% | a medir |
| latência / tamanho | **1,6 ms / 751 KB** | 11 ms / 460 MB | 17 ms / 425 MB | 1,8 s / GPU | rede |
| funciona sem rede | sim | sim | sim | só com GPU local | **não** |
| texto sai do totem | não | não | não | não | **sim** |

Por quê:
1. **Em risco, ninguém ganha com folga.** Os intervalos de revocação se sobrepõem entre pipeline,
   e5 e BERTimbau. Trocar o governante não melhora o que importa e custa 570× o tamanho.
2. **Com fala, o pipeline é o mais robusto**, e o totem recebe fala. Os encoders perdem mais.
3. **Os encoders melhoram o tipo** (+7 a +10 pontos), que decide para quem ir. Vale como
   segundo voto no **online**, nunca para rebaixar gravidade (o merge protetivo já impede).
4. **O LLM tem a melhor revocação, mas só 44% de precisão** e 1,8 s. Serve como refino opcional
   no online (pode **subir** gravidade, nunca descer) e fica fora do caminho crítico.
5. **Jev** é hospedado: nunca governante. Entra como referência quando houver chave
   (`scripts/alternativas_jev.py`, só frases sintéticas).

## Online × offline

- **Offline (Pi 5):** pipeline + heurística + merge. É o que já cabe e roda em ms.
- **Online (demo):** o mesmo núcleo, mais refino opcional (e5 para o tipo; LLM para subir
  gravidade). Em `POTO_DEMO=1` tudo é registrado em log, sem acionamento real.

## O que ainda falta para fechar a decisão

1. **A maior alavanca é a fala, não o modelo.** Treinar o classificador com variantes
   transcritas por STT (aumento de dados) e comparar de novo; o ganho esperado é maior que o de
   trocar de arquitetura. Também vale usar o Whisper `base` ou maior no totem (o `tiny` perde 4–9
   pontos a mais) e baixar o limiar de imediato quando a confiança do STT for baixa.
2. **Áudio real.** Todo o teste de STT usa uma voz sintética limpa. Gravar frases de pessoas
   reais no ambiente do totem antes de confirmar os números.
3. **Revisão humana** dos rótulos do teste (a revisão atual é minha, com critérios registrados
   em `scripts/dataset_v2/revisar_ext.py`) e da fronteira mulher × segurança (#23).
4. **Medir o Jev** e o LLM sobre fala quando houver chave e tempo de GPU.
