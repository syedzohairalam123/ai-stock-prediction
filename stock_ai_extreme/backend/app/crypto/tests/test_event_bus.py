"""
Phase 22D — tests for the cross-worker crypto event bus.

The real Redis path is exercised with a fake async client so these tests need no
Redis server and no ``redis`` package (``try_create`` is the only place that
imports it, and it is covered separately). What matters here:

  * the default (no REDIS_URL) is the local in-process bus — unchanged behaviour;
  * a Redis publish sends the documented envelope and counts it;
  * a Redis failure degrades to a local broadcast instead of dropping the event;
  * an unreachable Redis degrades at ``start()`` rather than raising;
  * received envelopes are re-broadcast per worker.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from app.crypto.websocket.event_bus import (
    DEFAULT_REDIS_CHANNEL,
    LocalEventBus,
    RedisEventBus,
    build_event_bus,
)


class FakePubSub:
    def __init__(self, messages: List[Dict[str, Any]]) -> None:
        self._messages = messages
        self.subscribed: List[str] = []
        self.closed = False
        self._release = asyncio.Event()

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def listen(self):
        for message in self._messages:
            yield message
        # Keep the generator open so the listener task stays alive until cancelled.
        await self._release.wait()

    async def aclose(self) -> None:
        self.closed = True
        self._release.set()


class FakeRedis:
    def __init__(self, *, fail_publish: bool = False, fail_ping: bool = False, messages=None) -> None:
        self.published: List[tuple] = []
        self.fail_publish = fail_publish
        self.fail_ping = fail_ping
        self._pubsub = FakePubSub(messages or [])
        self.closed = False

    async def ping(self) -> bool:
        if self.fail_ping:
            raise ConnectionError("redis down")
        return True

    def pubsub(self, ignore_subscribe_messages: bool = True) -> FakePubSub:
        return self._pubsub

    async def publish(self, channel: str, payload: str) -> int:
        if self.fail_publish:
            raise ConnectionError("publish failed")
        self.published.append((channel, payload))
        return 1

    async def aclose(self) -> None:
        self.closed = True


def _collector():
    calls: List[tuple] = []

    async def broadcast(channel: str, message: Dict[str, Any]) -> None:
        calls.append((channel, message))

    return calls, broadcast


def test_local_bus_is_default_without_redis_url() -> None:
    _, broadcast = _collector()
    bus = build_event_bus(broadcast)
    assert isinstance(bus, LocalEventBus)
    assert bus.enabled is False
    assert bus.stats()["backend"] == "local"


def test_local_bus_publish_delegates_in_process() -> None:
    calls, broadcast = _collector()
    bus = LocalEventBus(broadcast)
    asyncio.run(bus.publish("crypto:BTC", {"type": "tick", "price": 1}))
    assert calls == [("crypto:BTC", {"type": "tick", "price": 1})]


def test_redis_publish_sends_envelope_and_counts() -> None:
    calls, broadcast = _collector()
    client = FakeRedis()
    bus = RedisEventBus(broadcast, client, redis_channel="nm:crypto:test")
    asyncio.run(bus.publish("crypto:BTC:5m", {"type": "candle", "close": 42}))
    assert len(client.published) == 1
    channel, payload = client.published[0]
    assert channel == "nm:crypto:test"
    envelope = json.loads(payload)
    assert envelope["channel"] == "crypto:BTC:5m"
    assert envelope["message"]["close"] == 42
    # With Redis in use the message is delivered by the listener, not directly.
    assert calls == []
    assert bus.stats()["published"] == 1


def test_redis_publish_failure_degrades_to_local() -> None:
    calls, broadcast = _collector()
    client = FakeRedis(fail_publish=True)
    bus = RedisEventBus(broadcast, client)
    asyncio.run(bus.publish("crypto:ETH", {"type": "tick"}))
    assert calls == [("crypto:ETH", {"type": "tick"})]
    assert bus.stats()["backend"] == "redis-degraded"
    assert bus.stats()["failures"] == 1


def test_start_unreachable_redis_degrades_without_raising() -> None:
    calls, broadcast = _collector()
    client = FakeRedis(fail_ping=True)
    bus = RedisEventBus(broadcast, client)
    asyncio.run(bus.start())
    assert bus.stats()["backend"] == "redis-degraded"
    # A later publish still reaches local subscribers.
    asyncio.run(bus.publish("crypto:SOL", {"type": "tick"}))
    assert calls == [("crypto:SOL", {"type": "tick"})]


def test_listener_rebroadcasts_received_envelopes() -> None:
    calls, broadcast = _collector()
    envelope = {"channel": "crypto:BTC", "message": {"type": "tick", "price": 7}}
    client = FakeRedis(messages=[{"type": "message", "data": json.dumps(envelope)}])
    bus = RedisEventBus(broadcast, client)
    bus._pubsub = client._pubsub  # normally set by start()

    async def scenario() -> None:
        task = asyncio.create_task(bus._listen())
        for _ in range(50):
            if calls:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert calls == [("crypto:BTC", {"type": "tick", "price": 7})]
    assert bus.stats()["received"] == 1


def test_start_is_idempotent_and_stop_closes_client() -> None:
    _, broadcast = _collector()
    client = FakeRedis()
    bus = RedisEventBus(broadcast, client)

    async def scenario() -> None:
        await bus.start()
        await bus.start()  # second call must not double-subscribe
        assert client._pubsub.subscribed == [DEFAULT_REDIS_CHANNEL]
        await bus.stop()

    asyncio.run(scenario())
    assert client.closed is True
