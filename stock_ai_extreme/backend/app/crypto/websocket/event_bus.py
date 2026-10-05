"""
Phase 22D — cross-worker event bus for crypto WebSocket fan-out.

In a single process, forwarding a normalized provider event to subscribers is
just an in-memory loop (``CryptoStreamManager._publish``). Across several
uvicorn workers, a client connected to worker A must still receive an event
routed on worker B, so the fan-out goes through Redis pub/sub:

    provider stream (any worker)
        └─ publish("nm:crypto:events", {"channel": ..., "message": ...})
               └─ every worker's listener
                      └─ manager._publish(channel, message) → that worker's clients

Two implementations behind one seam:

* :class:`LocalEventBus` — no Redis. ``publish`` fans out in-process directly.
  This is the default and preserves the exact single-process behaviour (spec
  §9/§50: one shared upstream connection, coalesced fan-out, no per-user
  provider connection).
* :class:`RedisEventBus` — publishes to Redis and re-broadcasts whatever any
  worker published (including its own message, which Redis echoes back to the
  publishing subscriber), so a message is delivered exactly once per worker.

Delivery is best-effort and never on the correctness path: if a publish fails,
the bus falls back to a local broadcast so a Redis blip degrades to
single-process delivery rather than dropping the event. Crypto already treats
duplicate deliveries as harmless — the coalescer keeps only the latest frame per
(client, channel) — so an echoed message can never corrupt a client's view.

The bus is only built when ``REDIS_URL`` is configured and ``CRYPTO_REDIS_PUBSUB``
is enabled, so a default install behaves exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("neural_market.crypto.websocket.event_bus")

Broadcast = Callable[[str, Dict[str, Any]], Awaitable[None]]

DEFAULT_REDIS_CHANNEL = "nm:crypto:events"


class LocalEventBus:
    """Single-process fan-out. The default; no external dependency."""

    enabled = False

    def __init__(self, broadcast: Broadcast) -> None:
        self._broadcast = broadcast

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        await self._broadcast(channel, message)

    def stats(self) -> Dict[str, Any]:
        return {"backend": "local", "enabled": False}


class RedisEventBus(LocalEventBus):
    """Cross-worker fan-out over Redis pub/sub (async client)."""

    enabled = True

    def __init__(
        self,
        broadcast: Broadcast,
        client: Any,
        *,
        redis_channel: str = DEFAULT_REDIS_CHANNEL,
    ) -> None:
        super().__init__(broadcast)
        self._client = client
        self._redis_channel = redis_channel
        self._pubsub: Optional[Any] = None
        self._task: Optional[asyncio.Task] = None
        self._started = False
        self._published = 0
        self._received = 0
        self._failures = 0
        # Set once a Redis error is seen: every later publish degrades to a local
        # broadcast without logging again on each event.
        self._local_only = False

    @classmethod
    def try_create(
        cls,
        broadcast: Broadcast,
        url: str,
        *,
        redis_channel: str = DEFAULT_REDIS_CHANNEL,
        socket_timeout: float = 1.0,
    ) -> Optional["RedisEventBus"]:
        """Build only if ``redis.asyncio`` is installed and the client constructs."""
        try:
            import redis.asyncio as aioredis  # type: ignore
        except ImportError:
            logger.warning("redis.asyncio not installed; crypto fan-out stays local")
            return None
        try:
            client = aioredis.Redis.from_url(
                url,
                decode_responses=True,
                socket_timeout=max(0.1, float(socket_timeout)),
                socket_connect_timeout=max(0.1, float(socket_timeout)),
                health_check_interval=30,
            )
        except Exception as exc:  # malformed URL / client construction error
            logger.warning("crypto Redis event bus unavailable (%s); staying local", type(exc).__name__)
            return None
        logger.info("Crypto event bus is backed by Redis (channel=%s)", redis_channel)
        return cls(broadcast, client, redis_channel=redis_channel)

    async def start(self) -> None:
        """Verify connectivity and begin listening; degrade to local on failure."""
        if self._started:
            return
        self._started = True
        try:
            await self._client.ping()
            self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)
            await self._pubsub.subscribe(self._redis_channel)
        except Exception as exc:
            logger.warning("crypto Redis event bus unavailable (%s); fan-out stays local", type(exc).__name__)
            self._pubsub = None
            self._local_only = True
            return
        self._task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        pubsub = self._pubsub
        if pubsub is None:
            return
        try:
            async for raw in pubsub.listen():
                if not raw or raw.get("type") != "message":
                    continue
                try:
                    envelope = json.loads(raw.get("data") or "{}")
                    channel = envelope["channel"]
                    message = envelope["message"]
                except (ValueError, KeyError, TypeError):
                    self._failures += 1
                    continue
                self._received += 1
                await self._broadcast(channel, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("crypto Redis event bus listener stopped (%s)", type(exc).__name__)

    async def publish(self, channel: str, message: Dict[str, Any]) -> None:
        if self._local_only:
            await self._broadcast(channel, message)
            return
        try:
            payload = json.dumps({"channel": channel, "message": message}, default=str)
            await self._client.publish(self._redis_channel, payload)
            self._published += 1
        except Exception as exc:
            self._failures += 1
            self._local_only = True
            logger.warning("crypto Redis publish failed (%s); delivering locally from now on", type(exc).__name__)
            await self._broadcast(channel, message)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()
            except Exception:
                pass
            self._pubsub = None
        try:
            await self._client.aclose()
        except Exception:
            pass

    def stats(self) -> Dict[str, Any]:
        return {
            "backend": "redis" if not self._local_only else "redis-degraded",
            "enabled": True,
            "channel": self._redis_channel,
            "published": self._published,
            "received": self._received,
            "failures": self._failures,
        }


def build_event_bus(broadcast: Broadcast) -> LocalEventBus:
    """
    Choose the fan-out backend from settings.

    Redis is used only when ``CRYPTO_REDIS_PUBSUB`` is enabled *and* a
    ``REDIS_URL`` is configured and the client constructs; otherwise the
    single-process bus is returned, so the default deployment is unchanged.
    """
    from app.config import settings

    try:
        from app.crypto.config import crypto_settings
    except Exception:  # pragma: no cover - settings always importable in the app
        return LocalEventBus(broadcast)

    if not bool(getattr(crypto_settings, "redis_pubsub", True)):
        return LocalEventBus(broadcast)
    url = getattr(settings, "redis_url", None)
    if not url:
        return LocalEventBus(broadcast)
    bus = RedisEventBus.try_create(
        broadcast,
        url,
        redis_channel=str(getattr(crypto_settings, "redis_channel", DEFAULT_REDIS_CHANNEL)),
        socket_timeout=float(getattr(settings, "redis_socket_timeout_seconds", 1.0)),
    )
    return bus or LocalEventBus(broadcast)
