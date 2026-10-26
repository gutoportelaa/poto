#!/usr/bin/env python3
"""Harness de comparação das alternativas de triagem (issue #8).

Cada alternativa implementa `Alternativa` (fit/predict) e é avaliada com o MESMO
protocolo sobre scripts/dataset_v2:

  1. validação cruzada estratificada em treino+validação (frases originais, sem ruído)
  2. teste held-out (frases distintas) e teste_ruido (variantes de digitação/acento)
  3. IC 95% por bootstrap sobre o teste

Métricas: acurácia de tipo e de gravidade, REVOCAÇÃO de risco_imediato (errar um
risco imediato como orientação é o pior erro), matriz de confusão de gravidade,
latência por predição na CPU e tamanho do artefato.

Uso:
    uv run --no-project --with scikit-learn --with joblib --with pydantic --with httpx \\
        python scripts/compare_triagem.py [--alt heuristica,tfidf,pipeline] [--md saida.md]

Para plugar uma nova alternativa (BERT, SetFit, LLM...), adicione uma classe em
ALTERNATIVAS; ver issue #10.
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
DS = ROOT / "scripts" / "dataset_v2"

GRAVS = ["risco_imediato", "risco_potencial", "orientacao"]
TIPOS = ["seguranca", "mulher", "saude", "ouvidoria"]


def carregar(nome: str) -> list[dict]:
    return json.loads((DS / f"{nome}.json").read_text("utf-8"))


# --------------------------------------------------------------- alternativas ----
class Alternativa:
    nome = "?"

    def fit(self, dados: list[dict]) -> "Alternativa":
        return self

    def predict(self, textos: list[str]) -> list[tuple[str, str]]:
        """Retorna [(tipo, gravidade)] na ordem de `textos`."""
        raise NotImplementedError

    def tamanho_bytes(self) -> int:
        return 0


class Heuristica(Alternativa):
    """Regras por palavra-chave (agents.graph._heuristica) — não treina."""

    nome = "heuristica"

    def predict(self, textos):
        from app.agents.graph import _heuristica
        from app.models import Modo
        out = []
        for t in textos:
            r = _heuristica(t, Modo.normal)
            out.append((r["tipo_sugerido"], r["gravidade"]))
        return out


class TfidfLogreg(Alternativa):
    """Classificador atual (app.classificador): TF-IDF palavra+char + LogReg."""

    nome = "tfidf"

    def fit(self, dados):
        from app import classificador
        x = [d["texto"] for d in dados]
        self.p_tipo = classificador._novo_pipeline().fit(x, [d["tipo"] for d in dados])
        self.p_grav = classificador._novo_pipeline().fit(x, [d["gravidade"] for d in dados])
        return self

    def predict(self, textos):
        return list(zip(self.p_tipo.predict(textos), self.p_grav.predict(textos)))

    def tamanho_bytes(self):
        return len(pickle.dumps((self.p_tipo, self.p_grav)))


class PipelineProd(TfidfLogreg):
    """Configuração de produção: classificador + merge protetivo com a heurística
    (nunca rebaixa gravidade; em sinal crítico segue a heurística)."""

    nome = "pipeline"

    def predict(self, textos):
        from app.agents.graph import _heuristica, _merge_protetivo
        from app.models import Modo
        out = []
        for t, tipo, grav in zip(textos, self.p_tipo.predict(textos), self.p_grav.predict(textos)):
            seed = _heuristica(t, Modo.normal)
            m = _merge_protetivo(seed, {"tipo": str(tipo), "gravidade": str(grav),
                                        "confianca": 0.8}, Modo.normal, fonte="classificador")
            out.append((m["tipo_sugerido"], m["gravidade"]))
        return out


ALTERNATIVAS: dict[str, type[Alternativa]] = {
    c.nome: c for c in (Heuristica, TfidfLogreg, PipelineProd)
}
BASICAS = list(ALTERNATIVAS)  # as que rodam só com sklearn (default do harness)


def com_merge(base: type[Alternativa]) -> type[Alternativa]:
    """Embrulha qualquer alternativa no merge protetivo de produção: a heurística de
    sinais críticos pode ELEVAR a gravidade e, em crise, define o tipo (nunca rebaixa)."""

    class ComMerge(Alternativa):
        nome = base.nome + "+merge"

        def fit(self, dados):
            self.base = base().fit(dados)
            return self

        def predict(self, textos):
            from app.agents.graph import _heuristica, _merge_protetivo
            from app.models import Modo
            out = []
            for t, (tipo, grav) in zip(textos, self.base.predict(textos)):
                m = _merge_protetivo(_heuristica(t, Modo.normal),
                                     {"tipo": str(tipo), "gravidade": str(grav), "confianca": 0.8},
                                     Modo.normal, fonte="classificador")
                out.append((m["tipo_sugerido"], m["gravidade"]))
            return out

        def tamanho_bytes(self):
            return self.base.tamanho_bytes()

    return ComMerge


def _plugar_ml() -> None:
    """Registra as alternativas de encoder se torch/transformers estiverem presentes."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import alternativas_ml
        ALTERNATIVAS.update(alternativas_ml.registro(Alternativa))
    except ImportError as e:
        print(f"[aviso] alternativas ML indisponíveis ({e.name}); só as básicas.", file=sys.stderr)


