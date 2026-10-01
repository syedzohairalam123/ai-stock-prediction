"""
Phase 21C §16/§19 — event bus tests.

The Redis bus is exercised against a small fake async client (with an echo, as
real Redis pub/sub has), so publish → listener → local broadcast and the
degrade-to-local behaviour are asserted without a live server.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.esports.websocket.event_bus import (
    LocalEventBus,
    RedisEventBus,
    build_event_bus,
)


def _collector():
    seen: list[tuple[str, dict]] = []

    async def broadcast(channel, message):
        seen.append((channel, message))

    return seen, broadcast


# ---------------------------------------------------------------------------
# local bus
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_local_bus_fans_out_in_process():
    seen, broadcast = _collector()
    bus = LocalEventBus(broadcast)

    await bus.start()
    await bus.publish("esports:match:m1", {"type": "event", "id": "e1"})
    await bus.stop()

    assert seen == [("esports:match:m1", {"type": "event", "id": "e1"})]
    assert bus.stats()["backend"] == "local"
    assert bus.enabled is False


def test_build_event_bus_is_local_without_a_redis_url(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "redis_url", None)
    _seen, broadcast = _collector()
    bus = build_event_bus(broadcast)
    assert isinstance(bus, LocalEventBus)
    assert bus.enabled is False


# ---------------------------------------------------------------------------
# redis bus (fake async client)
# ---------------------------------------------------------------------------
class _FakePubSub:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel):
        return None

    async def listen(self):
        while not self.closed:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def aclose(self):
        self.closed = True
        await self.queue.put(None)


class _FakeAsyncRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.ps: _FakePubSub | None = None
        self.closed = False
        self.fail_publish = False
        self.fail_ping = False

    async def ping(self):
        if self.fail_ping:
            raise ConnectionError("no redis")
        return True

    def pubsub(self, ignore_subscribe_messages=False):
        self.ps = _FakePubSub()
        return self.ps

    async def publish(self, channel, data):
        if self.fail_publish:
            raise ConnectionError("publish failed")
        self.published.append((channel, data))
        if self.ps is not None:  # Redis echoes to subscribers
            await self.ps.queue.put({"type": "message", "channel": channel, "data": data})
        return 1

    async def aclose(self):
        self.closed = True


async def _settle():
    # Let the listener task drain the echoed message.
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_redis_bus_publishes_and_rebroadcasts_locally():
    seen, broadcast = _collector()
    client = _FakeAsyncRedis()
    bus = RedisEventBus(broadcast, client, redis_channel="nm:esports:events")

    await bus.start()
    await bus.publish("esports:match:m1", {"type": "event", "id": "e1"})
    await _settle()

    assert client.published and client.published[0][0] == "nm:esports:events"
    envelope = json.loads(client.published[0][1])
    assert envelope == {"channel": "esports:match:m1", "message": {"type": "event", "id": "e1"}}
    # The listener re-broadcast the echo to this worker's clients.
    assert seen == [("esports:match:m1", {"type": "event", "id": "e1"})]

    stats = bus.stats()
    assert stats["backend"] == "redis"
    assert stats["published"] == 1
    assert stats["received"] == 1

    await bus.stop()
    assert client.closed is True


@pytest.mark.asyncio
async def test_redis_bus_degrades_to_local_when_publish_fails():
    seen, broadcast = _collector()
    client = _FakeAsyncRedis()
    bus = RedisEventBus(broadcast, client)
    await bus.start()

    client.fail_publish = True
    await bus.publish("esports:match:m1", {"id": "e1"})
    assert seen == [("esports:match:m1", {"id": "e1"})]  # still delivered locally
    assert bus.stats()["backend"] == "redis-degraded"

    # Subsequent publishes skip Redis entirely (no repeated log spam).
    client.fail_publish = False
    await bus.publish("esports:match:m2", {"id": "e2"})
    assert len(client.published) == 0
    assert seen[-1] == ("esports:match:m2", {"id": "e2"})

    await bus.stop()


@pytest.mark.asyncio
async def test_redis_bus_falls_back_when_subscribe_fails():
    seen, broadcast = _collector()
    client = _FakeAsyncRedis()
    client.fail_ping = True
    bus = RedisEventBus(broadcast, client)

    await bus.start()  # subscribe fails, no listener
    await bus.publish("esports:match:m1", {"id": "e1"})

    assert seen == [("esports:match:m1", {"id": "e1"})]
    assert bus.stats()["backend"] == "redis-degraded"
    await bus.stop()
