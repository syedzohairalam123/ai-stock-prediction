"""
Phase 21C §13/§16 — cache backend tests.

Locks the contract the analytics store depends on, for both backends, without a
live Redis: the in-memory backend directly and the Redis backend against a small
fake client that implements exactly the commands it uses. The point is that the
two are interchangeable behind ``cache_get``/``cache_set`` — same expiry, same
stale fallback, same prefix invalidation — and that a broken Redis degrades to a
cache miss instead of raising.
"""

from __future__ import annotations

import fnmatch

from app.esports.analytics.cache_backends import (
    MemoryCacheBackend,
    RedisCacheBackend,
)
from app.esports.analytics.store import AnalyticsStore


class FakeRedis:
    """The subset of the Redis client the backend actually calls."""

    def __init__(self):
        self.data: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}
        self.fail = False

    def _maybe_fail(self):
        if self.fail:
            raise ConnectionError("redis down")

    def get(self, key):
        self._maybe_fail()
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self._maybe_fail()
        self.data[key] = value
        self.expiries[key] = ex

    def delete(self, key):
        self._maybe_fail()
        existed = key in self.data
        self.data.pop(key, None)
        self.expiries.pop(key, None)
        return 1 if existed else 0

    def scan_iter(self, match=None, count=None):
        self._maybe_fail()
        for key in list(self.data):
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    def ping(self):
        self._maybe_fail()
        return True


# ---------------------------------------------------------------------------
# memory backend
# ---------------------------------------------------------------------------
def test_memory_backend_expiry_and_stale_fallback():
    backend = MemoryCacheBackend()
    backend.set("k", {"v": 1}, ttl_seconds=-1.0)
    assert backend.get("k") is None  # logically expired
    assert backend.get_stale("k") == {"v": 1}  # still served as last-good


def test_memory_backend_prefix_invalidation_and_stats():
    backend = MemoryCacheBackend()
    backend.set("trending:games", 1, 60)
    backend.set("team:cs2:ta", 2, 60)
    assert backend.get("trending:games") == 1
    assert backend.invalidate("trending:") == 1
    assert backend.get("team:cs2:ta") == 2
    stats = backend.stats()
    assert stats["backend"] == "in-process-async-ttl"
    assert stats["cache_hits"] == 2
    assert stats["cache_failures"] == 0


# ---------------------------------------------------------------------------
# redis backend (against the fake client)
# ---------------------------------------------------------------------------
def test_redis_backend_logical_expiry_and_stale():
    backend = RedisCacheBackend(FakeRedis(), namespace="test:")
    backend.set("k", {"v": 2}, ttl_seconds=60)
    assert backend.get("k") == {"v": 2}
    backend.set("gone", {"v": 3}, ttl_seconds=-1.0)
    assert backend.get("gone") is None
    assert backend.get_stale("gone") == {"v": 3}


def test_redis_backend_uses_a_longer_physical_ttl_than_logical():
    client = FakeRedis()
    backend = RedisCacheBackend(client, namespace="test:", stale_grace_seconds=3600)
    backend.set("k", {"v": 1}, ttl_seconds=30)
    assert client.expiries["test:k"] == 30 + 3600


def test_redis_backend_prefix_invalidation():
    backend = RedisCacheBackend(FakeRedis(), namespace="test:")
    backend.set("trending:games", 1, 60)
    backend.set("team:cs2:ta", 2, 60)
    assert backend.invalidate("trending:") == 1
    assert backend.get("team:cs2:ta") == 2


def test_redis_backend_fails_soft_when_redis_is_down():
    client = FakeRedis()
    backend = RedisCacheBackend(client, namespace="test:")
    client.fail = True
    # No exception: a miss, a failed write, and a counted failure.
    assert backend.get("k") is None
    backend.set("k", {"v": 1}, 60)
    assert backend.get_stale("k") is None
    assert backend.invalidate("x") == 0
    assert backend.stats()["cache_failures"] >= 4


def test_redis_backend_try_create_returns_none_when_unreachable(monkeypatch):
    # No redis server here: the factory must yield None so callers fall back.
    assert RedisCacheBackend.try_create("redis://127.0.0.1:1/0", socket_timeout=0.2) is None


# ---------------------------------------------------------------------------
# store seam
# ---------------------------------------------------------------------------
def test_store_accepts_a_custom_backend_and_reports_its_name():
    store = AnalyticsStore(cache_backend=RedisCacheBackend(FakeRedis(), namespace="test:"))
    store.cache_set("k", {"v": 9}, 60)
    assert store.cache_get("k") == {"v": 9}
    assert store.stats()["backend"] == "redis"


def test_store_defaults_to_the_in_memory_backend():
    assert AnalyticsStore().stats()["backend"] == "in-process-async-ttl"
