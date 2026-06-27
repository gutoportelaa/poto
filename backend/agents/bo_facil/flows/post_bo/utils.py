import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.bo_facil.core.states import BOState
    from agents.bo_facil.flows.post_bo.models import ApiResponse, IncidentPayload

from agents.bo_facil.core.states import (
    IdentityInfo,
    IncidentInfo,
    ObjectsInfo,
    PersonsInfo,
    UserInfo,
    VictimInfo,
    get_state_field,
)
from core.observability import traced_external_call

logger = logging.getLogger(__name__)

# Maps full state names (lowercase, no accents) to 2-letter UF codes.
_STATE_TO_UF = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}
_VALID_UFS = set(_STATE_TO_UF.values())

# Detects any Brazilian UF (2-letter state code) as a standalone word
_BR_UF_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_VALID_UFS)) + r")\b",
    re.IGNORECASE,
)

# Detects any Brazilian state name (accent-insensitive via alt chars)
_BR_STATE_NAME_PATTERN = re.compile(
    r"\b(Acre|Alagoas|Amap[aá]|Amazonas|Bahia|Cear[aá]|Distrito\s+Federal|"
    r"Esp[ií]rito\s+Santo|Goi[aá]s|Maranh[aã]o|Mato\s+Grosso(?:\s+do\s+Sul)?|"
    r"Minas\s+Gerais|Par[aá]|Para[ií]ba|Paran[aá]|Pernambuco|Piau[ií]|"
    r"Rio\s+de\s+Janeiro|Rio\s+Grande\s+do\s+Norte|Rio\s+Grande\s+do\s+Sul|"
    r"Rond[oô]nia|Roraima|Santa\s+Catarina|S[aã]o\s+Paulo|Sergipe|Tocantins)\b",
    re.IGNORECASE,
)


def _has_br_state(text: str) -> bool:
    """Check if text mentions any Brazilian state (UF or full name)."""
    return bool(_BR_UF_PATTERN.search(text) or _BR_STATE_NAME_PATTERN.search(text))


# Detects strings that are just lat/long coordinates (e.g. "-5.116936, -42.794312")
_COORDINATES_ONLY_PATTERN = re.compile(r"^\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*$")


def _is_coordinates_only(text: str | None) -> bool:
    """Check if text is just lat/long coordinates (no actual address)."""
    if not text:
        return False
    return bool(_COORDINATES_ONLY_PATTERN.match(text.strip()))


