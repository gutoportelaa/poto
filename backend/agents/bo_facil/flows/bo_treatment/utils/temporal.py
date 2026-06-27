"""Deterministic temporal reference resolution for Portuguese text.

Resolves relative date/time expressions (e.g., "ontem às 20h") into concrete
datetime values using pure Python regex — no LLM required. Used to provide
hints to the extraction prompt and as a fallback when the LLM fails to
compute datetime arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# =============================================================================
# Regex patterns
# =============================================================================

# Relative dates
_RELATIVE_DATE_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    # Order matters: longer/more specific patterns first to avoid partial matches
    (re.compile(r"\b(?:anteontem|antes\s+de\s+ontem)\b", re.IGNORECASE), -2),
    (re.compile(r"\bontem\b", re.IGNORECASE), -1),
    (re.compile(r"\b(?:hoje|agora)\b", re.IGNORECASE), 0),
    (re.compile(r"\bamanh[ãa]\b", re.IGNORECASE), +1),
]

# Absolute dates: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY (2 or 4-digit year)
_ABSOLUTE_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")

# Explicit times: 17h20, 17h, 20:30, às 15h30
_EXPLICIT_TIME_RE = re.compile(
    r"\b(\d{1,2})\s*[hH]\s*(\d{2})?\b"
    r"|"
    r"\b(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)

# Period-specific times: "8 da noite", "3 da manhã", "8 da manha"
_PERIOD_SPECIFIC_RE = re.compile(
    r"\b(\d{1,2})\s+(?:da\s+|das\s+)(manh[ãa]|noite|tarde|madrugada)\b",
    re.IGNORECASE,
)

# Generic period: "de manhã", "à tarde", "à noite", "de madrugada"
_GENERIC_PERIOD_RE = re.compile(
    r"\b(?:de|da|pela|à|a)\s+(manh[ãa]|tarde|noite|madrugada)\b",
    re.IGNORECASE,
)

_PERIOD_DEFAULTS: dict[str, tuple[int, int]] = {
    "manha": (9, 0),
    "manhã": (9, 0),
    "tarde": (15, 0),
    "noite": (20, 0),
    "madrugada": (2, 0),
}


def _normalize_period(period: str) -> str:
    """Normalize period string to key for lookup."""
    return period.lower().replace("ã", "a") if "ã" in period.lower() else period.lower()


def _period_hour_offset(hour: int, period: str) -> int:
    """Apply AM/PM-like offset based on Portuguese period."""
    p = _normalize_period(period)
    if p in ("noite", "madrugada"):
        # "8 da noite" → 20, "3 da madrugada" → 3 (already correct)
        if p == "noite" and hour < 12:
            return hour + 12
        return hour
    if p in ("manha", "manhã"):
        return hour  # "8 da manhã" → 8
    if p == "tarde":
        if hour < 12:
            return hour + 12
        return hour
    return hour


# =============================================================================
# TemporalHints dataclass
# =============================================================================


@dataclass
class TemporalHints:
    """Holds deterministically resolved temporal references."""

    resolved_date: str | None = None  # "YYYY-MM-DD"
    resolved_time: str | None = None  # "HH:MM"
    resolved_datetime: str | None = None  # "YYYY-MM-DD HH:MM"
    raw_date_expr: str | None = None  # e.g., "ontem"
    raw_time_expr: str | None = None  # e.g., "por volta das 20h"
    _merged: bool = field(default=False, repr=False)

    @property
    def has_date(self) -> bool:
        return self.resolved_date is not None

    @property
    def has_time(self) -> bool:
        return self.resolved_time is not None

    @property
    def has_datetime(self) -> bool:
        return self.resolved_datetime is not None

    def _combine(self) -> None:
        """If we have both date and time but no datetime, combine them."""
        if self.resolved_date and self.resolved_time and not self.resolved_datetime:
            self.resolved_datetime = f"{self.resolved_date} {self.resolved_time}"

    def to_prompt_hint(self) -> str:
        """Generate text for prompt injection. Returns '' if nothing resolved."""
        self._combine()
        if not self.resolved_date and not self.resolved_time:
            return ""

        parts: list[str] = ["DICA TEMPORAL PRE-RESOLVIDA (use estes valores):"]
        if self.raw_date_expr and self.resolved_date:
            parts.append(f"'{self.raw_date_expr}' = {self.resolved_date}")
        elif self.resolved_date:
            parts.append(f"DATA = {self.resolved_date}")

        if self.raw_time_expr and self.resolved_time:
            parts.append(f"'{self.raw_time_expr}' = {self.resolved_time}")
        elif self.resolved_time:
            parts.append(f"HORA = {self.resolved_time}")

        if self.resolved_datetime:
            parts.append(f"DATETIME COMBINADO = {self.resolved_datetime}")

        return "; ".join(parts)

    def merge(self, other: TemporalHints) -> TemporalHints:
        """Merge another hints object, filling in missing fields."""
        return TemporalHints(
            resolved_date=self.resolved_date or other.resolved_date,
            resolved_time=self.resolved_time or other.resolved_time,
            resolved_datetime=self.resolved_datetime or other.resolved_datetime,
            raw_date_expr=self.raw_date_expr or other.raw_date_expr,
            raw_time_expr=self.raw_time_expr or other.raw_time_expr,
        )


# =============================================================================
# Resolution functions
# =============================================================================


def _resolve_date(text: str, reference_dt: datetime) -> tuple[str | None, str | None]:
    """Resolve date reference from text. Returns (YYYY-MM-DD, raw_expr) or (None, None)."""
    # Check relative dates first
    for pattern, offset in _RELATIVE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            resolved = (reference_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            return resolved, m.group(0)

    # Check absolute dates
    m = _ABSOLUTE_DATE_RE.search(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 1900 if year >= 70 else 2000
        try:
            dt = datetime(year, month, day)
            return dt.strftime("%Y-%m-%d"), m.group(0)
        except ValueError:
            pass

    return None, None


def _resolve_time(text: str) -> tuple[str | None, str | None]:
    """Resolve time reference from text. Returns (HH:MM, raw_expr) or (None, None)."""
    # Check period-specific first: "8 da noite", "3 da manhã"
    m = _PERIOD_SPECIFIC_RE.search(text)
    if m:
        hour = int(m.group(1))
        period = m.group(2)
        hour = _period_hour_offset(hour, period)
        return f"{hour:02d}:00", m.group(0)

    # Check explicit times: 17h20, 17h, 20:30
    m = _EXPLICIT_TIME_RE.search(text)
    if m:
        if m.group(1) is not None:
            # Matched 17h20 or 17h pattern
            hour = int(m.group(1))
            minute = int(m.group(2)) if m.group(2) else 0
        else:
            # Matched 20:30 pattern
            hour = int(m.group(3))
            minute = int(m.group(4))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}", m.group(0)

    # Check generic period: "de manhã", "à tarde", etc.
    m = _GENERIC_PERIOD_RE.search(text)
    if m:
        period = _normalize_period(m.group(1))
        if period in _PERIOD_DEFAULTS:
            h, mn = _PERIOD_DEFAULTS[period]
            return f"{h:02d}:{mn:02d}", m.group(0)

    return None, None


def resolve_temporal_references(text: str, reference_dt: datetime) -> TemporalHints:
    """Resolve temporal references in Portuguese text deterministically.

    Args:
        text: User message text in Portuguese.
        reference_dt: Reference datetime (usually datetime.now()).

    Returns:
        TemporalHints with resolved date/time values.
    """
    date_str, raw_date = _resolve_date(text, reference_dt)
    time_str, raw_time = _resolve_time(text)

    hints = TemporalHints(
        resolved_date=date_str,
        resolved_time=time_str,
        raw_date_expr=raw_date,
        raw_time_expr=raw_time,
    )
    hints._combine()
    return hints


def validate_extracted_datetime(
    dt_str: str, now: datetime
) -> tuple[str, bool]:
    """Validate an extracted datetime is not in the future.

    Args:
        dt_str: Datetime string in "YYYY-MM-DD HH:MM" format.
        now: Current datetime for comparison.

    Returns:
        (result_dt_str, is_valid) tuple:
        - Past/present datetime → (dt_str, True)
        - Today + future time → (clamped_to_now_str, True)
        - Future date → (dt_str, False)
    """
    try:
        parsed = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return dt_str, True  # Can't parse → let through

    if parsed <= now:
        return dt_str, True

    # Future: distinguish same-day (clamp) vs different-day (reject)
    if parsed.date() == now.date():
        clamped = now.strftime("%Y-%m-%d %H:%M")
        return clamped, True
    else:
        return dt_str, False


def resolve_temporal_from_messages(messages: list, reference_dt: datetime) -> TemporalHints:
    """Scan recent user messages to combine date from one + time from another.

    Scans the last 6 user messages (most recent first), combining partial
    temporal information found across messages.

    Args:
        messages: List of LangChain message objects.
        reference_dt: Reference datetime (usually datetime.now()).

    Returns:
        TemporalHints with the best combined date/time from recent messages.
    """
    from langchain_core.messages import HumanMessage

    combined = TemporalHints()
    user_messages: list[str] = []

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            user_messages.append(content)
            if len(user_messages) >= 6:
                break

    for text in user_messages:
        hints = resolve_temporal_references(text, reference_dt)
        combined = combined.merge(hints)
        if combined.has_date and combined.has_time:
            break

    combined._combine()
    return combined
