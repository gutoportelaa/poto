"""CAMADA 1 — Geocoder pipeline: forward + double-hop reverse, with V1/V3 validation.

Flow:
1. forward(text) → r1
2. validate r1 with V1 → if fails, return LocationData(source="none")
3. if r1.valid_address=true → DONE (source="geocoder_forward")
4. else (partial): reverse(r1.coords) → r2; merge with V3
   - r2 valid → source="geocoder_double_hop"
   - r2 invalid/drift → source="geocoder_forward_partial" (only municipio/uf)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx

from .models import GeocodeResult, LocationData, StructuredLocation
from .normalize import normalize_state
from .validation import merge_double_hop, validate_geocode_result

logger = logging.getLogger(__name__)

# Type for an injectable geocoder function (for testability)
GeocoderFn = Callable[[str], Awaitable[GeocodeResult | None]]


async def geocode_with_validation(
    text: str,
    *,
    geocoder: GeocoderFn | None = None,
    fuzzy: bool = False,
) -> LocationData:
    """Run forward + conditional reverse with V1/V3 validation.

    Args:
        text: User-provided location text or "lat, long" string.
        geocoder: Injectable geocoder function (defaults to real HTTP client).
        fuzzy: If True, enable V2 fuzzy matching for typo tolerance.

    Returns:
        LocationData with structured/coordinates/source set appropriately.
    """
    if not text or not text.strip():
        return LocationData(source="none")

    geo = geocoder or _real_geocoder

    # Step 1: forward
    r1 = await _safe_call(geo, text)
    if r1 is None:
        return LocationData(source="none")

    # Step 2a: reject generic state-level fallbacks.
    # When the geocoder can't resolve the address, it often returns
    # valid_address=false with only Estado filled and coords pointing
    # to the state centroid (e.g. "State of Piauí" at -8.11, -42.94).
    # Those coords lie about the incident — discard the whole response.
    if not r1.valid_address and not (r1.cidade and r1.cidade.strip()):
        logger.info(
            f"[geocoder_pipeline] rejected generic state fallback for {text!r}: "
            f"cidade=<empty>, estado={r1.estado}"
        )
        return LocationData(source="none")

    # Step 2b: V1 validation
    if not validate_geocode_result(r1, text, fuzzy=fuzzy):
        logger.info(
            f"[geocoder_pipeline] V1 rejected forward result for {text!r}: "
            f"cidade={r1.cidade}, estado={r1.estado}"
        )
        return LocationData(source="none")

    coords = (
        (r1.latitude, r1.longitude)
        if r1.latitude is not None and r1.longitude is not None
        else None
    )
    uf = normalize_state(r1.estado)

    # Step 3: forward valid_address=true.
    # Always do a reverse-hop verification when coords are available — it
    # catches Lambda hallucinations that V1 can't (when user text doesn't
    # name the canonical city) and also enriches missing fields like Bairro.
    # If r2 agrees with r1 on city (V3), merge; if it drifts, keep only
    # municipio/uf and flag as partial.
    if r1.valid_address:
        if coords is not None:
            coord_query = f"{coords[0]}, {coords[1]}"
            r2 = await _safe_call(geo, coord_query)
            if r2 and validate_geocode_result(r2, text, fuzzy=fuzzy):
                merged = merge_double_hop(r1, r2)
                drifted = (
                    merged.bairro is None and merged.logradouro is None and (r2.bairro or r2.rua)
                )
                if drifted:
                    logger.info(
                        f"[geocoder_pipeline] V3 drift on confident forward for {text!r}: "
                        f"r1.cidade={r1.cidade} vs r2.cidade={r2.cidade} — keeping municipio/uf only"
                    )
                    return LocationData(
                        structured=StructuredLocation(municipio=r1.cidade, uf=uf),
                        coordinates=coords,
                        source="geocoder_forward_partial",
                    )
                return LocationData(
                    structured=merged,
                    coordinates=coords,
                    source="geocoder_forward",
                )
        # No coords or reverse failed — use forward as-is.
        structured = StructuredLocation(
            municipio=r1.cidade,
            uf=uf,
            bairro=r1.bairro or None,
            logradouro=r1.rua or None,
        )
        return LocationData(
            structured=structured,
            coordinates=coords,
            source="geocoder_forward",
        )

    # Step 4: partial — try reverse hop if we have coords
    if coords is None:
        # Partial without coords: at least keep municipio/uf
        return LocationData(
            structured=StructuredLocation(municipio=r1.cidade, uf=uf),
            coordinates=None,
            source="geocoder_forward_partial",
        )

    # A forward result with neither street nor neighbourhood is a bare-city
    # match: its coords are the city centroid. Reverse-geocoding a centroid
    # fabricates an arbitrary precise street/bairro the user never gave
    # (e.g. "Teresina" → "Avenida João XXIII, São Cristóvão"). Keep only
    # municipio/uf in that case — V3 drift detection can't catch this because
    # the reverse result stays in the same city, so never invent sub-city
    # precision from a centroid in the first place.
    if not (r1.bairro and r1.bairro.strip()) and not (r1.rua and r1.rua.strip()):
        logger.info(
            f"[geocoder_pipeline] bare-city forward for {text!r}: "
            f"cidade={r1.cidade} — keeping municipio/uf only (no centroid reverse-hop)"
        )
        return LocationData(
            structured=StructuredLocation(municipio=r1.cidade, uf=uf),
            coordinates=coords,
            source="geocoder_forward_partial",
        )

    coord_query = f"{coords[0]}, {coords[1]}"
    r2 = await _safe_call(geo, coord_query)

    if r2 is None or not validate_geocode_result(r2, text, fuzzy=fuzzy):
        # Reverse failed or its result drifted out of validation
        return LocationData(
            structured=StructuredLocation(municipio=r1.cidade, uf=uf),
            coordinates=coords,
            source="geocoder_forward_partial",
        )

    # Both passed — merge with V3 drift detection
    merged = merge_double_hop(r1, r2)
    # If V3 detected drift, merged.bairro/logradouro will be None
    drifted = merged.bairro is None and merged.logradouro is None and (r2.bairro or r2.rua)
    return LocationData(
        structured=merged,
        coordinates=coords,
        source="geocoder_forward_partial" if drifted else "geocoder_double_hop",
    )


async def _safe_call(geocoder: GeocoderFn, query: str) -> GeocodeResult | None:
    """Wrap geocoder call with error handling."""
    try:
        return await geocoder(query)
    except Exception as e:
        logger.warning(f"[geocoder_pipeline] geocoder call failed for {query!r}: {e}")
        return None


# ---------------------------------------------------------------------------
# Real HTTP geocoder (production default)
# ---------------------------------------------------------------------------


async def _real_geocoder(address: str) -> GeocodeResult | None:
    """Default geocoder using the configured Lambda URL with retry."""
    from core.settings import settings

    last_error: str | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    settings.GEOCODING_API_URL,
                    params={"address": address},
                )
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2**attempt))
                    continue

                body = response.json()
                data = body.get("data") or {}
                return GeocodeResult(
                    valid_address=bool(body.get("valid_address")),
                    cidade=data.get("Cidade") or None,
                    bairro=data.get("Bairro") or None,
                    rua=data.get("Rua") or None,
                    estado=data.get("Estado") or None,
                    latitude=_parse_float(data.get("latitude") or data.get("Latitude")),
                    longitude=_parse_float(data.get("longitude") or data.get("Longitude")),
                    raw=body,
                )
        except Exception as e:
            last_error = str(e)
            if attempt < 2:
                await asyncio.sleep(0.5 * (2**attempt))

    logger.error(f"[_real_geocoder] All 3 attempts failed for {address!r}. Last: {last_error}")
    return None


def _parse_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
