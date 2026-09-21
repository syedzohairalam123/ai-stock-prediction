"""
Real-time delivery for Phase 17 (spec §15).

Three transports, one payload shape, so a client can pick whichever its
environment supports and still render the same thing:

* **WebSocket** — ``/api/breaking-news/ws``. Preferred: full duplex, and the
  client can send ``{"type": "ping"}`` to keep an idle connection alive.
* **Server-Sent Events** — ``/api/breaking-news/stream``. Works through
  proxies that break WebSockets and reconnects automatically in the browser.
* **Polling fallback** — ``/api/breaking-news/digest``. Returns the same snapshot
  plus a ``generated_at``/``etag`` pair, so a client without either streaming
  transport can poll and compare the etag instead of re-rendering blindly.

All three are driven by ONE shared broadcaster task that computes the snapshot on
an interval and fans it out. That is deliberate: per-connection polling would run
the same corpus queries once per open tab. Each client has a bounded queue, and a
client that cannot keep up is dropped rather than allowed to grow memory without
limit.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from ..logging_config import get_logger
from .config import breaking_news_settings
from .timeutil import utcnow

logger = get_logger("neural_market.breaking_news.stream")

#: Per-client queue depth. Two frames of slack is plenty for a client that is
#: keeping up; anything behind that is dropped and asked to re-poll.
_QUEUE_SIZE = 4

SnapshotFn = Callable[[], Awaitable[dict]]


@dataclass
class StreamClient:
    id: str
    transport: str  # websocket | sse
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_SIZE))
    connected_at: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)
    dropped: int = 0

    def offer(self, payload: dict) -> bool:
        """Enqueue without blocking; drop the oldest frame when full."""
        try:
            self.queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
            self.dropped += 1
            return False


class BreakingNewsStreamManager:
    """Fan-out broadcaster shared by the WebSocket, SSE and digest endpoints."""

    def __init__(self, settings: Any = None):
        self.settings = settings or breaking_news_settings
        self._clients: dict[str, StreamClient] = {}
        self._task: Optional[asyncio.Task] = None
        self._snapshot_fn: Optional[SnapshotFn] = None
        self._last_signature: Optional[str] = None
        self._last_snapshot: dict = {}
        self._broadcasts = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def bind(self, snapshot_fn: SnapshotFn) -> None:
        """Register the snapshot producer the broadcaster will call."""
        self._snapshot_fn = snapshot_fn

    async def start(self) -> None:
        if not (self.settings.enable_websocket or self.settings.enable_sse):
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._broadcast_loop(), name="breaking-news-broadcast")
        logger.info("breaking-news broadcaster started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _broadcast_loop(self) -> None:
        interval = max(int(self.settings.stream_broadcast_interval_seconds), 5)
        while True:
            try:
                await self.ensure_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop must survive any producer failure
                logger.warning("breaking-news broadcaster error: %s", exc)
            await asyncio.sleep(interval)

    async def ensure_snapshot(self, *, force: bool = False) -> dict:
        """Compute the digest and fan it out when it changed (or ``force``)."""
        if self._snapshot_fn is None:
            return dict(self._last_snapshot)

        snapshot = await self._snapshot_fn()
        signature = _signature(snapshot)
        changed = signature != self._last_signature
        self._last_snapshot = snapshot
        self._last_signature = signature

        if not changed and not force:
            await self._broadcast({"type": "heartbeat", "generated_at": snapshot.get("generated_at")})
            return snapshot

        await self._broadcast({
            "type": "breaking_news_update",
            "etag": signature,
            "data": snapshot,
        })
        self._broadcasts += 1
        return snapshot

    async def push_events(self, events: list[dict]) -> None:
        """Push newly persisted events immediately, ahead of the next tick."""
        if not events:
            return
        await self.ensure_snapshot(force=True)
        await self._broadcast({"type": "events_available", "count": len(events)})

    async def _broadcast(self, payload: dict) -> None:
        if not self._clients:
            return
        for client in list(self._clients.values()):
            client.offer(payload)

    # ------------------------------------------------------------------
    # clients
    # ------------------------------------------------------------------

    def register(self, client_id: str, transport: str) -> StreamClient:
        client = StreamClient(id=client_id, transport=transport)
        self._clients[client_id] = client
        logger.info("breaking-news %s client connected (%d total)", transport, len(self._clients))
        return client

    def unregister(self, client_id: str) -> None:
        if self._clients.pop(client_id, None) is not None:
            logger.info("breaking-news client disconnected (%d remaining)", len(self._clients))

    def touch(self, client_id: str) -> None:
        client = self._clients.get(client_id)
        if client is not None:
            client.last_seen = utcnow()

    async def cleanup_stale(self) -> int:
        """Drop clients that have not been seen for the stale timeout."""
        from .timeutil import ensure_aware  # local import keeps the module cohesive

        now = ensure_aware(utcnow())
        timeout = int(self.settings.ws_stale_connection_timeout_seconds)
        stale = [
            client_id for client_id, client in self._clients.items()
            if (now - ensure_aware(client.last_seen)).total_seconds() > timeout
        ]
        for client_id in stale:
            self.unregister(client_id)
        return len(stale)

    def stats(self) -> dict:
        return {
            "transport": "websocket+sse+polling",
            "connected_clients": len(self._clients),
            "websocket_clients": sum(1 for c in self._clients.values() if c.transport == "websocket"),
            "sse_clients": sum(1 for c in self._clients.values() if c.transport == "sse"),
            "broadcasts": self._broadcasts,
            "dropped_frames": sum(c.dropped for c in self._clients.values()),
            "interval_seconds": int(self.settings.stream_broadcast_interval_seconds),
            "heartbeat_interval_seconds": int(self.settings.ws_heartbeat_interval_seconds),
            "last_signature": self._last_signature,
        }


def _signature(snapshot: dict) -> str:
    """Stable content hash of a snapshot — the idempotency key for clients."""
    try:
        material = json.dumps(snapshot, sort_keys=True, default=str)
    except (TypeError, ValueError):
        material = str(snapshot)
    return hashlib.blake2b(material.encode("utf-8"), digest_size=8).hexdigest()


#: Shared instance used by the routes and the engine.
stream_manager = BreakingNewsStreamManager()


__all__ = ["BreakingNewsStreamManager", "StreamClient", "stream_manager"]
