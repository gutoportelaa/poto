"""Orientação da Ouvidoria a partir da base versionada (issue #21, #24).

O assistente NUNCA inventa prazo, telefone ou promessa: só devolve fatos de
`data/ouvidoria.json` cujo status não seja 'a_confirmar'. Sem fonte, não responde.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

BASE = Path(__file__).resolve().parent / "data" / "ouvidoria.json"
USAVEIS = ("norma", "portal")

AVISO_ANONIMATO = (
    "Atenção: denúncia anônima não gera protocolo e não permite resposta nem acompanhamento. "
    "Se você quer receber retorno, registre com identificação."
)

_RE_ANONIMO = re.compile(r"anonim|sem (me )?identific|nao quero (me )?identific|sem dar (meu )?nome")
_RE_DENUNCIA = re.compile(r"denunci")
_RE_PRAZO = re.compile(r"prazo|quanto tempo|quando (vou|vao) (receber|ter)|demora|tempo (medio )?de (retorno|resposta)")
_RE_CONTATO = re.compile(r"telefone|ligar|contato|horario|onde (fica|encontro|acho)")
_RE_TIPOS = re.compile(r"tipo|como (registr|faz)|fala\.?br|elogio|sugest|reclam")


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def fatos() -> dict:
    return json.loads(BASE.read_text("utf-8"))["fatos"]


def _fato(chave: str) -> dict | None:
    f = fatos().get(chave)
    return f if f and f.get("texto") and f.get("status") in USAVEIS else None


def orientar(texto: str) -> dict:
    """Devolve {resposta, fontes, aviso_anonimato}. `resposta` é None se não houver
    fato com fonte que cubra a pergunta (o chamador cai no texto padrão)."""
    t = _norm(texto)
    chaves: list[str] = []
    anonimo = bool(_RE_ANONIMO.search(t))
    if anonimo or _RE_DENUNCIA.search(t):
        chaves += ["denuncia_anonima"] if anonimo else []
    if _RE_PRAZO.search(t):
        chaves += ["prazo_manifestacao"]
    if _RE_CONTATO.search(t):
        chaves += ["telefone", "horario"]
    if _RE_TIPOS.search(t) and not chaves:
        chaves += ["canal_oficial", "tipos_manifestacao"]
    usados = [(c, _fato(c)) for c in dict.fromkeys(chaves)]
    usados = [(c, f) for c, f in usados if f]
    return {
        "resposta": " ".join(f["texto"] for _, f in usados) or None,
        "fontes": [f["fonte"] for _, f in usados],
        "aviso_anonimato": AVISO_ANONIMATO if anonimo else None,
    }
