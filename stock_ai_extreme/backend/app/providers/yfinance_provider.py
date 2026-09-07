"""
yfinance-backed provider (Phase 2).

This wraps the same `yfinance` call the original DataAgent made, but now:
  - retries with exponential backoff instead of failing on the first blip
  - classifies how fresh the returned data actually is
  - never returns an empty/partial frame silently — raises ProviderError instead

Reminder: yfinance is an unofficial wrapper around Yahoo's endpoints. It has
no SLA and can change or break without notice. Treat it as "free and good
enough for a primary provider", not as a guaranteed data feed.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from .base import DataStatus, MarketDataProvider, ProviderError, Quote


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def __init__(self, max_retries: int = 3, backoff_base_seconds: float = 1.0):
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds

    async def _with_retries(self, fn, *args, **kwargs):
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:  # yfinance raises a mix of exception types
                last_error = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.backoff_base_seconds * (2 ** attempt))
        raise ProviderError(self.name, f"failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def _classify_freshness(last_row_date: date) -> DataStatus:
        gap = (date.today() - last_row_date).days
        if gap <= 1:
            return DataStatus.LIVE
        if gap <= 4:  # covers a normal weekend
            return DataStatus.RECENT
        return DataStatus.STALE

    def _fetch(self, ticker: str, start: date, end: date, interval: str) -> pd.DataFrame:
        d = yf.download(
            ticker.upper(), start=str(start), end=str(end + timedelta(days=1)),
            interval=interval, auto_adjust=True, progress=False,
        )
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        return d

    async def get_history(self, ticker: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        d = await self._with_retries(self._fetch, ticker, start, end, interval)
        if d is None or d.empty:
            raise ProviderError(self.name, "no data returned — verify ticker, date range, and provider availability")
        return d

    def _fetch_info(self, ticker: str) -> dict:
        return yf.Ticker(ticker.upper()).info or {}

    async def get_profile(self, ticker: str) -> dict:
        """Company profile fields (sector/country/website/summary) — the one
        thing the earlier 'Warren' project did that this dashboard didn't yet."""
        info = await self._with_retries(self._fetch_info, ticker)
        if not info:
            raise ProviderError(self.name, "no profile info returned for this ticker")
        return {
            "ticker": ticker.upper(),
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "summary": info.get("longBusinessSummary"),
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "exchange": info.get("exchange"),
        }

    async def get_quote(self, ticker: str) -> Quote:
        end = date.today()
        d = await self._with_retries(self._fetch, ticker, end - timedelta(days=10), end, "1d")
        if d is None or d.empty:
            raise ProviderError(self.name, "no recent rows available for a quote")
        last_close = float(d["Close"].iloc[-1])
        prev_close = float(d["Close"].iloc[-2]) if len(d) > 1 else None
        change_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close else None
        last_date = pd.Timestamp(d.index[-1]).date()
        return Quote(
            ticker=ticker.upper(),
            price=last_close,
            source=self.name,
            status=self._classify_freshness(last_date),
            timestamp=datetime.now(timezone.utc),
            previous_close=prev_close,
            change_percent=change_pct,
        )
