"""
Phase 20 — paper-simulation lifecycle events (spec §54).

When the backend creates / evaluates / cancels a simulation it publishes a
lightweight event here. Two things consume them:

* `GET /api/paper/events/recent` — the last N events (polling fallback).
* `GET /api/paper/stream`        — Server-Sent Events, so an open ticket's
  history panel updates the moment a new simulation is recorded without
  refetching the whole table.

Design notes:
* In-process by design: this app is a single FastAPI instance with a SQLite
  store. The publish/subscribe seam is the same shape a Redis pub/sub would
  have, so a multi-instance deployment swaps the two functions in this file
  for Redis calls without touching any caller (the same seam every other
  Phase 16-21 module documents).
* Events are small and additive: they carry ids and statuses, never user
  inputs that could be mistaken for authoritative state.
* `user_id` IS included so a subscriber can filter to its own events — but
  the recent-events endpoint filters server-side, so one user can never read
  another user's event rows (spec §40 isolation).
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import AsyncIterator, Optional

from ..logging_config import get_logger

logger = get_logger("neural_market.paper.events")

#: Ring buffer size for the polling fallback. Small by intent: events are a
#: nudge to refetch, not a data store — the database remains authoritative.
RECENT_LIMIT = 50

_subscribers: dict[int, asyncio.Queue] = {}
_recent: deque[dict] = deque(maxlen=RECENT_LIMIT)
_seq = 0


def publish_paper_event(event: dict) -> dict:
    """Record an event and fan it out to every connected SSE subscriber.

    Never raises: a broken subscriber queue is dropped, and an event that
    fails to publish must not fail the simulation that produced it.
    """
    global _seq
    _seq += 1
    stamped = {
        "seq": _seq,
        "at": time.time(),
        **event,
    }
    _recent.appendleft(stamped)
    dead: list[int] = []
    for key, queue in _subscribers.items():
        try:
            queue.put_nowait(stamped)
        except Exception:
            dead.append(key)
    for key in dead:
        _subscribers.pop(key, None)
    return stamped


def recent_events(*, user_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Newest-first slice of the ring buffer, optionally scoped to one user.

    Scope is enforced here (server-side, spec §40): a caller is only ever
    shown its own simulation events — `anonymous` events stay hidden from a
    named user and vice versa.
    """
    wanted_user = (user_id or "").strip() or "anonymous"
    limit = max(1, min(int(limit), RECENT_LIMIT))
    out: list[dict] = []
    for event in _recent:
        if str(event.get("userId") or "anonymous") != wanted_user:
            continue
        out.append(event)
        if len(out) >= limit:
            break
    return out


async def subscribe(user_id: Optional[str] = None) -> AsyncIterator[str]:
    """Yield SSE-formatted frames for this subscriber until the client goes away.

    A heartbeat every ~15 s keeps proxies from closing the connection and lets
    the client distinguish "quiet market" from "dead socket" (spec §47).
    """
    wanted_user = (user_id or "").strip() or "anonymous"
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    key = id(queue)
    _subscribers[key] = queue
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if str(event.get("userId") or "anonymous") != wanted_user:
                continue  # never deliver another user's events (spec §40)
            yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
    except asyncio.CancelledError:  # client disconnected
        raise
    finally:
        _subscribers.pop(key, None)


def subscriber_count() -> int:
    return len(_subscribers)


def stats() -> dict:
    """Small introspection block for the health endpoint."""
    return {
        "subscribers": len(_subscribers),
        "bufferedEvents": len(_recent),
        "published": _seq,
    }
