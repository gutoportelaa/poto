"""Validation rules V1 (substring), V2 (fuzzy), V3 (drift detection).

These guard the pipeline against:
- V1: foreign results, geocoder hallucinations, generic chutes
- V2 (opt-in): user typos like "Teresima" → "Teresina"
- V3: reverse-hop drift like Rio de Janeiro → São Gonçalo
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import GeocodeResult, StructuredLocation
from .normalize import (
    UF_TO_STATE,
    VALID_UFS,
    is_coordinates_only,
    normalize_state,
    normalize_text,
)


def validate_geocode_result(
    result: GeocodeResult,
    original_text: str,
    *,
    fuzzy: bool = False,
) -> bool:
    """REGRA V1 — Decide if a geocoder result is trustworthy for the given text.

    Gate policy (in order):
    1. Filter BR: Estado must normalize to a Brazilian UF.
    2. Coordinates input: bypass substring check (coords are unambiguous).
    3. **valid_address=true: trust Lambda.** The upstream LLM already decided
       the text is a searchable place, and Lambda confirmed with confidence.
       Substring checks here cause false negatives when Lambda normalizes
       street/bairro names differently from what the user typed (common).
       Drift detection from V3 (reverse-hop in geocoder_pipeline) is the
       second safety layer for these confident results.
    4. valid_address=false: apply substring/fuzzy checks to filter Lambda
       hallucinations (e.g. "bairro Dirceu" → Cruz Alta-RS chute).

    With fuzzy=True, also tries V2 fuzzy match for typo tolerance.
    """
    uf = normalize_state(result.estado)
    if uf not in VALID_UFS:
        return False

    if is_coordinates_only(original_text):
        return True

    if result.valid_address:
        return True

    # Unconfident result — verify Lambda against the user text.
    text_norm = normalize_text(original_text)

    if result.cidade:
        cidade_norm = normalize_text(result.cidade)
        if cidade_norm in text_norm:
            return True
        if fuzzy and fuzzy_match_in_text(result.cidade, original_text):
            return True

    if re.search(rf"\b{uf}\b", original_text, re.IGNORECASE):
        return True

    estado_full = UF_TO_STATE.get(uf)
    if estado_full and normalize_text(estado_full) in text_norm:
        return True

    return False


def fuzzy_match_in_text(
    candidate: str,
    text: str,
    *,
    threshold: float = 0.85,
    max_len_diff: int = 3,
) -> bool:
    """REGRA V2 — Fuzzy match for typo tolerance.

    Returns True if some token-window of `text` matches `candidate` with
    SequenceMatcher ratio >= threshold AND length difference <= max_len_diff.

    Example:
        fuzzy_match_in_text("Teresina", "Teresima, PI")  # True (ratio 0.875)
        fuzzy_match_in_text("Patos de Minas", "patos pb")  # False (too different)
    """
    cand = normalize_text(candidate)
    text_norm = normalize_text(text)

    if cand in text_norm:
        return True

    # Tokenize stripping punctuation so "Teresima," matches the bare word.
    n_tokens = len(cand.split())
    text_tokens = re.findall(r"[\wáéíóúâêôãõç'\-]+", text_norm)
    if len(text_tokens) < n_tokens:
        return False

    for i in range(len(text_tokens) - n_tokens + 1):
        window = " ".join(text_tokens[i:i + n_tokens])
        if abs(len(window) - len(cand)) > max_len_diff:
            continue
        ratio = SequenceMatcher(None, cand, window).ratio()
        if ratio >= threshold:
            return True

    return False


def merge_double_hop(
    r1: GeocodeResult,
    r2: GeocodeResult,
) -> StructuredLocation:
    """REGRA V3 — Merge forward (r1) + reverse (r2) safely.

    Assumes r1 already passed V1. If r2.cidade differs from r1.cidade
    (drift detected — e.g. Rio de Janeiro → São Gonçalo), discards r2's
    bairro/rua and uses only r1's municipio/uf.
    """
    r1_cidade = normalize_text(r1.cidade or "")
    r2_cidade = normalize_text(r2.cidade or "")
    uf = normalize_state(r1.estado)

    # Drift: r2 moved to a different city — keep only r1's data
    if r2_cidade and r2_cidade != r1_cidade:
        return StructuredLocation(
            municipio=r1.cidade,
            uf=uf,
            bairro=None,
            logradouro=None,
        )

    # No drift: trust r2's bairro/rua (more precise from coords)
    return StructuredLocation(
        municipio=r1.cidade,
        uf=uf,
        bairro=r2.bairro or None,
        logradouro=r2.rua or None,
    )
