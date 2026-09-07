"""
MarketDataManager (Phase 2) — the only thing the rest of the backend talks to.

Routes and agents call manager.history() / manager.quote() / manager.profile().
They never import yfinance or Finnhub directly. That means:
  - adding a 3rd provider later is a one-line change in main.py, not a rewrite
  - every response can carry an honest status (LIVE/RECENT/CACHED/STALE/UNAVAILABLE)
  - a failing provider degrades gracefully instead of crashing the request
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from .base import DataStatus, MarketDataProvider, ProviderError, Quote
from .cache import TTLCache

logger = logging.getLogger("neural_market.providers")


class MarketDataManager:
    def __init__(
        self,
        providers: list[MarketDataProvider],
        history_cache_ttl: int = 300,
        quote_cache_ttl: int = 20,
        profile_cache_ttl: int = 3600,
    ):
        # keep only providers that are actually usable (e.g. Finnhub with no key is dropped here)
        self.providers = [p for p in providers if p.is_configured()]
        if not self.providers:
            raise RuntimeError("No configured market data providers — check your .env")
        self._history_cache = TTLCache(history_cache_ttl)
        self._quote_cache = TTLCache(quote_cache_ttl)
        self._profile_cache = TTLCache(profile_cache_ttl)

    async def history(self, ticker: str, start: date, end: date, interval: str = "1d"):
        key = f"history:{ticker.upper()}:{start}:{end}:{interval}"
        cached = await self._history_cache.get(key)
        if cached is not None:
            frame, source = cached
            return frame, source, DataStatus.CACHED

        last_error: Exception | None = None
        for provider in self.providers:
            try:
                frame = await provider.get_history(ticker, start, end, interval)
                await self._history_cache.set(key, (frame, provider.name))
                return frame, provider.name, DataStatus.LIVE
            except ProviderError as exc:
                logger.warning("history provider failed, trying next: %s", exc)
                last_error = exc
                continue

        # every live provider failed — fall back to a stale cached copy if we have one
        stale = await self._history_cache.get_stale(key)
        if stale is not None:
            frame, source = stale
            return frame, source, DataStatus.STALE

        raise ProviderError("manager", f"all providers failed for history({ticker}): {last_error}")

    async def quote(self, ticker: str) -> Quote:
        key = f"quote:{ticker.upper()}"
        cached = await self._quote_cache.get(key)
        if cached is not None:
            cached.status = DataStatus.CACHED
            return cached

        last_error: Exception | None = None
        for provider in self.providers:
            try:
                q = await provider.get_quote(ticker)
                await self._quote_cache.set(key, q)
                return q
            except ProviderError as exc:
                logger.warning("quote provider failed, trying next: %s", exc)
                last_error = exc
                continue

        stale = await self._quote_cache.get_stale(key)
        if stale is not None:
            stale.status = DataStatus.STALE
            return stale

        return self._unavailable_quote(ticker, last_error)

    @staticmethod
    def _unavailable_quote(ticker: str, error: Exception | None) -> Quote:
        # explicit, not a silent 0.0 default — callers must check status == UNAVAILABLE
        # and the frontend must show "unavailable", never plot a fabricated price of 0.
        q = Quote(ticker=ticker.upper(), price=float("nan"), source="none", status=DataStatus.UNAVAILABLE)
        logger.error("quote unavailable for %s: %s", ticker, error)
        return q

    def cache_stats(self) -> dict:
        return {
            "history_entries": self._history_cache.size(),
            "quote_entries": self._quote_cache.size(),
            "profile_entries": self._profile_cache.size(),
        }

    def provider_status(self) -> list[dict]:
        return [{"name": p.name, "configured": p.is_configured()} for p in self.providers]

    async def profile(self, ticker: str) -> dict:
        key = f"profile:{ticker.upper()}"
        cached = await self._profile_cache.get(key)
        if cached is not None:
            return {**cached, "status": DataStatus.CACHED.value}

        last_error: Exception | None = None
        for provider in self.providers:
            get_profile = getattr(provider, "get_profile", None)
            if get_profile is None:
                continue
            try:
                data = await get_profile(ticker)
                await self._profile_cache.set(key, data)
                return {**data, "status": DataStatus.LIVE.value}
            except ProviderError as exc:
                logger.warning("profile provider failed, trying next: %s", exc)
                last_error = exc
                continue

        raise ProviderError("manager", f"no provider could return a profile for {ticker}: {last_error}")
