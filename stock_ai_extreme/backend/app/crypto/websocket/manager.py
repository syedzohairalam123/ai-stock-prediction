"""
WebSocket gateway for the crypto module (spec §9, §49, §50, §89, §90).

The scaling property that matters: **one** upstream provider connection serves
every browser client. The gateway holds a single subscription set (the union of
what connected clients asked for), and when that set changes the one upstream
socket is restarted with the new Binance stream names — never one socket per
user, and never one socket per component.

```text
Binance WebSocket ──▶ one upstream task ──▶ channel router ──▶ coalescer ──▶ clients
```

Backpressure (spec §90) is handled by **coalescing**: high-frequency ticks are
folded per (client, channel) and flushed on a fixed cadence, so one slow client
receives the latest state rather than every frame and cannot degrade the
fan-out. A client that cannot keep up is disconnected rather than buffered
without bound.

Channels are user-specific subscriptions (spec §89):

    crypto:BTC          live tick
    crypto:BTC:5m       kline updates for that timeframe
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from fastapi import WebSocket, WebSocketDisconnect

from app.crypto.config import crypto_settings
from app.crypto.symbols import SymbolError, symbol_service
from app.crypto.timeframes import TIMEFRAMES, get_timeframe

logger = logging.getLogger("neural_market.crypto.websocket.manager")

#: Reconnect backoff for the single upstream connection.
_UPSTREAM_BACKOFF_SECONDS = (1, 2, 5, 10, 30)

#: Maximum coalesced frames kept per client before a forced flush.
_MAX_PENDING_PER_CLIENT = 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def symbol_channel(symbol: str) -> str:
    return f"crypto:{symbol.upper()}"


def timeframe_channel(symbol: str, timeframe: str) -> str:
    return f"crypto:{symbol.upper()}:{timeframe}"


def _timeframes_for_interval(interval: str) -> List[str]:
    """Every timeframe whose *source* interval is ``interval``."""
    return [tf.id for tf in TIMEFRAMES if tf.enabled and tf.source_interval == interval]


class CryptoStreamManager:
    """Single-upstream, multi-client real-time gateway."""

    def __init__(self) -> None:
        self._clients: Dict[str, WebSocket] = {}
        self._subscriptions: Dict[str, Set[Tuple[str, str]]] = {}
        self._channels: Dict[str, Set[str]] = {}
        self._pending: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._upstream_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._active_streams: Tuple[Tuple[str, str], ...] = ()
        self._lock = asyncio.Lock()
        self._manager = None
        self._stats: Dict[str, int] = {
            "connections_total": 0,
            "messages_in": 0,
            "messages_out": 0,
            "coalesced": 0,
            "upstream_events": 0,
            "upstream_restarts": 0,
            "disconnects": 0,
            "send_failures": 0,
            "rejected_connections": 0,
        }

    # ------------------------------------------------------------------ config
    def configure(self, manager) -> None:
        """Bind the provider manager (used for the upstream provider + snapshots)."""
        self._manager = manager

    @property
    def manager(self):
        if self._manager is None:
            from app.crypto.services.service import crypto_service

            self._manager = crypto_service.manager
        return self._manager

    # ------------------------------------------------------------------ guards
    def connection_allowed(self, client_id: str) -> bool:
        """Bounded connections (spec §92): refuse rather than degrade everyone."""
        if len(self._clients) >= crypto_settings.ws_max_connections:
            self._stats["rejected_connections"] += 1
            logger.warning(
                "crypto ws connection rejected: %d/%d connections in use",
                len(self._clients),
                crypto_settings.ws_max_connections,
            )
            return False
        return True

    # ------------------------------------------------------------------ serve
    async def serve(self, websocket: WebSocket, client_id: str) -> None:
        """Own one client socket for its whole lifetime."""
        if client_id in self._clients:
            await self._release(client_id)
        self._clients[client_id] = websocket
        self._subscriptions[client_id] = set()
        self._pending[client_id] = {}
        self._stats["connections_total"] += 1

        await self._ensure_tasks()
        await self._send(
            client_id,
            {
                "type": "connected",
                "clientId": client_id,
                "timestamp": _now_iso(),
                "heartbeatSeconds": crypto_settings.ws_heartbeat_seconds,
                "coalesceMs": crypto_settings.ws_coalesce_ms,
                "maxSymbols": crypto_settings.ws_max_symbols_per_client,
                "message": "Connected to the crypto market-data gateway.",
                "note": "One shared upstream provider connection serves every client.",
            },
        )

        try:
            while True:
                payload = await websocket.receive_json()
                self._stats["messages_in"] += 1
                await self._handle_message(client_id, payload)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # malformed frame must not kill the gateway
            logger.debug("crypto ws client %s error: %s", client_id, exc)
        finally:
            await self._release(client_id)

    async def _handle_message(self, client_id: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            await self._send(client_id, {"type": "error", "message": "message must be a JSON object"})
            return
        message_type = str(payload.get("type") or "").lower()

        if message_type == "ping":
            await self._send(client_id, {"type": "pong", "timestamp": _now_iso()})
            return

        if message_type == "subscribe":
            await self._subscribe(client_id, payload)
            return

        if message_type == "unsubscribe":
            await self._unsubscribe(client_id, payload)
            return

        if message_type == "snapshot":
            await self._snapshot(client_id, payload)
            return

        if message_type == "subscriptions":
            await self._send(
                client_id,
                {
                    "type": "subscriptions",
                    "subscriptions": sorted(self._subscriptions.get(client_id, set())),
                },
            )
            return

        await self._send(
            client_id,
            {"type": "error", "message": f"unsupported message type {message_type!r}"},
        )

    # ------------------------------------------------------------- subscribe
    async def _subscribe(self, client_id: str, payload: Dict[str, Any]) -> None:
        symbol = str(payload.get("symbol") or payload.get("symbols") or "").strip()
        if not symbol:
            await self._send(client_id, {"type": "error", "message": "symbol is required"})
            return
        try:
            timeframes = self._resolve_timeframes(client_id, payload.get("timeframe"))
        except ValueError as exc:
            await self._send(client_id, {"type": "error", "message": str(exc)})
            return

        for raw_symbol in [s for s in symbol.replace(",", " ").split() if s]:
            try:
                asset = symbol_service.resolve(raw_symbol)
            except SymbolError as exc:
                await self._send(client_id, {"type": "error", "message": str(exc)})
                continue
            if not asset.streaming or not asset.binance:
                await self._send(
                    client_id,
                    {
                        "type": "error",
                        "symbol": asset.internal,
                        "message": "No real-time stream is available for this asset.",
                    },
                )
                continue

            subscriptions = self._subscriptions.setdefault(client_id, set())
            for timeframe in timeframes:
                if len(subscriptions) >= crypto_settings.ws_max_symbols_per_client:
                    await self._send(
                        client_id,
                        {
                            "type": "error",
                            "message": (
                                f"Subscription limit reached "
                                f"({crypto_settings.ws_max_symbols_per_client} symbol/timeframe pairs)."
                            ),
                        },
                    )
                    break
                subscriptions.add((asset.internal, timeframe))

            self._subscribe_channel(client_id, symbol_channel(asset.internal))
            await self._send(
                client_id,
                {
                    "type": "subscribed",
                    "symbol": asset.internal,
                    "timeframes": timeframes,
                    "channels": [symbol_channel(asset.internal)]
                    + [timeframe_channel(asset.internal, tf) for tf in timeframes],
                    "timestamp": _now_iso(),
                },
            )

        await self._sync_upstream()
        # A fresh subscription immediately gets the current real state.
        await self._snapshot(client_id, {"symbol": symbol, "timeframe": timeframes[0]})

    def _resolve_timeframes(self, client_id: str, requested: Any) -> List[str]:
        if requested in (None, ""):
            return ["5m"]
        values = requested if isinstance(requested, (list, tuple)) else str(requested).replace(",", " ").split()
        resolved: List[str] = []
        for value in values:
            resolved.append(get_timeframe(str(value)).id)
        return resolved or ["5m"]

    async def _unsubscribe(self, client_id: str, payload: Dict[str, Any]) -> None:
        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            await self._release(client_id)
            return
        try:
            asset = symbol_service.resolve(symbol)
        except SymbolError as exc:
            await self._send(client_id, {"type": "error", "message": str(exc)})
            return
        subscriptions = self._subscriptions.get(client_id, set())
        remaining = {(s, tf) for (s, tf) in subscriptions if s != asset.internal}
        self._subscriptions[client_id] = remaining

        # Drop channels this client no longer needs.
        for channel in list(self._channels):
            if channel.startswith(symbol_channel(asset.internal)):
                self._unsubscribe_channel(client_id, channel)
        await self._send(
            client_id,
            {"type": "unsubscribed", "symbol": asset.internal, "timestamp": _now_iso()},
        )
        await self._sync_upstream()

    def _subscribe_channel(self, client_id: str, channel: str) -> None:
        self._channels.setdefault(channel, set()).add(client_id)

    def _unsubscribe_channel(self, client_id: str, channel: str) -> None:
        subscribers = self._channels.get(channel)
        if subscribers is None:
            return
        subscribers.discard(client_id)
        if not subscribers:
            self._channels.pop(channel, None)

    # ---------------------------------------------------------------- snapshot
    async def _snapshot(self, client_id: str, payload: Dict[str, Any]) -> None:
        """
        Authoritative current state: a real quote plus the newest real candles.

        Sending a snapshot on every (re)connect is what lets a client REPLACE a
        stale local view instead of replaying missed events onto it (spec §110).
        """
        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            await self._send(client_id, {"type": "error", "message": "symbol is required for a snapshot"})
            return
        try:
            asset = symbol_service.resolve(symbol)
            timeframe = get_timeframe(payload.get("timeframe"))
        except (SymbolError, ValueError) as exc:
            await self._send(client_id, {"type": "error", "message": str(exc)})
            return

        try:
            from app.crypto.services.service import crypto_service

            market = crypto_service.market
            quote = await market.quote(asset.internal)
            bundle = await market.load_series(asset.internal, timeframe.id, limit=200)
        except Exception as exc:
            logger.debug("snapshot failed for %s: %s", asset.internal, exc)
            await self._send(
                client_id,
                {
                    "type": "snapshot",
                    "symbol": asset.internal,
                    "status": "UNAVAILABLE",
                    "reason": type(exc).__name__,
                },
            )
            return

        await self._send(
            client_id,
            {
                "type": "snapshot",
                "symbol": asset.internal,
                "timeframe": timeframe.id,
                "quote": quote,
                "candles": [c.to_dict() for c in bundle.candles],
                "gaps": bundle.gaps.to_dict(),
                "quality": bundle.quality.to_dict(),
                "dataStatus": bundle.data_status.value,
                "source": bundle.series.source,
                "timestamp": _now_iso(),
            },
        )

    # ---------------------------------------------------------------- upstream
    def _desired_streams(self) -> Tuple[Tuple[str, str], ...]:
        """
        The union of what clients need, as sorted (provider_symbol, interval) pairs.

        De-duplicated, so N clients watching BTC/5m still produce exactly one
        upstream stream (spec §50).
        """
        specs: Set[Tuple[str, str]] = set()
        for subscriptions in self._subscriptions.values():
            for symbol, timeframe in subscriptions:
                asset = symbol_service.get(symbol)
                if asset is None or not asset.binance:
                    continue
                try:
                    config = get_timeframe(timeframe)
                except ValueError:
                    continue
                specs.add((asset.binance, config.source_interval))
        return tuple(sorted(specs))

    async def _sync_upstream(self) -> None:
        """Start, restart or stop the single upstream connection as needed."""
        async with self._lock:
            desired = self._desired_streams()
            if desired == self._active_streams:
                return
            if self._upstream_task is not None:
                self._upstream_task.cancel()
                try:
                    await self._upstream_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._upstream_task = None
            self._active_streams = desired
            if not desired:
                return
            self._stats["upstream_restarts"] += 1
            self._upstream_task = asyncio.create_task(self._upstream_loop(desired))

    async def _upstream_loop(self, streams: Sequence[Tuple[str, str]]) -> None:
        """
        Consume the single provider stream and route events to channels.

        Reconnects with capped exponential backoff. Every value forwarded is the
        provider's own — the gateway never generates a tick.
        """
        provider = self.manager.streaming_provider()
        if provider is None:
            logger.warning("no configured provider supports streaming; crypto live mode is off")
            return

        attempt = 0
        while True:
            specs = [
                {"provider_symbol": provider_symbol, "interval": interval}
                for provider_symbol, interval in streams
            ]
            try:
                async for event in provider.subscribe_market_data(specs):
                    attempt = 0
                    self._stats["upstream_events"] += 1
                    await self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = _UPSTREAM_BACKOFF_SECONDS[min(attempt, len(_UPSTREAM_BACKOFF_SECONDS) - 1)]
                attempt += 1
                logger.warning(
                    "crypto upstream stream stopped (%s); reconnecting in %ss", type(exc).__name__, delay
                )
                await asyncio.sleep(delay)

    async def _dispatch(self, event: Dict[str, Any]) -> None:
        """Route one normalized provider event onto the matching channels."""
        provider_symbol = str(event.get("provider_symbol") or "")
        asset = symbol_service.resolve(provider_symbol) if provider_symbol else None
        if asset is None:
            return

        if event.get("type") == "ticker":
            await self._publish(
                symbol_channel(asset.internal),
                {
                    "type": "tick",
                    "symbol": asset.internal,
                    "price": event.get("price"),
                    "open": event.get("open"),
                    "high": event.get("high"),
                    "low": event.get("low"),
                    "volume": event.get("volume"),
                    "quoteVolume": event.get("quote_volume"),
                    "source": event.get("provider"),
                    "sourceTimestamp": event.get("source_timestamp"),
                    "receivedAt": event.get("received_at"),
                    "dataStatus": "LIVE",
                    "origin": "SOURCE",
                },
            )
            return

        if event.get("type") == "kline":
            interval = str(event.get("interval") or "")
            for timeframe in _timeframes_for_interval(interval):
                await self._publish(
                    timeframe_channel(asset.internal, timeframe),
                    {
                        "type": "candle",
                        "symbol": asset.internal,
                        "timeframe": timeframe,
                        "interval": interval,
                        "isFinal": bool(event.get("is_final")),
                        "open": event.get("open"),
                        "high": event.get("high"),
                        "low": event.get("low"),
                        "close": event.get("close"),
                        "volume": event.get("volume"),
                        "timestamp": event.get("timestamp"),
                        "source": event.get("provider"),
                        "sourceTimestamp": event.get("source_timestamp"),
                        "receivedAt": event.get("received_at"),
                        "dataStatus": "LIVE",
                        "origin": "SOURCE",
                    },
                )

    # ------------------------------------------------------------------ fan-out
    async def _publish(self, channel: str, message: Dict[str, Any]) -> None:
        """
        Queue a message for every subscriber of ``channel``.

        Coalescing happens here: a newer message for the same (client, channel)
        replaces an older unsent one, so a slow client always receives the latest
        state at the next flush instead of an unbounded backlog (spec §90).
        """
        subscribers = self._channels.get(channel)
        if not subscribers:
            return
        for client_id in list(subscribers):
            self._subscribe_channel(client_id, channel)  # idempotent (client may have just joined)
            buffer = self._pending.setdefault(client_id, {})
            if channel in buffer:
                self._stats["coalesced"] += 1
            buffer[channel] = message

    async def _flush_loop(self) -> None:
        interval = max(0.05, crypto_settings.ws_coalesce_ms / 1000.0)
        try:
            while True:
                await asyncio.sleep(interval)
                for client_id in list(self._clients):
                    buffer = self._pending.get(client_id)
                    if not buffer:
                        continue
                    frames = list(buffer.values())[:_MAX_PENDING_PER_CLIENT]
                    buffer.clear()
                    if len(frames) == 1:
                        await self._send(client_id, frames[0])
                    else:
                        await self._send(
                            client_id, {"type": "batch", "frames": frames, "timestamp": _now_iso()}
                        )
        except asyncio.CancelledError:
            raise

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(5, crypto_settings.ws_heartbeat_seconds))
                for client_id in list(self._clients):
                    await self._send(
                        client_id,
                        {
                            "type": "heartbeat",
                            "timestamp": _now_iso(),
                            "subscriptions": len(self._subscriptions.get(client_id, set())),
                            "upstreamStreams": len(self._active_streams),
                        },
                    )
        except asyncio.CancelledError:
            raise

    async def _ensure_tasks(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _send(self, client_id: str, message: Dict[str, Any]) -> None:
        websocket = self._clients.get(client_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
            self._stats["messages_out"] += 1
        except Exception:
            self._stats["send_failures"] += 1
            await self._release(client_id)

    async def _release(self, client_id: str) -> None:
        """Drop a client and every trace of it (subscriptions, channels, buffers)."""
        had = client_id in self._clients
        self._clients.pop(client_id, None)
        self._pending.pop(client_id, None)
        self._subscriptions.pop(client_id, None)
        for channel in list(self._channels):
            subscribers = self._channels[channel]
            subscribers.discard(client_id)
            if not subscribers:
                self._channels.pop(channel, None)
        if had:
            self._stats["disconnects"] += 1
            try:
                await self._sync_upstream()
            except Exception:
                pass

    # ----------------------------------------------------------------- shutdown
    async def shutdown(self) -> None:
        for task in (self._upstream_task, self._flush_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._upstream_task = None
        self._flush_task = None
        self._heartbeat_task = None
        self._active_streams = ()
        self._clients.clear()
        self._channels.clear()
        self._subscriptions.clear()
        self._pending.clear()

    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "connections": len(self._clients),
            "channels": len(self._channels),
            "subscriptions": sum(len(s) for s in self._subscriptions.values()),
            "upstream_streams": [
                {"providerSymbol": symbol, "interval": interval} for symbol, interval in self._active_streams
            ],
            "coalesceMs": crypto_settings.ws_coalesce_ms,
            "maxConnections": crypto_settings.ws_max_connections,
        }


#: Process-wide singleton gateway.
crypto_ws_manager = CryptoStreamManager()
