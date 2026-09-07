"""
Finnhub-backed provider (Phase 2) — optional, quote-only.

Finnhub's free tier is a good *live quote* fallback/supplement to yfinance
(and is what a real WebSocket/live-tick upgrade would build on next), but
its free-tier historical-candle access has shifted over time, so this
provider intentionally only implements get_quote(), not get_history().
The manager simply skips straight to the next provider for history calls.

Nothing here runs unless FINNHUB_API_KEY is set — with no key, this
provider reports itself as not configured and the app runs fine without it
(matches the "don't require an API key just to run the demo" rule).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import requests

from .base import DataStatus, HistoryResult, MarketDataProvider, ProviderError, Quote

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"


class FinnhubProvider(MarketDataProvider):
    name = "finnhub"

    def __init__(self, api_key: str | None, timeout_seconds: float = 5.0):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _fetch_quote(self, ticker: str) -> dict:
        resp = requests.get(
            FINNHUB_QUOTE_URL,
            params={"symbol": ticker.upper(), "token": self.api_key},
            timeout=self.timeout_seconds,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_quote(self, ticker: str) -> Quote:
        if not self.is_configured():
            raise ProviderError(self.name, "FINNHUB_API_KEY not set — skipping this provider")
        try:
            data = await asyncio.to_thread(self._fetch_quote, ticker)
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"request failed: {exc}") from exc

        price = data.get("c")
        if not price:
            raise ProviderError(self.name, "empty/zero quote — symbol may be unsupported on the free tier")

        return Quote(
            ticker=ticker.upper(),
            price=float(price),
            source=self.name,
            status=DataStatus.LIVE,
            timestamp=datetime.now(timezone.utc),
            previous_close=data.get("pc"),
            change_percent=data.get("dp"),
        )

    async def get_history(self, ticker: str, start: date, end: date, interval: str = "1d"):
        # Deliberately unsupported here — see module docstring. The manager
        # will move on to the next provider (yfinance) for history requests.
        raise ProviderError(self.name, "history is not implemented for the Finnhub provider in this build")
