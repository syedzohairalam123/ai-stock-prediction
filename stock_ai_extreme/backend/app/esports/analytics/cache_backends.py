"""
Phase 21C §13, §16 — pluggable cache backends for the analytics store.

The analytics store keeps its aggregate cache behind one narrow seam —
``cache_get`` / ``cache_set`` / ``cache_get_stale`` / ``invalidate`` — so the
storage can change without a single caller changing. This module supplies the
two implementations:

  * :class:`MemoryCacheBackend` — the default. Process-local, lock-guarded, and
    deliberately *not* Redis (identical semantics to the store it replaces).
  * :class:`RedisCacheBackend` — a real Redis cache used when ``REDIS_URL`` is
    configured (and reachable), so several workers/processes share one cache
    instead of each keeping its own copy.

Both share one contract:

  * a *logical* expiry (when a reader must treat the value as stale) and a
    longer *physical* retention, so ``get_stale`` can still serve a last good
    value during a provider outage — the same promise the in-memory store makes.
  * **no value is invented**: a miss, a decode error or an unreachable backend
    returns ``None``; it never guesses.

Redis is best-effort by design. Every operation is wrapped so that a Redis
outage degrades to "no cache" rather than raising into the request or the live
event pipeline; the failure count is surfaced in ``stats()`` for observability.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Protocol

logger = logging.getLogger("neural_market.esports.analytics.cache")

#: How long a logically-expired entry is retained so ``get_stale`` still has a
#: last good value to serve (matches the in-memory store's stale-fallback grace).
STALE_GRACE_SECONDS = 3600.0

#: Upper bound on the keys counted for the cheap ``entries()`` health read.
_ENTRY_SCAN_CAP = 10_000


class CacheBackend(Protocol):
    """The cache contract every backend must satisfy."""

    name: str

    def get(self, key: str) -> Optional[Any]: ...
    def get_stale(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, ttl_seconds: float) -> None: ...
    def invalidate(self, prefix: Optional[str]) -> int: ...
    def prune(self, max_age_seconds: float) -> int: ...
    def entries(self) -> Optional[int]: ...
    def stats(self) -> Dict[str, Any]: ...


class MemoryCacheBackend:
    """Process-local TTL cache. The default; no external dependency."""

    name = "in-process-async-ttl"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, value = entry
            if expires_at < now:
                # Expired-but-present: kept for get_stale, counted as a miss.
                self._misses += 1
                return None
            self._hits += 1
            return value

    def get_stale(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            return entry[1] if entry else None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._cache[key] = (time.monotonic() + ttl_seconds, value)

    def invalidate(self, prefix: Optional[str] = None) -> int:
        with self._lock:
            if prefix is None:
                removed = len(self._cache)
                self._cache.clear()
                return removed
            keys = [k for k in self._cache if k.startswith(prefix)]
            for key in keys:
                del self._cache[key]
            return len(keys)

    def prune(self, max_age_seconds: float = 7200.0) -> int:
        cutoff = time.monotonic() - max_age_seconds
        removed = 0
        with self._lock:
            for key in [k for k, (expires, _value) in self._cache.items() if expires < cutoff]:
                del self._cache[key]
                removed += 1
        return removed

    def entries(self) -> Optional[int]:
        with self._lock:
            return len(self._cache)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "backend": self.name,
                "cache_entries": len(self._cache),
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "cache_failures": 0,
            }


class RedisCacheBackend:
    """
    Shared Redis cache behind the same seam.

    Values are JSON-encoded with their logical expiry embedded, so the physical
    Redis TTL can outlive the logical one (that gap is what makes ``get_stale``
    possible). Keys are namespaced so several deployments can share one Redis db
    without colliding, and the namespace is also the invalidation radix.
    """

    name = "redis"

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "nm:esports:cache:",
        stale_grace_seconds: float = STALE_GRACE_SECONDS,
    ) -> None:
        self._client = client
        self._namespace = namespace
        self._stale_grace = max(0.0, float(stale_grace_seconds))
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._failures = 0

    # ------------------------------------------------------------- factories
    @classmethod
    def try_create(
        cls,
        url: str,
        *,
        namespace: str = "nm:esports:cache:",
        socket_timeout: float = 1.0,
        stale_grace_seconds: float = STALE_GRACE_SECONDS,
    ) -> Optional["RedisCacheBackend"]:
        """
        Build a backend only if Redis is installed *and* reachable.

        The connection string is never logged (it may carry a password); a
        failure logs the class of error only and returns ``None`` so the caller
        can fall back to the in-memory backend.
        """
        try:
            import redis  # type: ignore
        except ImportError:
            logger.warning("redis package not installed; using the in-memory analytics cache")
            return None
        try:
            client = redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=max(0.1, float(socket_timeout)),
                socket_connect_timeout=max(0.1, float(socket_timeout)),
                health_check_interval=30,
            )
            client.ping()
        except Exception as exc:  # connection refused, auth failed, bad URL…
            logger.warning("Redis unavailable (%s); using the in-memory analytics cache", type(exc).__name__)
            return None
        logger.info("Esports analytics cache is backed by Redis (namespace=%s)", namespace)
        return cls(client, namespace=namespace, stale_grace_seconds=stale_grace_seconds)

    # ---------------------------------------------------------------- helpers
    def _k(self, key: str) -> str:
        return f"{self._namespace}{key}"

    def _fail(self, exc: Exception) -> None:
        with self._lock:
            self._failures += 1
        # Best-effort cache: log the category, never the credential-bearing URL.
        logger.warning("Redis cache operation failed (%s); continuing without cache", type(exc).__name__)

    @staticmethod
    def _decode(raw: Optional[str]) -> Optional[Dict[str, Any]]:
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    # ------------------------------------------------------------------- api
    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(self._k(key))
        except Exception as exc:
            self._fail(exc)
            return None
        payload = self._decode(raw)
        if payload is None or float(payload.get("e", 0) or 0) < time.time():
            with self._lock:
                self._misses += 1
            return None
        with self._lock:
            self._hits += 1
        return payload.get("v")

    def get_stale(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(self._k(key))
        except Exception as exc:
            self._fail(exc)
            return None
        payload = self._decode(raw)
        return payload.get("v") if payload else None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        # ``default=str`` keeps an exotic value from breaking the whole cache;
        # the caller's payloads are JSON-ready by construction.
        payload = json.dumps({"e": time.time() + ttl_seconds, "v": value}, default=str)
        physical_ttl = max(1, int(ttl_seconds + self._stale_grace))
        try:
            self._client.set(self._k(key), payload, ex=physical_ttl)
        except Exception as exc:
            self._fail(exc)

    def invalidate(self, prefix: Optional[str] = None) -> int:
        # A single SCAN pass; never KEYS (which blocks the server).
        pattern = f"{self._k(prefix if prefix is not None else '')}*"
        removed = 0
        try:
            for key in self._client.scan_iter(match=pattern, count=500):
                removed += int(self._client.delete(key) or 0)
        except Exception as exc:
            self._fail(exc)
            return 0
        return removed

    def prune(self, max_age_seconds: float = 7200.0) -> int:
        # Redis TTLs already reap physically-expired keys, so there is nothing
        # extra to sweep. Reported honestly as 0 rather than a fabricated count.
        return 0

    def entries(self) -> Optional[int]:
        count = 0
        try:
            for _ in self._client.scan_iter(match=f"{self._namespace}*", count=1000):
                count += 1
                if count >= _ENTRY_SCAN_CAP:
                    break
        except Exception as exc:
            self._fail(exc)
            return None
        return count

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            hits, misses, failures = self._hits, self._misses, self._failures
        return {
            "backend": self.name,
            "cache_entries": self.entries(),
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_failures": failures,
        }


def build_cache_backend() -> CacheBackend:
    """
    Select the cache backend from settings.

    * ``ESPORTS_CACHE_BACKEND=memory`` → always in-process.
    * ``redis``  → require Redis; fall back to memory (with a warning) if unreachable.
    * ``auto`` (default) → Redis when ``REDIS_URL`` is set and reachable, else memory.

    The fallback means a misconfigured or down Redis can never break the app —
    it only loses cross-process sharing, which is exactly the trade-off the
    single-process design already documents.
    """
    from app.config import settings

    preference = str(getattr(settings, "esports_cache_backend", "auto") or "auto").lower()
    url = getattr(settings, "redis_url", None)
    if preference == "memory" or not url:
        return MemoryCacheBackend()
    backend = RedisCacheBackend.try_create(
        url,
        namespace=str(getattr(settings, "esports_cache_namespace", "nm:esports:cache:")),
        socket_timeout=float(getattr(settings, "redis_socket_timeout_seconds", 1.0)),
    )
    return backend or MemoryCacheBackend()
