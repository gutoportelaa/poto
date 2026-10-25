#!/usr/bin/env python3
"""Gera o dataset v2 de triagem: divide por FRASE em treino/validação/teste e só
depois cria variantes ruidosas (sem acento, erro de digitação, caixa/pontuação).

Treino herda scripts/triagem_dataset.json; teste herda scripts/bench_dataset.json
(os números antigos continuam comparáveis). Saída em scripts/dataset_v2/.
"""

from __future__ import annotations

import json
import random
import unicodedata
from pathlib import Path

from base import BASE, FRONTEIRA

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
N_TREINO, N_VAL, N_TESTE = 12, 3, 5  # por célula (tipo, gravidade) = 20 frases
VARIANTES_TESTE = 2
SEED = 42


def sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))


def ruido(t: str, rng: random.Random, modo: str) -> str:
    if modo == "sem_acento":
        return sem_acento(t)
    if modo == "digitacao":
        pal = t.split()
        alvo = [i for i, w in enumerate(pal) if len(w) > 4]
        for i in rng.sample(alvo, k=min(2, len(alvo))):
            w, j = pal[i], rng.randrange(1, len(pal[i]) - 1)
            pal[i] = rng.choice([w[:j] + w[j + 1:], w[:j] + w[j] + w[j:], w[:j] + w[j + 1] + w[j] + w[j + 2:]])
        return " ".join(pal)
    return sem_acento(t).upper() + rng.choice(["!!", "!!!", "", "..."])  # "grito" de pânico


def main() -> None:
    rng = random.Random(SEED)
    treino = json.loads((RAIZ / "triagem_dataset.json").read_text("utf-8"))
    teste = json.loads((RAIZ / "bench_dataset.json").read_text("utf-8"))
    for lst, origem in ((treino, "v1"), (teste, "v1-bench")):
        for d in lst:
            d["origem"] = origem
    val: list[dict] = []
    vistos = {d["texto"].strip().lower() for d in treino + teste}

    for (tipo, grav), frases in sorted(BASE.items()):
        assert len(frases) == 20, (tipo, grav, len(frases))
        frases = [f for f in frases if f.strip().lower() not in vistos]
        rng.shuffle(frases)
        cortes = [(treino, 0, N_TREINO), (val, N_TREINO, N_TREINO + N_VAL),
                  (teste, N_TREINO + N_VAL, N_TREINO + N_VAL + N_TESTE)]
        for destino, a, b in cortes:
            for f in frases[a:b]:
                item = {"texto": f, "tipo": tipo, "gravidade": grav, "origem": "v2"}
                if f in FRONTEIRA:
                    item["fronteira"] = True
                destino.append(item)

    # variantes ruidosas: teste (2 por frase, separadas) e treino (1 por frase v2, sem acento)
    teste_ruido = []
    for d in teste:
        for modo in rng.sample(["sem_acento", "digitacao", "caixa_alta"], VARIANTES_TESTE):
            teste_ruido.append({**d, "texto": ruido(d["texto"], rng, modo),
                                "variante_de": d["texto"], "ruido": modo})
    aumento = [{**d, "texto": ruido(d["texto"], rng, "sem_acento"), "ruido": "sem_acento",
                "variante_de": d["texto"]} for d in treino if d["origem"] == "v2"]

    for nome, dados in (("treino", treino), ("treino_aumentado", treino + aumento),
                        ("validacao", val), ("teste", teste), ("teste_ruido", teste_ruido)):
        (AQUI / f"{nome}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=1), "utf-8")
        print(f"{nome:18s} {len(dados):4d}")
    textos = [d["texto"].lower() for d in treino + val + teste]
    assert len(textos) == len(set(textos)), "frase duplicada entre/dentro dos conjuntos"
    print("sem sobreposição entre treino/validação/teste: OK")


if __name__ == "__main__":
    main()
