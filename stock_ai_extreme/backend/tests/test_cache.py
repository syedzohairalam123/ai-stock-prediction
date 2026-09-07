import asyncio
import time

import pytest

from app.providers.cache import TTLCache


@pytest.mark.asyncio
async def test_set_then_get_returns_value():
    cache = TTLCache(default_ttl_seconds=60)
    await cache.set("k", {"price": 123})
    assert await cache.get("k") == {"price": 123}


@pytest.mark.asyncio
async def test_missing_key_returns_none():
    cache = TTLCache(default_ttl_seconds=60)
    assert await cache.get("missing") is None


@pytest.mark.asyncio
async def test_expired_entry_returns_none_but_stale_still_works():
    cache = TTLCache(default_ttl_seconds=0.05)
    await cache.set("k", "value")
    await asyncio.sleep(0.1)
    assert await cache.get("k") is None          # expired -> not returned as fresh
    assert await cache.get_stale("k") == "value"  # but still available as a last resort


@pytest.mark.asyncio
async def test_per_call_ttl_overrides_default():
    cache = TTLCache(default_ttl_seconds=60)
    await cache.set("short", "v", ttl_seconds=0.05)
    await asyncio.sleep(0.1)
    assert await cache.get("short") is None


@pytest.mark.asyncio
async def test_size_reflects_live_entries():
    cache = TTLCache(default_ttl_seconds=60)
    await cache.set("a", 1)
    await cache.set("b", 2)
    assert cache.size() == 2
