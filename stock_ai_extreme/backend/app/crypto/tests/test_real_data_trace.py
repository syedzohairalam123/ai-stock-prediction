"""
Live real-data verification (spec §98, §112).

Traces one configured real asset (BTC) end to end:

    provider REST → normalization → manager → analytics consistency

Network access is required; if the public providers are unreachable the whole
module is skipped rather than failed, so offline CI stays green — but when it
runs, it asserts the values are REAL: the quote must sit inside the latest
kline's range, timestamps must be recent, and the source must be attributed.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from datetime import datetime, timedelta, timezone

from app.crypto.normalization import detect_gaps
from app.crypto.providers.binance_provider import BinanceSpotProvider
from app.crypto.providers.coingecko_provider import CoinGeckoProvider
from app.crypto.providers.manager import CryptoMarketManager

UTC = timezone.utc


def _network_available() -> bool:
    if os.environ.get("CRYPTO_SKIP_LIVE_TESTS"):
        return False
    try:
        response = httpx.get("https://api.binance.com/api/v3/ping", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _network_available(), reason="public providers unreachable")


@pytest.fixture(scope="module")
def manager():
    """A fresh manager per module, closed inside the SAME event loop asyncio tests run in."""
    instance = CryptoMarketManager([BinanceSpotProvider(), CoinGeckoProvider()])
    yield instance
    # pytest-asyncio closes its loop after the last async test; close the HTTP
    # client synchronously without touching any event loop.
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(instance.close())
        loop.close()
    except Exception:
        pass


class TestLiveTrace:
    @pytest.mark.asyncio
    async def test_quote_is_real_and_recent(self, manager):
        quote = await manager.get_quote("BTC")
        assert quote.source == "binance"
        assert quote.price > 10_000.0  # BTC has never traded below this in the public era
        assert quote.bid is None or quote.bid > 0
        assert quote.ask is None or quote.ask >= quote.bid
        # The provider's own timestamp must be recent — a real live feed.
        assert quote.source_timestamp is not None
        age = datetime.now(UTC) - quote.source_timestamp
        assert age < timedelta(hours=1)

    @pytest.mark.asyncio
    async def test_candles_are_real_klines(self, manager):
        series = await manager.get_candles("BTC", "5m", limit=100)
        assert series.source == "binance"
        assert len(series.candles) >= 90
        assert series.stats["malformed"] == 0
        newest = series.candles[-1]
        age = datetime.now(UTC) - newest.timestamp
        assert age < timedelta(minutes=30)
        for candle in series.candles:
            assert candle.high >= max(candle.open, candle.close)
            assert candle.low <= min(candle.open, candle.close)
            assert candle.volume >= 0
        gaps = detect_gaps(series.candles, interval_seconds=300, timeframe="5m")
        assert gaps.completeness > 0.9  # Binance 5m history is effectively continuous

    @pytest.mark.asyncio
    async def test_quote_consistent_with_latest_candle(self, manager):
        """The quote and the newest kline must describe the same real market."""
        quote = await manager.get_quote("BTC")
        series = await manager.get_candles("BTC", "5m", limit=5)
        newest = series.candles[-1]
        # The live price must be within a sane band of the last traded range
        # (the quote can move after the kline closed, so allow generous slack).
        band = max(newest.close * 0.05, newest.high - newest.low + newest.close * 0.01)
        assert abs(quote.price - newest.close) <= band

    @pytest.mark.asyncio
    async def test_yearly_rollup_matches_daily_history(self, manager):
        """The 1Y roll-up must not contradict the daily series it came from."""
        yearly = await manager.get_candles("BTC", "1Y")
        daily = await manager.get_candles("BTC", "1d", limit=400)
        assert yearly.aggregated
        assert yearly.candles
        # The newest yearly close equals the newest daily close (same real market).
        assert yearly.candles[-1].close == pytest.approx(daily.candles[-1].close, rel=0.01)

    @pytest.mark.asyncio
    async def test_market_stats_from_coingecko(self, manager):
        # CoinGecko's public tier is rate-limited; when the whole suite runs the
        # upstream may answer 429, which the manager reports as a genuine
        # UNAVAILABLE rather than a fake stat. Skip (not fail) on that outcome.
        stats = await manager.get_market_stats("BTC")
        if stats is None:
            pytest.skip("CoinGecko market stats unavailable (public-tier rate limit)")
        assert stats["source"] == "coingecko"
        assert stats["market_cap"] > 100_000_000_000.0
        assert stats["market_cap_rank"] == 1
        assert stats["circulating_supply"] > 15_000_000

    @pytest.mark.asyncio
    async def test_analytics_pipeline_on_real_data(self, manager):
        from app.crypto.indicators import log_returns
        from app.crypto.trend import micro_trend_engine
        from app.crypto.volatility import volatility_engine

        series = await manager.get_candles("BTC", "1h", limit=300)
        candles = series.candles
        closes = [c.close for c in candles]
        snapshot = volatility_engine.snapshot(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=closes,
            duration_seconds=3600,
            timeframe="1h",
        )
        assert snapshot.realized_volatility is not None
        assert 0 < snapshot.realized_volatility < 50.0  # annualised BTC vol is far below 5000%
        trend = micro_trend_engine.analyse(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=closes,
            volumes=[c.volume for c in candles],
            timeframe="1h",
            duration_seconds=3600,
            realized_volatility=snapshot.realized_volatility,
        )
        assert trend.direction.value in {"UP", "DOWN", "SIDEWAYS"}
        assert trend.recent_return is not None

    @pytest.mark.asyncio
    async def test_forecast_engine_on_real_history(self, manager):
        from app.crypto.forecasting.engine import forecast_engine

        series = await manager.get_candles("BTC", "1h", limit=1000)
        outcome = forecast_engine.forecast(
            symbol="BTC",
            timeframe="1h",
            candles=series.candles,
            duration_seconds=3600,
            data_source=series.source,
        )
        assert outcome.available, outcome.reason
        forecast = outcome.forecast
        last_close = series.candles[-1].close
        # A calibrated model will not predict a 10x move in 5 bars.
        assert 0.5 * last_close < forecast.prediction < 1.5 * last_close
        assert forecast.lower_bound < forecast.upper_bound
        assert forecast.data_source == "binance"
