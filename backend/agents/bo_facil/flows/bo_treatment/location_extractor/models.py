"""Data models for the location extractor pipeline."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class GeocodeResult:
    """Raw geocoder response, normalized."""

    valid_address: bool
    cidade: str | None
    bairro: str | None
    rua: str | None
    estado: str | None  # raw from Lambda (e.g. "State of Piauí", "Rio Grande do Sul")
    latitude: float | None
    longitude: float | None
    raw: dict = field(default_factory=dict)


class StructuredLocation(BaseModel):
    """Validated structured location ready for the API payload.

    Pydantic BaseModel so it can be serialized inside IncidentInfo state.
    Frozen to preserve immutability semantics expected by the extractor.
    """

    model_config = ConfigDict(frozen=True)

    municipio: str | None = None
    uf: str | None = None  # always 2-letter UF
    bairro: str | None = None
    logradouro: str | None = None

    def is_empty(self) -> bool:
        return not any((self.municipio, self.uf, self.bairro, self.logradouro))


LocationSource = Literal[
    "geocoder_forward",         # forward returned valid_address=true and passed V1
    "geocoder_double_hop",      # forward+reverse merged successfully
    "geocoder_forward_partial", # forward gave partial data; reverse drift or failed
    "regex",                    # camada 2
    "llm",                      # camada 3
    "none",                     # nothing usable
]


@dataclass(frozen=True)
class LocationData:
    """Final result delivered by the orchestrator."""

    structured: StructuredLocation | None = None
    coordinates: tuple[float, float] | None = None
    source: LocationSource = "none"
