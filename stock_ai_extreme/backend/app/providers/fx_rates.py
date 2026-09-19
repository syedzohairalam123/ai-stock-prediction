"""
Phase 7 — real FX / precious-metal rate sources.

Two genuine, keyless sources sit behind this module:

  1. **Yahoo Finance (via yfinance)** — the primary source. It publishes live FX
     bid/ask for PKR crosses (`USDPKR=X`, `GBPPKR=X`, `EURPKR=X`, …) and the
     COMEX front-month metal futures (`GC=F`, `SI=F`, `PL=F`) used for the PKR
     bullion derivations. Free, no key, already a project dependency.

  2. **ExchangeRate-API open access** (`open.er-api.com`, no key) — 166
     currencies including PKR/AED/SAR, published once a day. Used only as a
     fallback when Yahoo cannot answer for a currency, and always reported as
     DELAYED because that is what the source actually is.

Nothing here invents a number. When a source cannot answer, the caller gets an
explicit failure and the UI reports UNAVAILABLE — the same ground rule the stock
side of the app already follows. Every value carries the source name and the
source's own publication time so freshness can be judged honestly.
"""
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests
import yfinance as yf

from ..config import settings
from ..logging_config import get_logger
from ..retry_utils import retry_on_exception
from .cache import TTLCache

logger = get_logger("neural_market.fx")

SOURCE_YAHOO = "yfinance"
SOURCE_ERAPI = "exchangerate-api"

#: Granularity each source actually publishes at. This is what stops a daily
#: publication from ever being labelled LIVE.
GRANULARITY_REALTIME = "realtime"
GRANULARITY_DAILY = "daily"

#: Currency -> Yahoo symbol. All eight are quoted against PKR, which is what the
#: spec means by "all local pricing must be clearly labeled as PKR-based data".
PKR_CROSS_SYMBOLS: dict[str, str] = {
    "USD": "USDPKR=X",
    "GBP": "GBPPKR=X",
    "EUR": "EURPKR=X",
    "AED": "AEDPKR=X",
    "SAR": "SARPKR=X",
    "AUD": "AUDPKR=X",
    "CAD": "CADPKR=X",
    "JPY": "JPYPKR=X",
}

#: Metal source series -> the futures contract Yahoo actually publishes (spot
#: symbols like XAUUSD=X return nothing on Yahoo, verified). Reported as
#: "COMEX front-month futures" so nobody mistakes it for a spot or retail quote.
METAL_SERIES: dict[str, str] = {
    "XAU": "GC=F",
    "XAG": "SI=F",
    "XPT": "PL=F",
}

_quote_cache = TTLCache(default_ttl_seconds=settings.fx_rates_cache_ttl_seconds)
_currency_cache = TTLCache(default_ttl_seconds=settings.fx_rates_cache_ttl_seconds)


@dataclass
class RawQuote:
    """One normalized Yahoo quote, exactly as the source published it."""

    symbol: str
    price: Optional[float] = None
    previous_close: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp_epoch: Optional[int] = None
    currency: Optional[str] = None
    name: Optional[str] = None
    source: str = SOURCE_YAHOO
    granularity: str = GRANULARITY_REALTIME
    status: str = "UNAVAILABLE"
    error: Optional[str] = None
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "previous_close": self.previous_close,
            "bid": self.bid,
            "ask": self.ask,
            "timestamp_epoch": self.timestamp_epoch,
            "currency": self.currency,
            "name": self.name,
            "source": self.source,
            "granularity": self.granularity,
            "status": self.status,
            "error": self.error,
        }


