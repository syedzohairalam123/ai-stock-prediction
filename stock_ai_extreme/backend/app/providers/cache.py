"""
A deliberately simple in-memory TTL cache (Phase 2).

Free market-data APIs are rate-limited (Alpha Vantage: ~25 requests/day on
its free tier; Finnhub is more generous but still capped). Caching is what
keeps a demo from getting itself rate-limited after a handful of clicks.

This is intentionally NOT Redis. Phase 3 adds a real database and can swap
this for a Redis-backed cache without changing any caller — everything here
goes through get()/set() only.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, default_ttl_seconds: int = 60):
        self._store: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl_seconds

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                # Expired for "fresh" purposes — but deliberately NOT deleted here.
                # get_stale() below relies on the entry still being present so a
                # total provider outage can still serve a last-resort STALE value.
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = self.default_ttl if ttl_seconds is None else ttl_seconds
        async with self._lock:
            self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    async def get_stale(self, key: str) -> Optional[Any]:
        """Return a value even if it's expired — used only as a last-resort fallback
        when every live provider has failed, so the UI can show STALE data instead
        of nothing at all. Never used for a first attempt."""
        async with self._lock:
            entry = self._store.get(key)
            return entry.value if entry is not None else None

    def size(self) -> int:
        return len(self._store)

    async def purge_expired(self, keep_for_stale_seconds: float = 3600) -> int:
        """Drop entries that have been expired for a while. Not called
        automatically — expired-but-recent entries are kept on purpose so
        get_stale() has something to serve during a provider outage. Wire
        this into a periodic background task (Phase 3) once the app runs
        long enough for unbounded growth to matter."""
        cutoff = time.monotonic() - keep_for_stale_seconds
        async with self._lock:
            dead = [k for k, e in self._store.items() if e.expires_at < cutoff]
            for k in dead:
                del self._store[k]
            return len(dead)
