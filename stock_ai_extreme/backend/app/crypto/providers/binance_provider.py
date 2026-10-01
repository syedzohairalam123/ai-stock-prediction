"""
Binance spot adapter — the primary real-time crypto provider (spec §8, §52).

Public, keyless endpoints only:

  REST   ``GET /api/v3/klines``       → OHLCV history at a native interval
  REST   ``GET /api/v3/ticker/24hr``  → rolling 24h quote (price, bid/ask, volume)
  REST   ``GET /api/v3/exchangeInfo`` → the symbols genuinely trading
  REST   ``GET /api/v3/ping``         → liveness
  WS     ``wss://stream.binance.com:9443/ws`` with SUBSCRIBE frames

Everything returned here is a value Binance actually published, with the
provider's own timestamps preserved. The normalizer validates structure; this
adapter never repairs or invents a record.

Rate-limit observability: Binance reports the used request weight in the
``X-MBX-USED-WEIGHT-1M`` response header, which is recorded so a dashboard can
show how close the shared connection is to the public limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import httpx

from app.crypto.config import crypto_settings
from app.crypto.normalization import normalize_candles, parse_binance_kline
from app.crypto.providers.base import (
    CandleSeries,
    CryptoMarketProvider,
    ProviderError,
    ProviderHealth,
    ProviderQuote,
)
from app.crypto.schemas import DataStatus

logger = logging.getLogger("neural_market.crypto.providers.binance")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _millis_to_dt(value: Any) -> Optional[datetime]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000, tz=timezone.utc)


def _f(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


class BinanceSpotProvider(CryptoMarketProvider):
    """Binance spot market data over public REST + WebSocket."""

    name = "binance"
    native_intervals = (
        "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M",
    )

    def __init__(
        self,
        *,
        rest_url: Optional[str] = None,
        ws_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.rest_url = (rest_url or crypto_settings.binance_rest_url).rstrip("/")
        self.ws_url = (ws_url or crypto_settings.binance_ws_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or crypto_settings.request_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._used_weight: Optional[int] = None
        self._request_count = 0
        self._error_count = 0

    def symbol_for(self, asset) -> Optional[str]:
        """Binance spot convention: ``BTCUSDT``."""
        return getattr(asset, "binance", None)

    # ------------------------------------------------------------------ client
    async def _get_client(self) -> httpx.AsyncClient:
        # An httpx.AsyncClient is bound to the event loop that created it. In
        # long-lived processes this never matters, but a client built on a loop
        # that has since closed must be rebuilt — never reused across loops.
        current_loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not current_loop:
            if self._client is not None and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = httpx.AsyncClient(
                base_url=self.rest_url,
                timeout=self.timeout_seconds,
                headers={"User-Agent": "neural-market/crypto-intel"},
            )
            self._client_loop = current_loop
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        client = await self._get_client()
        self._request_count += 1
        try:
            response = await client.get(path, params=params)
            weight = response.headers.get("X-MBX-USED-WEIGHT-1M")
            if weight is not None:
                try:
                    self._used_weight = int(weight)
                except ValueError:
                    pass
            if response.status_code == 429:
                raise ProviderError(self.name, "rate limited by upstream (HTTP 429)")
            if response.status_code >= 400:
                detail = response.text[:200]
                raise ProviderError(self.name, f"HTTP {response.status_code}: {detail}")
            return response.json()
        except ProviderError:
            self._error_count += 1
            raise
        except httpx.HTTPError as exc:
            self._error_count += 1
            raise ProviderError(self.name, f"request failed ({type(exc).__name__})") from exc
        except ValueError as exc:
            self._error_count += 1
            raise ProviderError(self.name, "response was not valid JSON") from exc

    # ------------------------------------------------------------------- assets
    async def get_assets(self) -> List[Dict[str, Any]]:
        payload = await self._request("/api/v3/exchangeInfo", {"permissions": "SPOT"})
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not isinstance(symbols, list):
            raise ProviderError(self.name, "exchangeInfo payload missing 'symbols'")
        assets: List[Dict[str, Any]] = []
        for entry in symbols:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "TRADING":
                continue
            symbol = entry.get("symbol")
            quote = entry.get("quoteAsset")
            base = entry.get("baseAsset")
            if not symbol or not quote or not base:
                continue
            assets.append(
                {
                    "provider": self.name,
                    "provider_symbol": symbol,
                    "base": base,
                    "quote": quote,
                    "status": entry.get("status"),
                }
            )
        return assets

    # -------------------------------------------------------------------- quote
    async def get_quote(self, symbol: str, provider_symbol: str) -> ProviderQuote:
        payload = await self._request("/api/v3/ticker/24hr", {"symbol": provider_symbol})
        if not isinstance(payload, dict):
            raise ProviderError(self.name, "ticker payload was not an object")

        price = _f(payload.get("lastPrice"))
        close_time = _millis_to_dt(payload.get("closeTime"))
        if price is None:
            raise ProviderError(self.name, "ticker payload had no usable lastPrice")

        return ProviderQuote(
            symbol=symbol,
            price=price,
            source=self.name,
            fetched_at=_now(),
            source_timestamp=close_time,
            bid=_f(payload.get("bidPrice")),
            ask=_f(payload.get("askPrice")),
            volume_24h=_f(payload.get("volume")),
            quote_volume_24h=_f(payload.get("quoteVolume")),
            high_24h=_f(payload.get("highPrice")),
            low_24h=_f(payload.get("lowPrice")),
            open_24h=_f(payload.get("openPrice")),
            change_24h=_f(payload.get("priceChange")),
            change_percent_24h=_f(payload.get("priceChangePercent")),
            status=DataStatus.LIVE,
        )

    # ----------------------------------------------------------------- candles
    async def get_historical_candles(
        self,
        *,
        symbol: str,
        provider_symbol: str,
        interval: str,
        limit: int,
    ) -> CandleSeries:
        if interval not in self.native_intervals:
            raise ProviderError(self.name, f"interval {interval!r} is not a native Binance interval")
        payload = await self._request(
            "/api/v3/klines",
            {"symbol": provider_symbol, "interval": interval, "limit": int(limit)},
        )
        if not isinstance(payload, list):
            raise ProviderError(self.name, "klines payload was not a list")

        raw = [row for row in (parse_binance_kline(r) for r in payload) if row is not None]
        seconds = _interval_seconds(interval)
        candles, stats = normalize_candles(raw, expected_interval_seconds=seconds)

        notes: List[str] = []
        # Binance includes the currently-forming candle last; flag it so callers
        # can exclude it from training without guessing.
        if candles:
            notes.append("last candle may be in-progress (provider behaviour)")

        source_timestamp = None
        if payload and isinstance(payload[-1], list) and len(payload[-1]) > 6:
            source_timestamp = _millis_to_dt(payload[-1][6])

        return CandleSeries(
            symbol=symbol,
            timeframe=interval,
            interval=interval,
            candles=candles,
            stats=stats,
            source=self.name,
            fetched_at=_now(),
            source_timestamp=source_timestamp,
            aggregated=False,
            notes=notes,
        )

    # ------------------------------------------------------------- market stats
    async def get_market_stats(self, symbol: str, coingecko_id: Optional[str]) -> Optional[Dict[str, Any]]:
        # Binance spot does not publish market cap / circulating supply.
        return None

    # ------------------------------------------------------------------ streams
    def supports_streaming(self) -> bool:
        return True

    def stream_names(self, streams: Sequence[Dict[str, str]]) -> List[str]:
        """Binance stream identifiers for a subscription request."""
        names: List[str] = []
        for entry in streams:
            provider_symbol = (entry.get("provider_symbol") or "").lower()
            interval = entry.get("interval") or "1m"
            if not provider_symbol:
                continue
            names.append(f"{provider_symbol}@kline_{interval}")
            names.append(f"{provider_symbol}@miniTicker")
        # Stable order + de-duplication so a repeated subscription is idempotent.
        seen = set()
        unique: List[str] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            unique.append(name)
        return unique

    async def subscribe_market_data(
        self,
        streams: Sequence[Dict[str, str]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Yield normalized real-time events from one Binance WebSocket connection.

        The caller owns the connection's lifetime; this is a plain async
        generator so a single shared task can fan the events out to every
        connected client (spec §9, §49) instead of one upstream socket per user.
        """
        names = self.stream_names(streams)
        if not names:
            raise ProviderError(self.name, "no stream names resolved from subscription")

        try:
            import websockets  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency is present in this env
            raise ProviderError(self.name, "websockets package is not installed") from exc

        from websockets.exceptions import ConnectionClosed  # type: ignore

        # Binance allows the subscription to be carried on the query string,
        # which avoids a round-trip race between connect and SUBSCRIBE.
        # Combined streams live at /stream?streams=..., raw streams at /ws/...;
        # the configured base may be either, so normalise to the combined form.
        base = self.ws_url
        if base.endswith("/ws"):
            base = base[: -len("/ws")]
        url = f"{base}/stream?streams={'/'.join(names)}"
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_queue=1024,
        ) as socket:
            async for raw in socket:
                try:
                    envelope = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                data = envelope.get("data") if isinstance(envelope, dict) else None
                if not isinstance(data, dict):
                    continue
                event = self._normalize_stream_event(data)
                if event is not None:
                    yield event
            raise ConnectionClosed(None, None)  # pragma: no cover - unreachable

    @staticmethod
    def _normalize_stream_event(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event_type = data.get("e")
        provider_symbol = data.get("s")
        if not provider_symbol:
            return None
        received_at = _now()

        if event_type == "kline":
            kline = data.get("k")
            if not isinstance(kline, dict):
                return None
            open_time = _millis_to_dt(kline.get("t"))
            return {
                "type": "kline",
                "provider": "binance",
                "provider_symbol": provider_symbol,
                "interval": kline.get("i"),
                "is_final": bool(kline.get("x")),
                "open": _f(kline.get("o")),
                "high": _f(kline.get("h")),
                "low": _f(kline.get("l")),
                "close": _f(kline.get("c")),
                "volume": _f(kline.get("v")),
                "quote_volume": _f(kline.get("q")),
                "trades": _f(kline.get("n")),
                "timestamp": open_time.isoformat() if open_time else None,
                "source_timestamp": received_at.isoformat(),
                "received_at": received_at.isoformat(),
            }

        if event_type in ("miniTicker", "24hrMiniTicker"):
            return {
                "type": "ticker",
                "provider": "binance",
                "provider_symbol": provider_symbol,
                "price": _f(data.get("c")),
                "open": _f(data.get("o")),
                "high": _f(data.get("h")),
                "low": _f(data.get("l")),
                "volume": _f(data.get("v")),
                "quote_volume": _f(data.get("q")),
                "source_timestamp": _millis_to_dt(data.get("E")).isoformat() if _millis_to_dt(data.get("E")) else None,
                "received_at": received_at.isoformat(),
            }

        return None

    # ------------------------------------------------------------------- health
    async def health(self) -> ProviderHealth:
        started = asyncio.get_event_loop().time()
        try:
            await self._request("/api/v3/ping")
        except ProviderError as exc:
            return ProviderHealth(
                provider=self.name, available=False, checked_at=_now(), detail=exc.message
            )
        latency = (asyncio.get_event_loop().time() - started) * 1000.0
        return ProviderHealth(
            provider=self.name,
            available=True,
            checked_at=_now(),
            latency_ms=round(latency, 3),
            detail=f"used_weight_1m={self._used_weight}" if self._used_weight is not None else None,
        )

    def stats(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "requests": self._request_count,
            "errors": self._error_count,
            "used_weight_1m": self._used_weight,
        }


_INTERVAL_SECONDS: Dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000,
}


def _interval_seconds(interval: str) -> Optional[int]:
    return _INTERVAL_SECONDS.get(interval)