def _as_float(value: Any) -> Optional[float]:
    """Coerce to a usable float or None. Guards the NaN/inf cases that would
    otherwise reach the UI as the literal strings 'NaN'/'Infinity'."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _fetch_symbol_sync(symbol: str) -> RawQuote:
    """Blocking Yahoo lookup — always called through a worker thread."""
    quote = RawQuote(symbol=symbol)
    try:
        info = yf.Ticker(symbol).info or {}
        quote.price = _as_float(info.get("regularMarketPrice"))
        quote.previous_close = _as_float(info.get("regularMarketPreviousClose"))
        quote.bid = _as_float(info.get("bid"))
        quote.ask = _as_float(info.get("ask"))
        quote.currency = info.get("currency")
        quote.name = info.get("shortName") or info.get("longName")
        epoch = info.get("regularMarketTime")
        quote.timestamp_epoch = int(epoch) if isinstance(epoch, (int, float)) and epoch else None

        if quote.price is None and quote.bid is None and quote.ask is None:
            quote.status = "UNAVAILABLE"
            quote.error = "source returned no price for this symbol"
        else:
            quote.status = "LIVE"
        return quote
    except Exception as exc:  # network / delisted / rate-limited — never fatal
        quote.status = "UNAVAILABLE"
        quote.error = str(exc)[:200]
        return quote


@retry_on_exception(exception_types=(requests.RequestException,), max_attempts=2, stop_after_delay=20)
def _fetch_currency_rates_sync() -> dict[str, Any]:
    """Blocking call to the keyless ExchangeRate-API open endpoint."""
    response = requests.get(settings.exchangerate_api_url, timeout=settings.exchangerate_api_timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if payload.get("result") != "success" or not isinstance(payload.get("rates"), dict):
        raise ValueError("exchangerate-api returned an unexpected payload")
    return payload


async def yahoo_quotes(symbols: list[str], force_refresh: bool = False) -> dict[str, RawQuote]:
    """Fetch several Yahoo quotes concurrently, with a short TTL cache.

    A symbol that fails comes back as an UNAVAILABLE RawQuote rather than
    raising, so one bad pair can never take the whole grid down. `force_refresh`
    backs the UI's refresh action: it skips the cache read and overwrites on
    write, instead of the app hammering the source on every render.
    """
    out: dict[str, RawQuote] = {}
    missing: list[str] = []
    for symbol in symbols:
        cached = None if force_refresh else await _quote_cache.get(symbol)
        if cached is not None:
            out[symbol] = cached
        else:
            missing.append(symbol)

    if missing:
        results = await asyncio.gather(*(asyncio.to_thread(_fetch_symbol_sync, s) for s in missing))
        for quote in results:
            out[quote.symbol] = quote
            if quote.status != "UNAVAILABLE":
                await _quote_cache.set(quote.symbol, quote)
    return out


async def usd_currency_rates(force_refresh: bool = False) -> dict[str, Any]:
    """Keyless daily USD rates: {code: units per USD} plus the source's own
    publication time. Raises on failure — callers decide how to degrade."""
    if not force_refresh:
        cached = await _currency_cache.get("usd_rates")
        if cached is not None:
            return cached

    payload = await asyncio.to_thread(_fetch_currency_rates_sync)
    rates = {str(k).upper(): _as_float(v) for k, v in payload["rates"].items()}
    result = {
        "base": str(payload.get("base_code", "USD")).upper(),
        "rates": {k: v for k, v in rates.items() if v is not None},
        "updated_epoch": _as_float(payload.get("time_last_update_unix")),
        "updated_text": payload.get("time_last_update_utc"),
        "next_update_epoch": _as_float(payload.get("time_next_update_unix")),
        "source": SOURCE_ERAPI,
        "granularity": GRANULARITY_DAILY,
    }
    await _currency_cache.set("usd_rates", result)
    return result


def cross_rate(usd_rates: dict[str, Any], base: str, quote: str) -> Optional[float]:
    """base/quote from USD-pivoted rates: (PKR per USD) / (base per USD).

    e.g. cross_rate(rates, "AED", "PKR") -> PKR per AED. Returns None when the
    source does not publish either leg (the ECB-based APIs, for instance, carry
    no PKR at all) so the caller can report UNAVAILABLE honestly.
    """
    rates = usd_rates.get("rates") or {}
    base_per_usd = rates.get(base)
    quote_per_usd = rates.get(quote)
    if not base_per_usd or not quote_per_usd:
        return None
    return quote_per_usd / base_per_usd


async def purge_caches() -> int:
    """Drop long-expired entries; wired into the existing background job loop."""
    return await _quote_cache.purge_expired() + await _currency_cache.purge_expired()


def cache_sizes() -> dict[str, int]:
    return {"fx_quotes": _quote_cache.size(), "currency_rates": _currency_cache.size()}


def utc_now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())
