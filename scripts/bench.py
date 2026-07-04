#!/usr/bin/env python3
"""P.O.T.O — benchmark de modelos de TRIAGEM na CPU (decisão sem Hailo).

Compara modelos mini/nano em latência e acurácia na tarefa de classificação
(tipo/gravidade) sobre um conjunto rotulado de frases pt-BR de emergência. Serve
para escolher o `POTO_TRIAGEM_MODEL` por dados — "avaliar à medida que testamos".

Mede o CLASSIFICADOR isolado (`agents.graph.classificar_triagem`), sem os
guardrails determinísticos (que sobrepõem gravidade em sinal crítico) — o objetivo
é comparar o julgamento do modelo, não do pipeline.

Uso (na Pi, com Ollama no ar):
    cd backend && uv run python ../scripts/bench.py
    ... --models qwen2.5:0.5b,qwen2.5:1.5b,llama3.2:1b,gemma2:2b,llama3.2:3b
    ... --dataset ../scripts/bench_dataset.json   # sobrescreve o conjunto embutido
    ... --json

Modelos ausentes no Ollama são pulados (dica: `ollama pull <modelo>`).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Conjunto rotulado embutido — pequeno mas cobrindo as 4 trilhas e 3 gravidades.
DATASET: list[dict] = [
    {"texto": "um homem está me seguindo perto do bloco 7", "tipo": "seguranca", "gravidade": "risco_imediato"},
    {"texto": "vi uns caras estranhos rondando o estacionamento", "tipo": "seguranca", "gravidade": "risco_potencial"},
    {"texto": "queria saber o horário da segurança do campus", "tipo": "seguranca", "gravidade": "orientacao"},
    {"texto": "meu ex me ameaçou e está aqui na faculdade agora", "tipo": "mulher", "gravidade": "risco_imediato"},
    {"texto": "um professor faz comentários que me deixam desconfortável", "tipo": "mulher", "gravidade": "risco_potencial"},
    {"texto": "quero informações sobre a sala lilás", "tipo": "mulher", "gravidade": "orientacao"},
    {"texto": "estou passando mal, quase desmaiando", "tipo": "saude", "gravidade": "risco_imediato"},
    {"texto": "torci o tornozelo na quadra e está inchando", "tipo": "saude", "gravidade": "risco_potencial"},
    {"texto": "onde fica o posto médico do campus?", "tipo": "saude", "gravidade": "orientacao"},
    {"texto": "quero fazer uma denúncia contra um servidor", "tipo": "ouvidoria", "gravidade": "risco_potencial"},
    {"texto": "como faço uma reclamação sobre a limpeza dos banheiros", "tipo": "ouvidoria", "gravidade": "orientacao"},
    {"texto": "alguém está tendo uma convulsão no corredor", "tipo": "saude", "gravidade": "risco_imediato"},
    {"texto": "estão brigando e um deles tem uma faca", "tipo": "seguranca", "gravidade": "risco_imediato"},
    {"texto": "recebi mensagens ameaçadoras de um colega", "tipo": "mulher", "gravidade": "risco_potencial"},
    {"texto": "gostaria de elogiar o atendimento da biblioteca", "tipo": "ouvidoria", "gravidade": "orientacao"},
]

MODELOS_PADRAO = ["qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:1b", "gemma2:2b", "llama3.2:3b"]

GREEN, RED, YELLOW, DIM, BOLD, RST = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)


def _modelos_ollama() -> set[str] | None:
    """Nomes de modelos presentes no Ollama, ou None se o serviço estiver fora."""
    import httpx

    from app.config import OLLAMA_BASE_URL
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return {m["name"] for m in r.json().get("models", [])}
    except Exception:
        return None


def _avaliar(modelo: str, dataset: list[dict]) -> dict:
    from app.agents.graph import classificar_triagem
    classificar_triagem(dataset[0]["texto"], modelo=modelo)  # warm-up (carrega o modelo)
    lat: list[float] = []
    acertos_tipo = acertos_grav = com_grav = falhas = 0
    for item in dataset:
        t0 = time.perf_counter()
        r = classificar_triagem(item["texto"], modelo=modelo)
        lat.append((time.perf_counter() - t0) * 1000)
        if not r:
            falhas += 1
            continue
        if r.get("tipo") == item["tipo"]:
            acertos_tipo += 1
        if "gravidade" in r:
            com_grav += 1
            if r["gravidade"] == item["gravidade"]:
                acertos_grav += 1
    n = len(dataset)
    return {
        "modelo": modelo,
        "acuracia_tipo": acertos_tipo / n,
        "acuracia_gravidade": (acertos_grav / com_grav) if com_grav else 0.0,
        "falhas": falhas,
        "lat_media_ms": round(statistics.mean(lat), 1),
        "lat_p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1),
        "n": n,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark de modelos de triagem (P.O.T.O)")
    ap.add_argument("--models", help="lista por vírgula (default: candidatos mini/nano)")
    ap.add_argument("--dataset", help="JSON com [{texto,tipo,gravidade}]")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    # Dataset: --dataset explícito > scripts/bench_dataset.json (ampliado) > embutido.
    _ds_padrao = ROOT / "scripts" / "bench_dataset.json"
    if args.dataset:
        dataset = json.loads(Path(args.dataset).read_text("utf-8"))
    elif _ds_padrao.exists():
        dataset = json.loads(_ds_padrao.read_text("utf-8"))
    else:
        dataset = DATASET
    modelos = [m.strip() for m in args.models.split(",")] if args.models else MODELOS_PADRAO

    presentes = _modelos_ollama()
    if presentes is None:
        sys.exit("Ollama fora do ar — suba o serviço (ollama serve) e tente de novo.")

    resultados, pulados = [], []
    for m in modelos:
        if m not in presentes:
            pulados.append(m)
            continue
        resultados.append(_avaliar(m, dataset))

    if args.json:
        print(json.dumps({"resultados": resultados, "pulados": pulados}, ensure_ascii=False, indent=2))
        return

    print(f"\n{BOLD}P.O.T.O — benchmark de triagem{RST}  {DIM}({len(dataset)} amostras){RST}\n")
    print(f"  {'modelo':<16}{'acc.tipo':>9}{'acc.grav':>9}{'falhas':>8}{'lat.méd':>10}{'lat.p95':>9}")
    print(f"  {DIM}{'-'*60}{RST}")
    for r in sorted(resultados, key=lambda x: (-x["acuracia_tipo"], x["lat_media_ms"])):
        cor = GREEN if r["acuracia_tipo"] >= 0.8 else (YELLOW if r["acuracia_tipo"] >= 0.6 else RED)
        print(f"  {r['modelo']:<16}{cor}{r['acuracia_tipo']*100:>7.0f}%{RST}"
              f"{r['acuracia_gravidade']*100:>8.0f}%{r['falhas']:>8}"
              f"{r['lat_media_ms']:>8.0f}ms{r['lat_p95_ms']:>7.0f}ms")
    if pulados:
        print(f"\n  {YELLOW}pulados (ausentes no Ollama):{RST} {', '.join(pulados)}")
        print(f"  {DIM}baixe com: ollama pull <modelo>{RST}")
    print()


if __name__ == "__main__":
    main()
