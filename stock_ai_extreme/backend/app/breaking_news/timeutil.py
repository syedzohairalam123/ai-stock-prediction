"""
Time helpers for Phase 17.

The rest of the terminal stores naive-UTC datetimes in the database (SQLAlchemy's
SQLite DATETIME type drops tzinfo), while the news providers hand back
tz-aware timestamps. Mixing the two silently produces ``TypeError: can't
compare offset-naive and offset-aware datetimes`` — or, worse, an "N hours ago"
label that is off by the machine's UTC offset.

Every timestamp that enters or leaves this package therefore goes through these
helpers: aware in memory, naive-UTC in the database, and never assumed to be
either without checking.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

UTC = timezone.utc


def utcnow() -> datetime:
    """Current UTC time, naive — the single representation used for storage."""
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    """Attach UTC to a naive datetime; pass an aware one through unchanged."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime to naive UTC (the storage representation)."""
    aware = ensure_aware(value)
    if aware is None:
        return None
    return aware.astimezone(UTC).replace(tzinfo=None)


def parse_datetime(value: Any) -> Optional[datetime]:
    """Best-effort parse of the timestamp shapes the app meets in practice.

    Accepts ``datetime``, ISO-8601 strings (with or without ``Z``), and numeric
    epoch seconds. Returns a naive-UTC datetime, or ``None`` when the value is
    genuinely unusable — callers must treat ``None`` as "no timestamp", never
    substitute the current time.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_naive_utc(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return to_naive_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
        try:
            return datetime.fromtimestamp(float(text), tz=UTC).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None
    return None


def age_minutes(published_at: Optional[datetime], *, now: Optional[datetime] = None) -> Optional[float]:
    """Age of a timestamp in minutes — ``None`` when there is no timestamp.

    Never falls back to "0 minutes ago": an article whose publisher gave no
    timestamp is reported as having no timestamp, not as brand new.
    """
    published = ensure_aware(published_at)
    if published is None:
        return None
    reference = ensure_aware(now) or datetime.now(UTC)
    return (reference - published).total_seconds() / 60.0


def iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 string (with UTC offset) for a stored timestamp."""
    aware = ensure_aware(value)
    return aware.isoformat() if aware else None


__all__ = [
    "UTC",
    "utcnow",
    "ensure_aware",
    "to_naive_utc",
    "parse_datetime",
    "age_minutes",
    "iso",
]
