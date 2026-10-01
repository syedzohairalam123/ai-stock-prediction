"""
CoinGecko adapter — market metadata + coarse daily history (spec §52, §53).

Public, keyless endpoints:

  ``GET /ping``                              → liveness
  ``GET /coins/markets``                     → market cap, rank, supply, volumes
  ``GET /coins/{id}/ohlc?days=N``            → daily OHLC (no volume published)

CoinGecko is deliberately the *secondary* source. Its OHLC endpoint publishes a
limited set of windows (1/7/14/30/90/180/365 days) and no volume, so it cannot
serve minute-level analytics honestly — the capability layer reports ``1d`` only
and the manager only falls back to it for intervals it can genuinely cover.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.crypto.config import crypto_settings
from app.crypto.normalization import normalize_candles, parse_coingecko_ohlc
from app.crypto.providers.base import (
    CandleSeries,
    CryptoMarketProvider,
    ProviderError,
    ProviderHealth,
    ProviderQuote,
)
from app.crypto.schemas import DataStatus

logger = logging.getLogger("neural_market.crypto.providers.coingecko")

#: Real windows the public OHLC endpoint accepts.
SUPPORTED_OHLC_WINDOWS = (1, 7, 14, 30, 90, 180, 365)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


class CoinGeckoProvider(CryptoMarketProvider):
    name = "coingecko"
    native_intervals = ("1d",)

    def __init__(self, *, base_url: Optional[str] = None, timeout_seconds: Optional[float] = None) -> None:
        self.base_url = (base_url or crypto_settings.coingecko_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or crypto_settings.request_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._request_count = 0
        self._error_count = 0

    def symbol_for(self, asset) -> Optional[str]:
        """CoinGecko convention: asset ids like ``bitcoin``."""
        return getattr(asset, "coingecko_id", None)

    # ------------------------------------------------------------------ client
    async def _get_client(self) -> httpx.AsyncClient:
        # See the Binance adapter: a client is never reused across event loops.
        current_loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not current_loop:
            if self._client is not None and not self._client.is_closed:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
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
            if response.status_code == 429:
                raise ProviderError(self.name, "rate limited by upstream (HTTP 429)")
            if response.status_code >= 400:
                raise ProviderError(self.name, f"HTTP {response.status_code}: {response.text[:200]}")
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
        payload = await self._request("/coins/markets", {"vs_currency": "usd", "per_page": 100, "page": 1})
        if not isinstance(payload, list):
            raise ProviderError(self.name, "markets payload was not a list")
        return [
            {
                "provider": self.name,
                "provider_symbol": entry.get("id"),
                "base": entry.get("symbol", "").upper() if entry.get("symbol") else None,
                "quote": "usd",
                "status": "TRADING" if entry.get("id") else "UNKNOWN",
            }
            for entry in payload
            if isinstance(entry, dict) and entry.get("id")
        ]

    # -------------------------------------------------------------------- quote
    async def get_quote(self, symbol: str, provider_symbol: str) -> ProviderQuote:
        payload = await self._request(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "ids": provider_symbol,
                "price_change_percentage": "24h",
                "sparkline": "false",
            },
        )
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise ProviderError(self.name, f"no market row for {provider_symbol!r}")
        row = payload[0]
        price = _f(row.get("current_price"))
        if price is None:
            raise ProviderError(self.name, "market row had no usable current_price")
        updated = row.get("last_updated")
        source_timestamp = None
        if isinstance(updated, str):
            try:
                source_timestamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except ValueError:
                source_timestamp = None
        return ProviderQuote(
            symbol=symbol,
            price=price,
            source=self.name,
            fetched_at=_now(),
            source_timestamp=source_timestamp,
            high_24h=_f(row.get("high_24h")),
            low_24h=_f(row.get("low_24h")),
            volume_24h=_f(row.get("total_volume")),
            change_percent_24h=_f(row.get("price_change_percentage_24h")),
            # Freshness is judged by the quality layer from the real timestamps
            # above (CoinGecko's `last_updated` can lag); the adapter does not
            # claim a status it has not verified.
            status=DataStatus.UNAVAILABLE,
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
        if interval != "1d":
            raise ProviderError(
                self.name, f"CoinGecko OHLC supports only '1d' candles, not {interval!r}"
            )
        # Pick the smallest real window that can satisfy the request.
        days = min(SUPPORTED_OHLC_WINDOWS[-1], max(1, int(limit)))
        chosen = next((w for w in SUPPORTED_OHLC_WINDOWS if w >= days), SUPPORTED_OHLC_WINDOWS[-1])
        payload = await self._request(
            f"/coins/{provider_symbol}/ohlc",
            {"vs_currency": "usd", "days": chosen},
        )
        if not isinstance(payload, list):
            raise ProviderError(self.name, "ohlc payload was not a list")

        raw = [row for row in (parse_coingecko_ohlc(r) for r in payload) if row is not None]
        candles, stats = normalize_candles(raw, expected_interval_seconds=86400)

        # CoinGecko does not publish volume on this endpoint; the zeros are a
        # *documented absence*, so the note travels with the series.
        notes = [f"CoinGecko OHLC window={chosen}d publishes no volume"]
        return CandleSeries(
            symbol=symbol,
            timeframe=interval,
            interval=interval,
            candles=candles[-limit:] if limit else candles,
            stats=stats,
            source=self.name,
            fetched_at=_now(),
            source_timestamp=candles[-1].timestamp if candles else None,
            aggregated=False,
            notes=notes,
        )

    # ------------------------------------------------------------- market stats
    async def get_market_stats(self, symbol: str, coingecko_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not coingecko_id:
            return None
        payload = await self._request(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "ids": coingecko_id,
                "price_change_percentage": "24h,7d,30d",
            },
        )
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        row = payload[0]
        return {
            "symbol": symbol,
            "source": self.name,
            "market_cap": _f(row.get("market_cap")),
            "market_cap_rank": row.get("market_cap_rank"),
            "fully_diluted_valuation": _f(row.get("fully_diluted_valuation")),
            "circulating_supply": _f(row.get("circulating_supply")),
            "total_supply": _f(row.get("total_supply")),
            "max_supply": _f(row.get("max_supply")),
            "ath": _f(row.get("ath")),
            "ath_change_percentage": _f(row.get("ath_change_percentage")),
            "atl": _f(row.get("atl")),
            "price_change_percentage_7d": _f(row.get("price_change_percentage_7d_in_currency")),
            "price_change_percentage_30d": _f(row.get("price_change_percentage_30d_in_currency")),
            "last_updated": row.get("last_updated"),
        }

    # ------------------------------------------------------- classification data
    async def get_categories(self) -> List[Dict[str, Any]]:
        """Real CoinGecko category taxonomy with its published market caps."""
        payload = await self._request("/coins/categories", {"order": "market_cap_desc"})
        if not isinstance(payload, list):
            raise ProviderError(self.name, "categories payload was not a list")
        out: List[Dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            out.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "market_cap": _f(entry.get("market_cap")),
                    "market_cap_change_24h": _f(entry.get("market_cap_change_24h")),
                    "volume_24h": _f(entry.get("volume_24h")),
                    "top_3_coins": entry.get("top_3_coins") or [],
                    "updated_at": entry.get("updated_at"),
                    "source": self.name,
                }
            )
        return out

    async def get_trending(self) -> List[Dict[str, Any]]:
        """CoinGecko's real search-interest ranking (observed, not predicted)."""
        payload = await self._request("/search/trending")
        coins = payload.get("coins") if isinstance(payload, dict) else None
        if not isinstance(coins, list):
            raise ProviderError(self.name, "trending payload had no coins")
        out: List[Dict[str, Any]] = []
        for entry in coins:
            item = entry.get("item") if isinstance(entry, dict) else None
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "id": item.get("id"),
                    "symbol": (item.get("symbol") or "").upper() or None,
                    "name": item.get("name"),
                    "market_cap_rank": item.get("market_cap_rank"),
                    "price_btc": _f(item.get("price_btc")),
                    "score": item.get("score"),
                    "source": self.name,
                }
            )
        return out

    async def get_public_treasury(self, coingecko_id: str) -> Optional[Dict[str, Any]]:
        """
        Publicly disclosed corporate/treasury holdings (spec §43).

        This is reported, published disclosure — it is attributed to the source
        and dated. Nothing here infers institutional intent or flow.
        """
        if not coingecko_id:
            return None
        payload = await self._request(f"/companies/public_treasury/{coingecko_id}")
        if not isinstance(payload, dict):
            return None
        companies = payload.get("companies") or []
        rows: List[Dict[str, Any]] = []
        for entry in companies:
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "name": entry.get("name"),
                    "symbol": entry.get("symbol"),
                    "country": entry.get("country"),
                    "total_holdings": _f(entry.get("total_holdings")),
                    "total_entry_value_usd": _f(entry.get("total_entry_value_usd")),
                    "total_current_value_usd": _f(entry.get("total_current_value_usd")),
                    "percentage_of_total_supply": _f(entry.get("percentage_of_total_supply")),
                }
            )
        return {
            "source": self.name,
            "asset": coingecko_id,
            "total_holdings": _f(payload.get("total_holdings")),
            "total_value_usd": _f(payload.get("total_value_usd")),
            "market_cap_dominance": _f(payload.get("market_cap_dominance")),
            "companies": rows,
            "company_count": len(rows),
            "coverage": "Publicly disclosed corporate treasury holdings as published by CoinGecko.",
            "limitations": (
                "Covers public-company disclosures only. It is not fund flow data and does not "
                "include private holders, ETF creations/redemptions or exchange balances."
            ),
        }

    # ------------------------------------------------------------------- health
    async def health(self) -> ProviderHealth:
        started = asyncio.get_event_loop().time()
        try:
            await self._request("/ping")
        except ProviderError as exc:
            return ProviderHealth(provider=self.name, available=False, checked_at=_now(), detail=exc.message)
        latency = (asyncio.get_event_loop().time() - started) * 1000.0
        return ProviderHealth(
            provider=self.name, available=True, checked_at=_now(), latency_ms=round(latency, 3)
        )

    def stats(self) -> Dict[str, Any]:
        return {"provider": self.name, "requests": self._request_count, "errors": self._error_count}


def coingecko_days_for(span_days: int) -> int:
    """Smallest real CoinGecko window that covers ``span_days`` (documented set)."""
    return next((w for w in SUPPORTED_OHLC_WINDOWS if w >= span_days), SUPPORTED_OHLC_WINDOWS[-1])


def clamp_window_days(days: int) -> int:
    """Kept for symmetry with the manager's range control."""
    return max(1, min(days, SUPPORTED_OHLC_WINDOWS[-1]))