def _plugar_jev() -> None:
    """Registra o Jev (referência hospedada) só se houver chave e o pacote."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import alternativas_jev
    if alternativas_jev.disponivel():
        ALTERNATIVAS.update(alternativas_jev.registro(Alternativa))


_plugar_ml()
_plugar_jev()
for _n in [n for n in ALTERNATIVAS if n not in ("heuristica", "pipeline")]:
    ALTERNATIVAS[_n + "+merge"] = com_merge(ALTERNATIVAS[_n])


# -------------------------------------------------------------------- métricas ----
def metricas(gold: list[dict], pred: list[tuple[str, str]]) -> dict:
    at = np.array([p[0] == g["tipo"] for p, g in zip(pred, gold)], dtype=float)
    ag = np.array([p[1] == g["gravidade"] for p, g in zip(pred, gold)], dtype=float)
    imed = np.array([g["gravidade"] == "risco_imediato" for g in gold])
    rec = np.array([p[1] == "risco_imediato" for p in pred])[imed].astype(float)
    # pior erro: risco_imediato previsto como orientação
    grave = float(np.mean([p[1] == "orientacao" for p in np.array(pred, dtype=object)[imed]])) \
        if imed.any() else 0.0
    alarmes = [p[1] == "risco_imediato" for p in pred]
    prec = (sum(a and g["gravidade"] == "risco_imediato" for a, g in zip(alarmes, gold))
            / sum(alarmes)) if any(alarmes) else 0.0
    conf = {g: {h: 0 for h in GRAVS} for g in GRAVS}
    for p, g in zip(pred, gold):
        conf[g["gravidade"]][p[1]] = conf[g["gravidade"]].get(p[1], 0) + 1
    return {"n": len(gold), "tipo": at.mean(), "grav": ag.mean(),
            "rec_imediato": rec.mean() if len(rec) else float("nan"),
            "imediato_como_orientacao": grave, "prec_imediato": prec, "confusao": conf,
            "_tipo": at, "_grav": ag, "_rec": rec}


def ic95(v: np.ndarray, rng: np.random.Generator, b: int = 1000) -> tuple[float, float]:
    if len(v) == 0:
        return (float("nan"),) * 2
    m = [rng.choice(v, size=len(v)).mean() for _ in range(b)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def validacao_cruzada(cls, dados: list[dict], k: int = 5, seed: int = 42) -> dict:
    from sklearn.model_selection import StratifiedKFold
    y = [f"{d['tipo']}|{d['gravidade']}" for d in dados]
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)
    gold_all, pred_all = [], []
    for tr, te in skf.split(dados, y):
        alt = cls().fit([dados[i] for i in tr])
        gold = [dados[i] for i in te]
        pred_all += alt.predict([g["texto"] for g in gold])
        gold_all += gold
    return metricas(gold_all, pred_all)


def latencia_ms(alt: Alternativa, textos: list[str]) -> tuple[float, float]:
    alt.predict(textos[:1])  # warm-up
    t = []
    for x in textos:
        t0 = time.perf_counter()
        alt.predict([x])
        t.append((time.perf_counter() - t0) * 1000)
    t.sort()
    return statistics.median(t), t[max(0, int(len(t) * 0.95) - 1)]


# ---------------------------------------------------------------------- relatório ----
def pct(x: float) -> str:
    return "—" if x != x else f"{x*100:.0f}%"


def com_ic(m: dict, chave: str, rng) -> str:
    lo, hi = ic95(m["_" + chave] if chave != "rec" else m["_rec"], rng)
    val = m[{"tipo": "tipo", "grav": "grav", "rec": "rec_imediato"}[chave]]
    return f"{pct(val)} [{pct(lo)}–{pct(hi)}]"


def main() -> None:
    ap = argparse.ArgumentParser(description="Compara alternativas de triagem (P.O.T.O)")
    ap.add_argument("--alt", default=",".join(BASICAS),
                    help=f"lista por vírgula; disponíveis: {', '.join(ALTERNATIVAS)}")
    ap.add_argument("--treino", default="treino", choices=["treino", "treino_aumentado"])
    ap.add_argument("--md", help="grava o relatório em markdown neste caminho")
    ap.add_argument("--sem-cv", action="store_true")
    ap.add_argument("--teste", default="teste",
                    help="arquivos de teste em dataset_v2 (vírgula), ex.: teste,teste_ext")
    args = ap.parse_args()

    treino, val = carregar(args.treino), carregar("validacao")
    teste = [d for n in args.teste.split(",") for d in carregar(n.strip())]
    ruido = carregar("teste_ruido")
    # CV só com frases originais (sem variantes) para não vazar ruído entre folds
    cv_dados = [d for d in treino + val if "variante_de" not in d]
    rng = np.random.default_rng(0)

    linhas, detalhes = [], []
    for nome in [a.strip() for a in args.alt.split(",") if a.strip()]:
        cls = ALTERNATIVAS[nome]
        alt = cls().fit(treino)
        r_teste = metricas(teste, alt.predict([d["texto"] for d in teste]))
        r_ruido = metricas(ruido, alt.predict([d["texto"] for d in ruido]))
        med, p95 = latencia_ms(alt, [d["texto"] for d in teste])
        cv = None if args.sem_cv else validacao_cruzada(cls, cv_dados)
        linhas.append((nome, cv, r_teste, r_ruido, med, p95, alt.tamanho_bytes()))
        detalhes.append((nome, r_teste))
        print(f"[ok] {nome}", file=sys.stderr)

    out = [f"# Comparação de triagem — treino: `{args.treino}`",
           f"\nTeste: {len(teste)} frases distintas · teste com ruído: {len(ruido)} · "
           f"CV 5-fold em {len(cv_dados)} frases. IC 95% por bootstrap.\n",
           "| alternativa | CV tipo | CV grav | CV rec.imediato | teste tipo | teste grav | "
           "**teste rec.imediato** | prec.imediato | imediato→orientação | ruído tipo | lat. mediana | p95 | tamanho |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for nome, cv, t, r, med, p95, tam in linhas:
        cvs = (pct(cv["tipo"]), pct(cv["grav"]), pct(cv["rec_imediato"])) if cv else ("—",) * 3
        out.append(
            f"| {nome} | {cvs[0]} | {cvs[1]} | {cvs[2]} | {com_ic(t,'tipo',rng)} | "
            f"{com_ic(t,'grav',rng)} | **{com_ic(t,'rec',rng)}** | "
            f"{pct(t['prec_imediato'])} | {pct(t['imediato_como_orientacao'])} | {pct(r['tipo'])} | {med:.2f} ms | "
            f"{p95:.2f} ms | {tam/1024:.0f} KB |")
    out.append("\n## Matriz de confusão da gravidade (teste; linhas = real, colunas = previsto)\n")
    for nome, t in detalhes:
        out.append(f"**{nome}**\n\n| real \\ prev | " + " | ".join(GRAVS) + " |\n|---|---|---|---|")
        for g in GRAVS:
            out.append(f"| {g} | " + " | ".join(str(t['confusao'][g].get(h, 0)) for h in GRAVS) + " |")
        out.append("")
    texto = "\n".join(out)
    print(texto)
    if args.md:
        Path(args.md).write_text(texto + "\n", "utf-8")


if __name__ == "__main__":
    main()
