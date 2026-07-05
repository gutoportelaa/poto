"""Classificador especializado de triagem (CPU, offline) — o "governante" local.

Sem Hailo e sem depender de LLM: TF-IDF (palavra + caractere) + Regressão
Logística sobre frases pt-BR rotuladas. Prediz tipo e gravidade em ~1ms, com
footprint de poucos KB — cabe em SD apertado e roda offline na borda. O LLM
(local ou remoto) fica como refino opcional, sem rebaixar o classificador.

Degrada com elegância: se o scikit-learn ou o modelo treinado não estiverem
presentes, `disponivel()` é False e o pipeline cai na heurística/LLM.

Dependência opcional (extra `clf`):  uv sync --extra clf
Treino:                              python scripts/train_classificador.py
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import CLF_PATH

log = logging.getLogger("poto.classificador")

_modelo = None  # cache do artefato carregado (dict com pipelines tipo/gravidade)


def _sklearn_ok() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except Exception:
        return False


def _novo_pipeline():
    """Pipeline TF-IDF(palavra + caractere) + LogReg. Char n-grams dão robustez a
    morfologia/erros de digitação com poucos dados; a união com palavra capta
    termos inteiros. Isolado numa função para treino e (des)serialização iguais."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    palavras = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
    return Pipeline([
        ("feats", FeatureUnion([("w", palavras), ("c", chars)])),
        ("clf", LogisticRegression(max_iter=1000, C=4.0, class_weight="balanced")),
    ])


def treinar(dataset: list[dict], caminho: str | None = None) -> dict:
    """Treina pipelines de tipo e gravidade e salva o artefato. Retorna um resumo."""
    import joblib
    caminho = caminho or CLF_PATH
    textos = [d["texto"] for d in dataset]
    y_tipo = [d["tipo"] for d in dataset]
    y_grav = [d.get("gravidade", "orientacao") for d in dataset]
    p_tipo = _novo_pipeline().fit(textos, y_tipo)
    p_grav = _novo_pipeline().fit(textos, y_grav)
    art = {"tipo": p_tipo, "gravidade": p_grav, "n": len(dataset)}
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(art, caminho)
    return {"amostras": len(dataset), "caminho": caminho}


def _carregar():
    global _modelo
    if _modelo is None:
        import joblib
        _modelo = joblib.load(CLF_PATH)
    return _modelo


def disponivel() -> bool:
    """True quando dá para classificar: sklearn instalado + modelo treinado presente."""
    return _sklearn_ok() and Path(CLF_PATH).is_file()


def classificar(texto: str) -> dict | None:
    """Prediz {tipo, gravidade, confianca} para o texto. None se indisponível/erro.
    confianca = probabilidade máxima da classe de tipo (o rótulo que roteia)."""
    if not disponivel() or not (texto or "").strip():
        return None
    try:
        art = _carregar()
        p_tipo, p_grav = art["tipo"], art["gravidade"]
        tipo = p_tipo.predict([texto])[0]
        conf = float(max(p_tipo.predict_proba([texto])[0]))
        grav = p_grav.predict([texto])[0]
        return {"tipo": tipo, "gravidade": grav, "confianca": round(conf, 3)}
    except Exception as e:  # noqa: BLE001 — degrada para heurística/LLM
        log.warning("classificador falhou (%s) — cai no fallback.", e)
        return None


def status() -> dict:
    return {
        "sklearn": _sklearn_ok(),
        "modelo_treinado": Path(CLF_PATH).is_file(),
        "disponivel": disponivel(),
        "caminho": CLF_PATH,
    }