def _strip_accents_simple(text: str) -> str:
    """Remove accents for lookup: 'Piauí' → 'Piaui'."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_state(raw: str) -> str:
    """Normalize geocoding state to 2-letter UF.

    Handles: 'State of Piauí' → 'PI', 'MARANHÃO' → 'MA', 'PI' → 'PI'.
    """
    cleaned = re.sub(r"(?i)^state\s+of\s+", "", raw).strip()
    cleaned_key = _strip_accents_simple(cleaned).lower()
    if uf := _STATE_TO_UF.get(cleaned_key):
        return uf
    if cleaned.upper() in _VALID_UFS:
        return cleaned.upper()
    return raw


def _safe_int_id(value: str | None, field_name: str) -> int | None:
    """Convert string ID to int with explicit logging on failure."""
    if not value:
        logger.warning(f"[build_incident_payload] {field_name} is missing (None)")
        return None
    if not value.isdigit():
        logger.warning(f"[build_incident_payload] {field_name} is not numeric: {value!r}")
        return None
    return int(value)


def _format_datetime(dt) -> str:
    """Format datetime to API format.

    Since datetime is now stored as string in "YYYY-MM-DD HH:MM" format,
    this function simply validates and returns the string.
    """
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    # Fallback for legacy datetime objects (should not occur)
    try:
        from datetime import datetime

        return dt.strftime("%Y-%m-%d %H:%M") if isinstance(dt, datetime) else ""
    except Exception:
        return ""


def _normalize_cpf(cpf: str) -> str:
    """Normalize CPF to numbers only, return empty if invalid."""
    if not cpf:
        return ""

    digits = "".join(filter(str.isdigit, cpf))
    return digits if len(digits) == 11 and len(set(digits)) > 1 else ""


@traced_external_call(name="pdf_generation", dep="pdf_api")
async def call_pdf_generation_api(payload: "IncidentPayload") -> "ApiResponse | None":
    """Call PDF generation API."""
    import httpx

    from core.settings import settings

    if not settings.PDF_API_KEY:
        logger.warning("PDF_API_KEY not configured")
        return None

    if not payload.pessoa.cpf:
        logger.warning("Cannot generate PDF: CPF is required but not provided")
        return None

    from uuid import uuid4

    headers = {
        "accept": "application/json",
        "authorization": settings.PDF_API_KEY.get_secret_value(),
        "Content-Type": "application/json",
        "X-Idempotency-Key": str(uuid4()),
    }

    try:
        # Send null fields explicitly — their renderer shows "NÃO INFORMADO"
        # for null values but "UNDEFINED" when fields are absent from JSON.
        payload_dict = payload.model_dump(exclude_none=False)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(settings.PDF_API_URL, headers=headers, json=payload_dict)

            if response.status_code == 200:
                from agents.bo_facil.flows.post_bo.models import ApiResponse

                body_preview = response.text[:2000]
                logger.info(f"[call_pdf_generation_api] 200 OK — body: {body_preview}")
                try:
                    api_response = ApiResponse(**response.json())
                except Exception as parse_error:
                    # API accepted the payload (HTTP 200) but the response
                    # doesn't match our schema. The BO was almost certainly
                    # created on their side — retrying would duplicate it.
                    # Return a partial ApiResponse with protocolo=None so the
                    # caller can treat this as "do not retry".
                    logger.error(
                        f"[call_pdf_generation_api] 200 OK but response parse "
                        f"failed — BO may already exist upstream, NOT retrying. "
                        f"Error: {parse_error}. Body: {body_preview}"
                    )
                    try:
                        return ApiResponse(
                            protocolo=None, ocorrencia=response.json().get("ocorrencia", {})
                        )
                    except Exception:
                        # Even the partial response failed — return empty shell
                        # just so the caller sees "don't retry" signal.
                        return ApiResponse.model_construct(protocolo=None, ocorrencia=None)
                return api_response
            else:
                logger.error(
                    f"PDF API error - Status: {response.status_code}, "
                    f"Response: {response.text[:500]}"
                )
                if 400 <= response.status_code < 500:
                    # Client error — same payload will always fail, don't retry
                    return ApiResponse.model_construct(protocolo=None, ocorrencia=None)

    except Exception as e:
        logger.error(f"PDF API error: {e}", exc_info=True)

    return None


def _build_objects_list(bo_objects: list[dict] | None) -> list:
    """Convert BOObject list to API format."""
    from agents.bo_facil.flows.post_bo.models import IncidentObject

    if not bo_objects:
        return []

    objects = []
    seen_descriptions = set()  # Track descriptions to avoid duplicates

    tipo_objeto_map = {
        "celular": "celular",
        "documento": "documento",
        "carro": "veiculo",
        "moto": "veiculo",
        "outro": "outros",
    }

    tipo_veiculo_map = {
        "carro": "Carro",
        "moto": "Moto",
    }

    for obj in bo_objects:
        obj_type = obj.get("type", "outro")
        tipo_objeto = tipo_objeto_map.get(obj_type, "outros")

        # Build description based on object type
        description_parts = [obj.get("name", "")]

        if obj_type == "celular":
            details = []
            if obj.get("brand"):
                details.append(f"Marca: {obj['brand']}")
            if obj.get("model"):
                details.append(f"Modelo: {obj['model']}")
            if obj.get("color"):
                details.append(f"Cor: {obj['color']}")
            if obj.get("imei"):
                details.append(f"IMEI: {obj['imei']}")
            if details:
                description_parts.append(" - " + ", ".join(details))
        elif obj_type in ("carro", "moto"):
            details = []
            if obj.get("brand"):
                details.append(f"Marca: {obj['brand']}")
            if obj.get("model"):
                details.append(f"Modelo: {obj['model']}")
            if obj.get("color"):
                details.append(f"Cor: {obj['color']}")
            if obj.get("plate"):
                details.append(f"Placa: {obj['plate']}")
            if details:
                description_parts.append(" - " + ", ".join(details))
            elif obj.get("description"):
                description_parts.append(f" - {obj['description']}")
        elif obj_type == "documento":
            if obj.get("document_number"):
                description_parts.append(f" - Nº: {obj['document_number']}")
        elif obj.get("description"):
            description_parts.append(f" - {obj['description']}")

        description = "".join(description_parts)

        # Create unique key for deduplication (type + description)
        unique_key = f"{tipo_objeto}|{description.lower()}"

        # Only add if not seen before
        if unique_key not in seen_descriptions:
            seen_descriptions.add(unique_key)

            # Build structured fields per object type
            structured = {}
            if obj_type == "celular":
                structured = {
                    "marca": obj.get("brand"),
                    "modelo": obj.get("model"),
                    "cor": obj.get("color"),
                    "nr_imei": obj.get("imei"),
                }
            elif obj_type in ("carro", "moto"):
                structured = {
                    "marca": obj.get("brand"),
                    "modelo": obj.get("model"),
                    "cor": obj.get("color"),
                    "tipo_veiculo": tipo_veiculo_map.get(obj_type),
                    "placa": obj.get("plate"),
                }
            elif obj_type == "documento":
                structured = {
                    "numero_documento": obj.get("document_number"),
                }

            # Remove None values
            structured = {k: v for k, v in structured.items() if v}

            objects.append(
                IncidentObject(
                    tipo_objeto=tipo_objeto,
                    descricao=description,
                    **structured,
                )
            )

    return objects


def _build_weapons_list(bo_weapons: list[dict] | None) -> tuple[list[dict], str | None]:
    """Convert BOWeapon list to API objetos_utilizados format.

    Returns:
        Tuple of (objetos_utilizados list, meios_empregados summary string)
    """
    if not bo_weapons:
        return [], None

    objetos = []
    meios_parts = []

    for weapon in bo_weapons:
        tipo = weapon.get("type", "outro")
        desc = weapon.get("description")

        obj = {"tipo_objeto": tipo}
        if desc:
            obj["descricao"] = desc

        objetos.append(obj)
        meios_parts.append(f"{tipo} ({desc})" if desc else tipo)

    meios_empregados = ", ".join(meios_parts) if meios_parts else None
    return objetos, meios_empregados


def _build_involved_persons_list(bo_persons: list[dict] | None, reporter_cpf: str | None) -> list:
    """Convert BOPerson list to API format.

    Args:
        bo_persons: List of persons from state
        reporter_cpf: CPF of the person making the report (denunciante)

    Returns:
        List of InvolvedPerson dicts in API format

    Notes:
        Type mapping (per API contract):
        - 1: Comunicante (reporter — added automatically by API)
        - 2: Vítima
        - 3: Suspeito
        - 4: Testemunha
        - 99: Outros
    """
    from agents.bo_facil.flows.post_bo.models import InvolvedPerson

    if not bo_persons:
        return []

    involved = []
    for person in bo_persons:
        person_type = person.get("type", "outro_envolvido")

        # Map person type to API type codes
        type_code_map = {
            "suspeito": 3,
            "testemunha": 4,
            "outro_envolvido": 99,
        }
        type_code = type_code_map.get(person_type, 99)

        # Map to ds_envolvimento (required by API)
        envolvimento_map = {
            3: "Suposto Autor do Fato",
            4: "Testemunha",
            99: "Outros",
        }
        ds_envolvimento = envolvimento_map.get(type_code, "Outros")

        # Get person data
        person_name = person.get("name", "")
        person_description = person.get("description", "")
        person_cpf = _normalize_cpf(person.get("cpf", "")) if person.get("cpf") else ""

        # ds_envolvido should contain the description/characteristics
        # If no description, use the name field (which might be "SUSPEITO 1", etc.)
        ds_envolvido = person_description if person_description else person_name
        if not ds_envolvido:
            ds_envolvido = "NÃO INFORMADO"

        # nome_envolvido should only contain real names, not labels like "SUSPEITO 1"
        # Check if name looks like a label (contains numbers or starts with generic terms)
        nome_envolvido = None
        if person_name:
            # Remove if contains digits (like "Suspeito 1", "Testemunha 2")
            has_digits = any(char.isdigit() for char in person_name)

            # Check if starts with generic placeholder terms
            generic_starts = [
                "suspeito",
                "testemunha",
                "envolvido",
                "desconhecido",
                "não informado",
            ]
            is_generic = any(person_name.lower().startswith(generic) for generic in generic_starts)

            # If it's not a label/placeholder, it's a real name
            if not has_digits and not is_generic:
                nome_envolvido = person_name

        # Add to list
        involved.append(
            InvolvedPerson(
                type=type_code,
                ds_envolvimento=ds_envolvimento,
                nome_envolvido=nome_envolvido,
                cpf=person_cpf,
                ds_envolvido=ds_envolvido,
            )
        )

    return involved


def _normalize_address(address: str, city_hint: str | None = None) -> str:
    """Normalize informal address for geocoding API.

    Removes noise like "BLOCO 02", "Lote 5" that confuse geocoders.
    Preserves "quadra" and "casa" (essential for conjuntos habitacionais).
    Cleans up "Rua: Sete" → "Rua Sete" and adds city/state suffix if missing.
    """
    normalized = address.strip()

    # Skip all normalization for coordinate-only input — no street to clean,
    # and adding ", PI" breaks the geocoder for WhatsApp coordinates.
    if _is_coordinates_only(normalized):
        return normalized

    # Remove colon after address type (Rua: Sete → Rua Sete)
    normalized = re.sub(r"(\w+)\s*:\s*", r"\1 ", normalized)

    # Strip "N°/Nº/No" prefix but keep the number (N° 123 → 123)
    normalized = re.sub(r"\bn[°ºo]\s*(\d+)", r"\1", normalized, flags=re.IGNORECASE)

    # Remove terms that confuse geocoding (keep quadra/casa — essential for conjuntos)
    noise_patterns = [
        r"\bbloco\s+\w+\b",
        r"\blotes?\s+\w+\b",
        r"\bapto?\s*\.?\s*\w+\b",
    ]
    for pattern in noise_patterns:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

    # Clean up orphan commas and duplicate spaces
    normalized = re.sub(r"(\s*,\s*)+", ", ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(", ")

    # Add city context if no city is detected and a hint is provided
    known_cities = r"\b(?:Teresina|Parnaíba|Picos|Piripiri|Floriano|Campo Maior|Barras|Oeiras)\b"
    if city_hint and not re.search(known_cities, normalized, re.IGNORECASE):
        normalized = f"{normalized}, {city_hint}"

    # Only inject ", PI" when NO Brazilian state is mentioned
    # Service is PI-based but receives addresses from other states
    if not _has_br_state(normalized):
        normalized = f"{normalized}, PI"

    return normalized


def _extract_structured_fields(
    incident, location: str | None
) -> tuple[str | None, str | None, str | None]:
    """Extract (logradouro, bairro, municipio) for the API payload.

    Primary: `incident.structured` populated by the 3-layer extractor (Phase 2+).
    Fallback: legacy `incident.geocoded_data` for checkpoints in flight during
    the Phase 2 deploy. Fallback will be removed in Phase 3.
    """
    # Primary: new structured field
    s = incident.structured
    if s and s.municipio and s.uf:
        logradouro = s.logradouro
        bairro = s.bairro
        municipio = f"{s.municipio} - {s.uf}"
        logger.info(
            f"[build_incident_payload] Using structured data - "
            f"Logradouro: {logradouro}, Bairro: {bairro}, Municipio: {municipio}"
        )
        return logradouro, bairro, municipio

    # Fallback: legacy geocoded_data
    geocoded = incident.geocoded_data
    if geocoded and geocoded.get("_valid_address"):
        logradouro_parts = []
        if geocoded.get("Rua"):
            logradouro_parts.append(geocoded["Rua"])
        if geocoded.get("Número"):
            logradouro_parts.append(f"nº {geocoded['Número']}")
        logradouro = ", ".join(logradouro_parts) if logradouro_parts else None
        bairro = geocoded.get("Bairro") or None
        municipio_parts = []
        if geocoded.get("Cidade"):
            municipio_parts.append(geocoded["Cidade"])
        if geocoded.get("Estado"):
            municipio_parts.append(geocoded["Estado"])
        municipio = " - ".join(municipio_parts) if municipio_parts else None
        logger.info(
            f"[build_incident_payload] Using legacy geocoded data (fallback) - "
            f"Logradouro: {logradouro}, Bairro: {bairro}, Municipio: {municipio}"
        )
        return logradouro, bairro, municipio

    if location:
        logger.info(
            f"[build_incident_payload] No structured data — "
            f"sending only ponto_referencia: {location!r}"
        )
    return None, None, None


def _is_generic_pi_fallback(geo: dict) -> bool:
    """Detect geocode result that's a generic Piauí fallback (state-only, no useful data).

    This pattern appears when the ", PI" injection confuses the geocoder for
    addresses outside Piauí — the API returns valid_address=false with the state
    defaulted to PI but no street or city resolved.
    """
    return (
        not geo.get("_valid_address")
        and not geo.get("Cidade")
        and not geo.get("Rua")
        and str(geo.get("Estado", "")).upper() == "PI"
    )


@traced_external_call(name="geocode_request", dep="geocode")
async def _geocode_request(clean_address: str, retries: int) -> dict | None:
    """Execute HTTP request to geocoding API with retry logic.

    Returns the geocoded data dict (with _valid_address flag) or None on failure.
    """
    import asyncio

    import httpx

    from core.settings import settings

    last_error = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    settings.GEOCODING_API_URL,
                    params={"address": clean_address},
                )

                if response.status_code == 200:
                    data = response.json()
                    geo = data.get("data")
                    if not geo:
                        logger.warning(
                            f"[_geocode_request] No data in response for: {clean_address}"
                        )
                        return None

                    # Normalize state to 2-letter UF (e.g. "State of Piauí" → "PI")
                    if geo.get("Estado"):
                        geo["Estado"] = _normalize_state(geo["Estado"])

                    has_coordinates = (
                        geo.get("latitude") is not None or geo.get("Latitude") is not None
                    )
                    has_city = bool(geo.get("Cidade"))

                    if data.get("valid_address"):
                        logger.info(f"[_geocode_request] Valid geocode: {clean_address}")
                        geo["_valid_address"] = True
                        return geo
                    elif has_coordinates or has_city:
                        logger.info(
                            f"[_geocode_request] Partial geocode (valid_address=false) "
                            f"with useful data for: {clean_address}"
                        )
                        geo["_valid_address"] = False
                        return geo
                    else:
                        logger.warning(f"[_geocode_request] No useful data for: {clean_address}")
                        return None

                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    f"[_geocode_request] HTTP {response.status_code} for: {clean_address} "
                    f"(attempt {attempt + 1}/{retries})"
                )

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[_geocode_request] Attempt {attempt + 1}/{retries} failed: {e}")

        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (2**attempt))

    logger.error(
        f"[_geocode_request] All {retries} attempts failed for: {clean_address}. "
        f"Last error: {last_error}"
    )
    return None


async def _geocode_address(
    address: str, retries: int = 3, city_hint: str | None = None
) -> dict | None:
    """Call geocoding API to get structured address components.

    Two-layer protection for addresses outside Piauí:
    - Layer 1: _normalize_address skips ", PI" injection when text mentions any state
    - Layer 2: if geocode returns generic PI fallback, retry without ", PI" suffix

    Args:
        address: Free-form address string
        retries: Number of HTTP retry attempts per request
        city_hint: Expected city (e.g. "Teresina") — appended if no city in address

    Returns:
        Dictionary with structured address data (includes _valid_address flag)
        or None if unreachable/no useful data.
    """
    if not address or not address.strip():
        return None

    clean_address = _normalize_address(address, city_hint=city_hint)
    if clean_address != address.strip():
        logger.info(f"[_geocode_address] Normalized: '{address.strip()}' → '{clean_address}'")

    result = await _geocode_request(clean_address, retries)

    # Layer 2: retry without ", PI" if result is generic PI fallback
    # and original address didn't mention PI explicitly
    if (
        result
        and _is_generic_pi_fallback(result)
        and clean_address.endswith(", PI")
        and not re.search(r"\bPI\b|\bPiau[ií]\b", address, re.IGNORECASE)
    ):
        retry_address = clean_address.removesuffix(", PI").rstrip(", ")
        logger.info(
            f"[_geocode_address] Generic PI fallback detected, "
            f"retrying without state suffix: '{retry_address}'"
        )
        retry_result = await _geocode_request(retry_address, retries)
        if retry_result and not _is_generic_pi_fallback(retry_result):
            return retry_result
        return None

    return result


# Violência Doméstica Contra Mulher, Violência Escolar, Desaparecimento de Pessoa
_PRIORITY_CODES = {10000, 30, 500}


def _resolve_priority_status(type_codes: list[str] | None) -> int | None:
    """Return status id 6 (Prioridade) if incident involves priority crime types."""
    if not type_codes:
        return None
    codes = {int(c) for c in type_codes}
    matched = _PRIORITY_CODES & codes
    if matched:
        names = {
            10000: "Violência Doméstica Contra Mulher",
            30: "Violência Escolar",
            500: "Desaparecimento de Pessoa",
        }
        logger.info(f"[priority] id_status=6 — {', '.join(names[c] for c in matched)}")
        return 6
    return None


async def build_incident_payload(state: "BOState") -> "IncidentPayload | None":
    """Build API payload from state data.

    Uses geocoding API to resolve location into structured address components.

    Returns:
        IncidentPayload if successful, None if required data (CPF) is missing
    """
    from agents.bo_facil.flows.post_bo.models import Address, IncidentPayload, Person

    user = get_state_field(state, "user", UserInfo)
    identity = get_state_field(state, "identity", IdentityInfo)
    incident = get_state_field(state, "incident", IncidentInfo)
    objects_info = get_state_field(state, "objects", ObjectsInfo)
    persons_info = get_state_field(state, "persons", PersonsInfo)

    bio = identity.biographical_data or {}
    victim = get_state_field(state, "victim", VictimInfo)

    reporter_cpf = _normalize_cpf(bio.get("cpf", ""))
    if not reporter_cpf:
        if identity.proceed_without_cpf:
            if identity.cpf_validated and identity.cpf_input:
                reporter_cpf = _normalize_cpf(identity.cpf_input)
                logger.info(
                    "[build_incident_payload] Using user-informed CPF "
                    "(proceed_without_cpf=True, cpf_validated=True)"
                )
            else:
                reporter_cpf = "00000000000"
                logger.info(
                    "[build_incident_payload] Using anonymous CPF fallback "
                    "(proceed_without_cpf=True, cpf_validated=False)"
                )
        else:
            logger.warning(
                "[build_incident_payload] Cannot build payload: valid CPF is required for PDF generation"
            )
            return None

    addr = bio.get("residentialAdress", {})
    location = incident.location

    # Primary source: structured data populated by the 3-layer extractor (Phase 2+).
    # Fallback: legacy geocoded_data for checkpoints created before the migration.
    logradouro_fato, bairro_fato, municipio_fato = _extract_structured_fields(incident, location)

    # Coordinates: new list form takes precedence; fall back to legacy lat/long.
    if incident.coordinates:
        lat, long = incident.coordinates[0], incident.coordinates[1]
    else:
        lat, long = incident.latitude, incident.longitude

    # Extract contact phone (priority: GovChat phone > bio data)
    phone = user.phone or bio.get("phone") or bio.get("phoneNumber") or None

    # Use description from state (generated during summary creation)
    description = incident.description or incident.fact or ""

    # Build weapons / objetos_utilizados
    objetos_utilizados, meios_empregados = _build_weapons_list(objects_info.weapons)

    # Build involved persons list (suspects, witnesses, etc.)
    involved_persons = _build_involved_persons_list(persons_info.items, reporter_cpf)
    # Reporter is NOT added here — the API creates envolvido type="1" automatically from `pessoa`

    # Add victim as involved person (type=2) if third-party reporter provided data
    if victim.is_third_party and (victim.name or victim.cpf):
        from agents.bo_facil.flows.post_bo.models import InvolvedPerson

        victim_cpf = _normalize_cpf(victim.cpf) if victim.cpf else ""
        involved_persons.append(
            InvolvedPerson(
                type=2,
                ds_envolvimento="Vítima",
                nome_envolvido=victim.name or None,
                cpf=victim_cpf,
                ds_envolvido=victim.name or "VÍTIMA NÃO IDENTIFICADA",
            )
        )

    # Coordinates have dedicated lat/long fields — don't duplicate them as text
    ponto_referencia_value = (
        None if _is_coordinates_only(incident.reference_point) else incident.reference_point
    )

    payload = IncidentPayload(
        pessoa=Person(
            cpf=reporter_cpf,
            nome_completo=bio.get("name") or victim.reporter_name or None,
            nome_completo_mae=bio.get("motherName") or None,
            telefone_contato=phone,
            email_contato=bio.get("email") or None,
            naturalidade=identity.birth_city_provided or bio.get("birthCity") or None,
            nacionalidade=bio.get("nationality") or None,
            data_nascimento=bio.get("birthDate") or bio.get("birhDate") or None,
            profissao=bio.get("profession") or None,
            sexo=bio.get("gender") or None,
            estado_civil=bio.get("maritalStatus") or None,
            endereco=Address(
                cep=addr.get("zipCode") or None,
                rua=addr.get("publicPark") or None,
                numero=addr.get("number") or None,
                bairro=addr.get("neighborhood") or None,
                cidade=addr.get("city") or None,
                estado=addr.get("stateAcronyn") or None,
                ponto_referencia=None,
            )
            if any(addr.values())
            else None,
        ),
        descricao_fato=description,
        municipio_fato=municipio_fato,
        bairro_fato=bairro_fato,
        logradouro_fato=logradouro_fato,
        lat=lat,
        long=long,
        ponto_referencia=ponto_referencia_value,
        tipo_local_fato=None,
        momento_fato=_format_datetime(incident.datetime) or None,
        tipo_ocorrencia=[int(code) for code in incident.type_codes]
        if incident.type_codes
        else None,
        id_status=_resolve_priority_status(incident.type_codes),
        meios_empregados=meios_empregados,
        objetos_utilizados=objetos_utilizados,
        objetosOcorrencia=_build_objects_list(objects_info.items),
        envolvidos=involved_persons,
        canal="Chatbot",
        conversation_id=_safe_int_id(user.conversation_id, "conversation_id"),
        inbox_id=_safe_int_id(user.inbox_id, "inbox_id"),
        account_id=_safe_int_id(user.account_id, "account_id"),
    )

    # Log the full payload for field-by-field validation
    import json

    try:
        payload_json = json.dumps(
            payload.model_dump(exclude_none=False),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        logger.info(f"[build_incident_payload] Full payload:\n{payload_json}")
    except Exception as e:
        logger.warning(f"[build_incident_payload] Could not serialize payload for log: {e}")

    return payload
