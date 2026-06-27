import asyncio
import logging
import random
import re

import httpx

from core.observability import traced_external_call
from core.settings import settings

logger = logging.getLogger(__name__)

_IBIOSEG_TIMEOUT = 5.0


def validate_cpf_format(cpf: str) -> bool:
    """Validate CPF format and check digits."""
    if not cpf:
        return False

    cleaned = re.sub(r"\D", "", cpf)

    if len(cleaned) != 11 or not cleaned.isdigit():
        return False

    if len(set(cleaned)) == 1:
        return False

    total = sum(int(cleaned[i]) * (10 - i) for i in range(9))
    remainder = total % 11
    if int(cleaned[9]) != (0 if remainder < 2 else 11 - remainder):
        return False

    total = sum(int(cleaned[i]) * (11 - i) for i in range(10))
    remainder = total % 11
    return int(cleaned[10]) == (0 if remainder < 2 else 11 - remainder)


def clean_cpf(cpf: str) -> str:
    """Clean CPF keeping only numeric digits"""
    return re.sub(r"\D", "", cpf)


@traced_external_call(name="ibioseg_lookup", dep="ibioseg")
async def _call_ibioseg_api_impl(cpf: str) -> dict:
    base_url = settings.IBIOSEG_API_URL
    url = f"{base_url}/{cpf}"

    headers = {"Accept": "application/json"}
    if settings.IBIOSEG_API_KEY:
        headers["x-api-key"] = settings.IBIOSEG_API_KEY.get_secret_value()

    try:
        async with httpx.AsyncClient(timeout=_IBIOSEG_TIMEOUT) as client:
            response = await client.get(url, params={"includeRfb": "true"}, headers=headers)

        if response.status_code == 200:
            logger.info("[call_ibioseg_api] Successfully retrieved data for CPF")
            return response.json()

        if response.status_code == 404:
            logger.warning("[call_ibioseg_api] CPF not found in IBioSeg")
            return {"error": "cpf_not_found"}

        logger.error(f"[call_ibioseg_api] API error {response.status_code}")
        return {"error": "api_error", "status_code": response.status_code}

    except httpx.TimeoutException:
        logger.warning("[call_ibioseg_api] Timeout calling IBioSeg API")
        return {"error": "timeout"}
    except httpx.NetworkError as e:
        logger.warning(f"[call_ibioseg_api] Network error calling IBioSeg API: {e}")
        return {"error": "network_error", "details": str(e)}
    except Exception as e:
        logger.error(f"[call_ibioseg_api] Unexpected error: {e}")
        return {"error": "network_error", "details": str(e)}


async def call_ibioseg_api(cpf: str) -> dict:
    """Call IBioSeg API to get biographical data."""
    try:
        return await asyncio.wait_for(_call_ibioseg_api_impl(cpf), timeout=_IBIOSEG_TIMEOUT)
    except TimeoutError:
        logger.warning(f"[call_ibioseg_api] Total timeout of {_IBIOSEG_TIMEOUT}s exceeded")
        return {"error": "timeout"}


def generate_birth_year_options(birth_year: int) -> list[int]:
    """Generate 3 year options (1 correct + 2 random from 1970-2017)"""
    if not birth_year:
        return []

    # Generate range excluding the correct year
    year_range = list(range(1970, 2018))
    if birth_year in year_range:
        year_range.remove(birth_year)

    # Pick 2 random years from the range
    random_years = random.sample(year_range, 2)

    # Create list with correct year + random years
    options = [birth_year] + random_years

    # Shuffle the options
    return shuffle_options(options)


def shuffle_options(options: list) -> list:
    """Shuffle options using Fisher-Yates algorithm"""
    shuffled = options.copy()
    random.shuffle(shuffled)
    return shuffled


def validate_city_input(text: str) -> bool:
    """Validate that input looks like a city name, not arbitrary text."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    if len(stripped) > 100:
        return False
    if len(stripped.split()) > 10:
        return False
    return True


def get_birth_date(biographical_data: dict) -> str | None:
    """Extract birth date handling API typo ('birhDate' vs 'birthDate')."""
    return biographical_data.get("birthDate") or biographical_data.get("birhDate")
