from unittest.mock import AsyncMock

import pytest

from app.multi_asset import CRYPTO_SYMBOLS, build_overview
from app.providers.base import DataStatus, Quote


class FakeManager:
    def __init__(self, fail_symbols=None):
        self.fail_symbols = fail_symbols or set()

    async def quote(self, symbol):
        if symbol in self.fail_symbols:
            raise RuntimeError("simulated provider outage")
        return Quote(ticker=symbol, price=100.0, source="yfinance", status=DataStatus.LIVE, change_percent=1.5)


@pytest.mark.asyncio
async def test_build_overview_returns_one_entry_per_symbol():
    results = await build_overview(FakeManager(), "crypto")
    assert len(results) == len(CRYPTO_SYMBOLS)
    assert all(r["status"] == "LIVE" for r in results)
    assert all(r["price"] == 100.0 for r in results)


@pytest.mark.asyncio
async def test_a_single_failing_symbol_does_not_break_the_whole_batch():
    failing_symbol = next(iter(CRYPTO_SYMBOLS))
    results = await build_overview(FakeManager(fail_symbols={failing_symbol}), "crypto")
    assert len(results) == len(CRYPTO_SYMBOLS)
    failed = [r for r in results if r["symbol"] == failing_symbol][0]
    assert failed["status"] == "UNAVAILABLE"
    assert failed["price"] is None
    others_ok = [r for r in results if r["symbol"] != failing_symbol]
    assert all(r["status"] == "LIVE" for r in others_ok)


@pytest.mark.asyncio
async def test_unknown_asset_class_raises():
    with pytest.raises(ValueError, match="Unknown asset class"):
        await build_overview(FakeManager(), "not-a-real-class")


@pytest.mark.asyncio
async def test_commodities_and_forex_also_work():
    for asset_class in ("commodities", "forex"):
        results = await build_overview(FakeManager(), asset_class)
        assert len(results) > 0
