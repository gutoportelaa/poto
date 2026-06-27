"""CAMADA 2 — Deterministic regex parser.

Extracts municipio + uf from text matching patterns like:
    "Cidade, UF"
    "Cidade, Nome do Estado"
    "em Cidade, Estado"

Picks the FIRST occurrence (consistent with geocoder behavior on multi-city input).
Returns None if no clear pattern is found.
"""

from __future__ import annotations

import re

from .models import StructuredLocation
from .normalize import STATE_TO_UF, VALID_UFS, normalize_text, strip_accents

# Pattern: "<word(s)>, <UF>" anchored anywhere in the text.
# UF requires word boundary on both sides.
_UF_ALT = "|".join(sorted(VALID_UFS))
_PATTERN_CITY_UF = re.compile(
    r"(?P<city>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\sáéíóúâêôãõç'\-]+?)\s*,\s*(?P<uf>" + _UF_ALT + r")\b",
    re.IGNORECASE,
)

# Pattern: "<word(s)>, <state words>" — captures up to 4 words after comma,
# then we look them up against STATE_TO_UF after normalization.
_PATTERN_CITY_STATE_NAME = re.compile(
    r"(?P<city>[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\sáéíóúâêôãõç'\-]+?)\s*,\s*"
    r"(?P<state>[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]+(?:\s+[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]+){0,3})",
    re.UNICODE,
)


def parse_location_regex(text: str) -> StructuredLocation | None:
    """CAMADA 2 — Parse 'Cidade, UF' or 'Cidade, NomeEstado' from free text.

    Returns StructuredLocation with municipio + uf when a match is found,
    otherwise None. Bairro/logradouro are NEVER populated by regex —
    those require geocoder confirmation.
    """
    if not text or not text.strip():
        return None

    # Try "Cidade, UF" first (highest precision)
    match = _PATTERN_CITY_UF.search(text)
    if match:
        city = _clean_city(match.group("city"))
        uf = match.group("uf").upper()
        if city and len(city) >= 2:
            return StructuredLocation(municipio=city, uf=uf)

    # Try "Cidade, NomeEstado" (lookup full state name → UF)
    # Search all matches and try matching state name from longest to shortest.
    for match in _PATTERN_CITY_STATE_NAME.finditer(text):
        city = _clean_city(match.group("city"))
        state_raw = match.group("state").strip()
        state_words = state_raw.split()
        # Try longest possible state name (4 → 1 words) for greedy match
        for n in range(len(state_words), 0, -1):
            candidate = " ".join(state_words[:n])
            uf = STATE_TO_UF.get(normalize_text(candidate))
            if uf and city and len(city) >= 2:
                return StructuredLocation(municipio=city, uf=uf)

    return None


# Match the last contiguous "city-like" chunk in a string:
# a capitalized word, optionally followed by more capitalized words
# possibly joined by Portuguese connectors ("de", "do", "da", "dos", "das").
# Examples matched: "Teresina", "Rio de Janeiro", "São João do Rio Preto"
_CITY_CHUNK_PATTERN = re.compile(
    r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç'\-]+"
    r"(?:\s+(?:de|do|da|dos|das)\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç'\-]+"
    r"|\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç'\-]+)*)\s*$",
    re.UNICODE,
)


def _clean_city(raw: str) -> str | None:
    """Extract the trailing capitalized city chunk from a raw match.

    Examples:
        "ocorreu em Parnaíba" → "Parnaíba"
        "na cidade de Teresina" → "Teresina"
        "Rio de Janeiro" → "Rio de Janeiro"
        "São João do Rio Preto" → "São João do Rio Preto"
    """
    if not raw:
        return None
    s = raw.strip()
    match = _CITY_CHUNK_PATTERN.search(s)
    if not match:
        return None
    candidate = match.group(1).strip()
    if len(candidate) < 2 or candidate.isdigit():
        return None
    return candidate
