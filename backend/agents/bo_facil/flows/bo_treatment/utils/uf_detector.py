"""Regex UF detection in free-text location strings.

Used as fallback by `apply_uf_detection` when the extractor LLM does not
return `state_uf` directly. Covers majority of cases (siglas + state names
with accent variants). False negatives default to no-flag (assume PI).
"""

from __future__ import annotations

import re

_UF_PATTERNS: dict[str, list[str]] = {
    "AC": [r"\bAC\b", r"\bAcre\b"],
    "AL": [r"\bAL\b", r"\bAlagoas\b"],
    "AP": [r"\bAP\b", r"\bAmap[áa]\b"],
    "AM": [r"\bAM\b", r"\bAmazonas\b"],
    "BA": [r"\bBA\b", r"\bBahia\b"],
    "CE": [r"\bCE\b", r"\bCear[áa]\b"],
    "DF": [r"\bDF\b", r"\bDistrito Federal\b"],
    "ES": [r"\bES\b", r"\bEsp[íi]rito Santo\b"],
    "GO": [r"\bGO\b", r"\bGoi[áa]s\b"],
    "MA": [r"\bMA\b", r"\bMaranh[ãa]o\b"],
    "MT": [r"\bMT\b", r"\bMato Grosso\b(?!\s+do Sul)"],
    "MS": [r"\bMS\b", r"\bMato Grosso do Sul\b"],
    "MG": [r"\bMG\b", r"\bMinas Gerais\b"],
    "PA": [r"\bPA\b", r"\bPar[áa]\b"],
    "PB": [r"\bPB\b", r"\bPara[íi]ba\b"],
    "PR": [r"\bPR\b", r"\bParan[áa]\b"],
    "PE": [r"\bPE\b", r"\bPernambuco\b"],
    "PI": [r"\bPI\b", r"\bPiau[íi]\b"],
    "RJ": [r"\bRJ\b", r"\bRio de Janeiro\b"],
    "RN": [r"\bRN\b", r"\bRio Grande do Norte\b"],
    "RS": [r"\bRS\b", r"\bRio Grande do Sul\b"],
    "RO": [r"\bRO\b", r"\bRond[ôo]nia\b"],
    "RR": [r"\bRR\b", r"\bRoraima\b"],
    "SC": [r"\bSC\b", r"\bSanta Catarina\b"],
    "SP": [r"\bSP\b", r"\bS[ãa]o Paulo\b"],
    "SE": [r"\bSE\b", r"\bSergipe\b"],
    "TO": [r"\bTO\b", r"\bTocantins\b"],
}


def detect_uf_in_location(value: str) -> str | None:
    """Return UF code (ex: 'PI') if detected in `value`, else None."""
    if not value:
        return None

    flags = re.IGNORECASE
    for uf, patterns in _UF_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, value, flags=flags):
                return uf
    return None
