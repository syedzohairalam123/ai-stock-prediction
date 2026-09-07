import math
from datetime import date

import pandas as pd
import pytest

from app.providers.base import DataStatus, MarketDataProvider, ProviderError, Quote
from app.providers.manager import MarketDataManager


class FakeProvider(MarketDataProvider):
    """A test double that behaves however a test wants: always fails, always
    succeeds, or fails a set number of times before succeeding."""

    def __init__(self, name, fail=False, configured=True, frame=None, quote=None):
        self.name = name
        self.fail = fail
        self._configured = configured
        self.frame = frame if frame is not None else pd.DataFrame({"Close": [1.0, 2.0]})
        self.quote_value = quote
        self.history_calls = 0
        self.quote_calls = 0

    def is_configured(self):
        return self._configured

    async def get_history(self, ticker, start, end, interval="1d"):
        self.history_calls += 1
        if self.fail:
            raise ProviderError(self.name, "simulated failure")
        return self.frame

    async def get_quote(self, ticker):
        self.quote_calls += 1
        if self.fail:
            raise ProviderError(self.name, "simulated failure")
        return self.quote_value or Quote(ticker=ticker, price=123.45, source=self.name, status=DataStatus.LIVE)


@pytest.mark.asyncio
async def test_primary_success_returns_live_and_correct_source():
    primary = FakeProvider("primary")
    manager = MarketDataManager(providers=[primary])
    frame, source, status = await manager.history("AAPL", date.today(), date.today())
    assert source == "primary"
    assert status == DataStatus.LIVE
    assert primary.history_calls == 1


@pytest.mark.asyncio
async def test_fallback_to_secondary_when_primary_fails():
    primary = FakeProvider("primary", fail=True)
    secondary = FakeProvider("secondary")
    manager = MarketDataManager(providers=[primary, secondary])
    frame, source, status = await manager.history("AAPL", date.today(), date.today())
    assert source == "secondary"
    assert status == DataStatus.LIVE
    assert primary.history_calls == 1
    assert secondary.history_calls == 1


@pytest.mark.asyncio
async def test_all_providers_fail_and_no_cache_raises():
    manager = MarketDataManager(providers=[FakeProvider("a", fail=True), FakeProvider("b", fail=True)])
    with pytest.raises(ProviderError):
        await manager.history("AAPL", date.today(), date.today())


@pytest.mark.asyncio
async def test_second_call_is_served_from_cache_without_calling_provider_again():
    primary = FakeProvider("primary")
    manager = MarketDataManager(providers=[primary], history_cache_ttl=60)
    await manager.history("AAPL", date.today(), date.today())
    frame, source, status = await manager.history("AAPL", date.today(), date.today())
    assert status == DataStatus.CACHED
    assert primary.history_calls == 1  # not called twice


@pytest.mark.asyncio
async def test_stale_cache_used_as_last_resort_when_everything_fails():
    primary = FakeProvider("primary")
    manager = MarketDataManager(providers=[primary], history_cache_ttl=0.01)
    await manager.history("AAPL", date.today(), date.today())
    import asyncio
    await asyncio.sleep(0.05)  # let the cache entry expire
    primary.fail = True  # now simulate an outage
    frame, source, status = await manager.history("AAPL", date.today(), date.today())
    assert status == DataStatus.STALE
    assert source == "primary"


@pytest.mark.asyncio
async def test_unconfigured_provider_is_dropped_at_init():
    configured = FakeProvider("configured", configured=True)
    unconfigured = FakeProvider("unconfigured", configured=False)
    manager = MarketDataManager(providers=[unconfigured, configured])
    assert [p.name for p in manager.providers] == ["configured"]


@pytest.mark.asyncio
async def test_quote_unavailable_when_all_providers_fail_and_no_cache():
    manager = MarketDataManager(providers=[FakeProvider("a", fail=True)])
    quote = await manager.quote("AAPL")
    assert quote.status == DataStatus.UNAVAILABLE
    assert math.isnan(quote.price)  # never a fabricated 0.0 — callers must check status


@pytest.mark.asyncio
async def test_init_raises_if_no_provider_is_configured():
    with pytest.raises(RuntimeError):
        MarketDataManager(providers=[FakeProvider("x", configured=False)])
