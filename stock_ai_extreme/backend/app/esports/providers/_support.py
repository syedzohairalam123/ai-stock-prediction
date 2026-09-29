"""
Shared support helpers for the real esports provider adapters (Phase 21B).

The Phase 21A adapters were interface stubs. Phase 21B wires them to real,
keyless public feeds (csapi.de, lolesports.com, opendota.com). Those feeds are
rate-limited and return large payloads, so every adapter needs the same three
things: a small async TTL cache, a stable short-id helper, and defensive
parsing that never invents a value.

Nothing here fabricates data: a field the upstream does not publish is
returned as ``None``/``0`` exactly as the source gave it, and a number that
cannot be parsed is dropped rather than guessed.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional


def utcnow() -> datetime:
    """Timezone-aware UTC now (the stored/emitted timestamp convention)."""
    return datetime.now(timezone.utc)


def from_epoch(seconds: Any) -> Optional[datetime]:
    """Convert a unix timestamp (int/float/str) to an aware datetime, or None."""
    if seconds is None or seconds == "":
        return None
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string (with a trailing ``Z``) into an aware datetime."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int conversion that never raises."""
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any) -> Optional[float]:
    """Best-effort float conversion; unparseable input becomes None (never 0)."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(value: str, max_length: int = 28) -> str:
    """A short, url/id-safe slug derived from a display string."""
    cleaned = _SLUG_RE.sub("-", (value or "").strip().lower()).strip("-")
    if not cleaned:
        cleaned = "unknown"
    return cleaned[:max_length].strip("-") or "unknown"


def short_hash(value: str, length: int = 6) -> str:
    """Deterministic short hash — stable across restarts for the same input."""
    return hashlib.sha1(value.encode("utf-8", "ignore")).hexdigest()[:length]


def make_id(prefix: str, *parts: Any, max_length: int = 48) -> str:
    """
    Build a stable, collision-resistant internal id.

    Provider ids are namespaced behind a short prefix (``cs2-m2396949``) so a
    CS2 match and a Dota match sharing a numeric id can never collide, and the
    adapter that owns an id can be recovered from the prefix. Long composite
    parts are shortened with a deterministic hash to respect the DB column.
    """
    raw = "-".join(str(part) for part in parts if part not in (None, ""))
    candidate = f"{prefix}{raw}"
    if len(candidate) <= max_length:
        return candidate
    digest = short_hash(candidate)
    keep = max_length - len(digest) - 2
    return f"{candidate[:keep]}-{digest}"


class AsyncTTLCache:
    """
    Minimal async TTL cache used inside a single adapter instance.

    One cache per adapter keeps upstream request volume low enough for the
    free tier of every configured source: repeated UI reads within the TTL hit
    the cache, and a background refresh happens on the next request after it
    expires. Deliberately not shared across adapters — each source has its own
    freshness budget.
    """

    def __init__(self) -> None:
        self._store: Dict[str, tuple[float, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def get_or_set(
        self,
        key: str,
        ttl_seconds: float,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        """
        Return a cached value, or await ``factory`` to populate it.

        The per-key lock means concurrent readers of the same key trigger a
        single upstream request (thundering-herd protection). ``factory`` runs
        while the lock is held but exceptions propagate without caching, so a
        transient failure is retried on the next call instead of being pinned.
        """
        now = time.monotonic()
        entry = self._store.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]

        lock = await self._lock_for(key)
        async with lock:
            # Re-check: another waiter may have filled it while we queued.
            now = time.monotonic()
            entry = self._store.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]
            value = await factory()
            self._store[key] = (now + ttl_seconds, value)
            return value

    def peek(self, key: str) -> Optional[Any]:
        """Return a cached value even if expired (used only for stale fallback)."""
        entry = self._store.get(key)
        return entry[1] if entry is not None else None

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)
