"""Location extractor — three-layer pipeline for converting free-text into structured location.

Layer 1: Geocoder forward + double-hop reverse, validated by V1/V3.
Layer 2: Regex parser (deterministic, dictionary-based).
Layer 3: LLM parser (last resort, V1 post-validated).

Public API: `extract_location_data(text) -> LocationData`.
"""

from .models import GeocodeResult, LocationData, StructuredLocation
from .orchestrator import extract_location_data

__all__ = [
    "GeocodeResult",
    "LocationData",
    "StructuredLocation",
    "extract_location_data",
]
