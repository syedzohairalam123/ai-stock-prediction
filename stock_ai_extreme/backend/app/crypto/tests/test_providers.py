"""Provider manager + capability tests: failover, symbol mapping, timeframes (spec §3, §51–§53)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.crypto.providers.base import (
    CandleSeries,
    CryptoMarketProvider,
    ProviderError,
    ProviderQuote,
)
from app.crypto.providers.manager import CryptoMarketManager
from app.crypto.schemas import Candle, DataStatus
from app.crypto.symbols import SymbolError, symbol_service
from app.crypto.timeframes import (
    DEFAULT_TIMEFRAME_ID,
    TIMEFRAMES,
    TimeframeError,
    capabilities,
    get_timeframe,
    list_timeframes,
    provider_supports,
)
from app.crypto.tests.synthetic import make_candles


class FakeProvider(CryptoMarketProvider):
    """Scriptable provider for failover tests (fixtures: test-only)."""

    name = "fake-a"
    native_intervals = ("5m", "1h", "1d")

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def get_assets(self):
        return []

    async def get_quote(self, symbol, provider_symbol):
        self.calls += 1
        if self.fail:
            raise ProviderError(self.name, "simulated outage")
        return ProviderQuote(
            symbol=symbol, price=100.0, source=self.name,
            fetched_at=datetime.now(timezone.utc), status=DataStatus.LIVE,
        )

    async def get_historical_candles(self, *, symbol, provider_symbol, interval, limit):
        self.calls += 1
        if self.fail:
            raise ProviderError(self.name, "simulated outage")
        seconds = {"5m": 300, "1h": 3600, "1d": 86400, "1M": 2592000}.get(interval, 3600)
        candles = make_candles(min(limit, 100), step_seconds=seconds)
        return CandleSeries(
            symbol=symbol, timeframe=interval, interval=interval, candles=candles,
            stats={"received": len(candles), "accepted": len(candles)}, source=self.name,
            fetched_at=datetime.now(timezone.utc),
            source_timestamp=candles[-1].timestamp if candles else None,
        )

    async def health(self):
        from app.crypto.providers.base import ProviderHealth

        return ProviderHealth(
            provider=self.name, available=not self.fail, checked_at=datetime.now(timezone.utc)
        )


class TestSymbolMapping:
    def test_accepts_multiple_spellings(self):
        for spelling in ("BTC", "btc", "BTC/USDT", "BTCUSDT", "bitcoin"):
            assert symbol_service.resolve(spelling).internal == "BTC"

    def test_unknown_symbol_raises(self):
        with pytest.raises(SymbolError):
            symbol_service.resolve("NOTAREALCOIN")

    def test_display_and_providers(self):
        btc = symbol_service.resolve("BTC")
        assert btc.binance == "BTCUSDT"
        assert btc.coingecko_id == "bitcoin"
        assert btc.industry == "Layer 1"

    def test_industries_are_documented(self):
        grouped = symbol_service.by_industry()
        assert "Layer 1" in grouped and "Stablecoins" in grouped
        for assets in grouped.values():
            assert assets  # no empty categories


class TestTimeframes:
    def test_registry_complete(self):
        ids = [tf.id for tf in TIMEFRAMES]
        assert ids == ["5m", "15m", "1h", "4h", "1d", "1w", "1M", "1Y"]

    def test_default_and_case_sensitive_month(self):
        assert get_timeframe(None).id == DEFAULT_TIMEFRAME_ID == "5m"
        assert get_timeframe("1M").id == "1M"  # monthly
        with pytest.raises(TimeframeError):
            get_timeframe("7m")

    def test_yearly_is_rollup(self):
        yearly = get_timeframe("1Y")
        assert yearly.aggregation_method.value == "ohlcv_rollup"
        assert yearly.source_interval == "1M"

    def test_capabilities_native_vs_rollup(self):
        report = {entry["id"]: entry for entry in capabilities("binance")}
        assert report["5m"]["native"] is True
        assert report["5m"]["aggregation_required"] is False
        assert report["1Y"]["aggregation_required"] is True
        assert report["1Y"]["supported"] is True

    def test_provider_supports(self):
        assert provider_supports("binance", "5m")
        assert not provider_supports("binance", "7m")
        assert not provider_supports("unknown-provider", "5m")


class TestFailover:
    @pytest.mark.asyncio
    async def test_primary_failure_falls_over(self):
        primary, backup = FakeProvider(fail=True), FakeProvider()
        primary.name, backup.name = "fake-a", "fake-b"
        backup.native_intervals = primary.native_intervals
        manager = CryptoMarketManager([primary, backup])
        series = await manager.get_candles("BTC", "5m", limit=50)
        assert series.source == "fake-b"
        assert any("failover" in note for note in series.notes)
        assert manager.stats()["providers"][0]["failures"] >= 1
        await manager.close()

    @pytest.mark.asyncio
    async def test_quote_failover_and_error_trail(self):
        primary = FakeProvider(fail=True)
        backup = FakeProvider()
        primary.name, backup.name = "fake-a", "fake-b"
        manager = CryptoMarketManager([primary, backup])
        quote = await manager.get_quote("BTC")
        assert quote.source == "fake-b"
        assert quote.errors  # the real failure is recorded, not hidden
        await manager.close()

    @pytest.mark.asyncio
    async def test_total_failure_returns_empty_series_with_reason(self):
        dead = FakeProvider(fail=True)
        dead.name = "fake-a"
        manager = CryptoMarketManager([dead])
        series = await manager.get_candles("BTC", "5m", limit=50, allow_stale=False)
        assert series.empty
        assert series.source == "unavailable"
        await manager.close()

    @pytest.mark.asyncio
    async def test_requires_at_least_one_provider(self):
        with pytest.raises(ValueError):
            CryptoMarketManager([])

    @pytest.mark.asyncio
    async def test_stale_cache_served_on_outage(self):
        provider = FakeProvider()
        provider.name = "fake-a"
        manager = CryptoMarketManager([provider])
        # Use a long TTL so the cached entry is still logically fresh when the
        # upstream dies — the point here is outage resilience, not expiry.
        from app.providers.cache import TTLCache

        manager.cache = TTLCache(default_ttl_seconds=600)
        fresh = await manager.get_candles("BTC", "5m", limit=50)
        assert not fresh.empty
        provider.fail = True  # simulate the upstream dying after a successful fetch
        stale = await manager.get_candles("BTC", "5m", limit=50)
        assert not stale.empty
        assert stale.source == "fake-a"
        await manager.close()


class TestRollup:
    @pytest.mark.asyncio
    async def test_yearly_candles_are_aggregated_from_monthly(self):
        provider = FakeProvider()
        provider.name = "fake-a"
        provider.native_intervals = ("5m", "1h", "1d", "1M")
        manager = CryptoMarketManager([provider])
        series = await manager.get_candles("BTC", "1Y")
        assert series.aggregated is True
        assert series.interval == "1M"
        assert series.timeframe == "1Y"
        assert series.stats["aggregated_from"] >= series.stats["aggregated_to"]
        await manager.close()
