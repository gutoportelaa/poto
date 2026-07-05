#!/usr/bin/env python3
"""Treina o classificador especializado de triagem e avalia contra o bench.

Treina em scripts/triagem_dataset.json e mede a acurácia num conjunto SEPARADO
(scripts/bench_dataset.json, held-out) — número honesto, sem vazamento. Também
reporta a latência de predição na CPU (o argumento central: ms, não segundos).

Uso:
    cd backend && uv sync --extra clf
    uv run python ../scripts/train_classificador.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    from app import classificador
    if not classificador._sklearn_ok():
        sys.exit("scikit-learn ausente. Instale: cd backend && uv sync --extra clf")

    treino = json.loads((ROOT / "scripts" / "triagem_dataset.json").read_text("utf-8"))
    eval_ = json.loads((ROOT / "scripts" / "bench_dataset.json").read_text("utf-8"))

    resumo = classificador.treinar(treino)
    print(f"treinado em {resumo['amostras']} amostras → {resumo['caminho']}")

    # Avaliação held-out + latência
    classificador._modelo = None  # força recarregar o artefato salvo
    ok_tipo = ok_grav = 0
    lat: list[float] = []
    for item in eval_:
        t0 = time.perf_counter()
        r = classificador.classificar(item["texto"])
        lat.append((time.perf_counter() - t0) * 1000)
        if r and r["tipo"] == item["tipo"]:
            ok_tipo += 1
        if r and r.get("gravidade") == item.get("gravidade"):
            ok_grav += 1
    n = len(eval_)
    lat.sort()
    print("\nAvaliação (held-out, bench_dataset.json):")
    print(f"  acurácia tipo:      {ok_tipo/n*100:5.1f}%  ({ok_tipo}/{n})")
    print(f"  acurácia gravidade: {ok_grav/n*100:5.1f}%  ({ok_grav}/{n})")
    print(f"  latência média:     {sum(lat)/n:6.2f} ms")
    print(f"  latência p95:       {lat[int(n*0.95)-1]:6.2f} ms")
    print("\nComparativo (mesmo held-out): nano na CPU do Pi = 29–45% tipo / ~6000 ms.")


if __name__ == "__main__":
    main()
