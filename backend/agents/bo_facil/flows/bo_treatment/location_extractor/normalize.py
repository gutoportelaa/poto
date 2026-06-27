"""Normalization helpers — accent stripping, state code mapping, coordinate detection."""

from __future__ import annotations

import re
import unicodedata

# Maps full Brazilian state names (lowercase, accent-stripped) to 2-letter UF.
STATE_TO_UF: dict[str, str] = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}
VALID_UFS: frozenset[str] = frozenset(STATE_TO_UF.values())
UF_TO_STATE: dict[str, str] = {uf: name.title() for name, uf in STATE_TO_UF.items()}

# Detects coordinates-only input like "-5.116936, -42.794312".
_COORDINATES_PATTERN = re.compile(r"^\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*$")


def strip_accents(text: str) -> str:
    """Remove diacritics: 'Piauí' → 'Piaui', 'São' → 'Sao'."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Lowercase + strip accents — for substring comparisons."""
    return strip_accents(text.lower())


def normalize_state(raw: str | None) -> str | None:
    """Normalize a state string to 2-letter UF, or None if not Brazilian.

    Examples:
        'State of Piauí' → 'PI'
        'Rio Grande do Sul' → 'RS'
        'PI' → 'PI'
        'Nouvelle-Aquitaine' → None (not Brazilian)
    """
    if not raw:
        return None
    cleaned = re.sub(r"(?i)^state\s+of\s+", "", raw).strip()
    cleaned_key = strip_accents(cleaned).lower()
    if uf := STATE_TO_UF.get(cleaned_key):
        return uf
    if cleaned.upper() in VALID_UFS:
        return cleaned.upper()
    return None


def is_coordinates_only(text: str | None) -> bool:
    """True if text is just lat/long coordinates."""
    if not text:
        return False
    return bool(_COORDINATES_PATTERN.match(text.strip()))


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Parse 'lat, long' string into floats. Returns None if not valid coords."""
    if not is_coordinates_only(text):
        return None
    parts = [p.strip() for p in text.split(",")]
    try:
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return None
