"""PSX symbol-resolution tests.

Yahoo Finance lists PSX (Karachi) companies as `<TICKER>.KA` — the bare symbol
returns nothing at all. These tests pin the resolution rules and prove the
yfinance provider actually walks the candidate list instead of silently giving
up, all without touching the network.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.providers.base import ProviderError
from app.providers.yfinance_provider import YFinanceProvider
from app.symbols import PSX_SUFFIX, is_psx_symbol, symbol_candidates, to_yahoo_symbol


def _frame(n_days: int = 5) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    return pd.DataFrame({"Close": [100.0 + i for i in range(n_days)]}, index=idx)


# ---------------------------------------------------------------------------
# Resolution rules
# ---------------------------------------------------------------------------

def test_known_psx_symbol_maps_straight_to_karachi_suffix():
    assert symbol_candidates("OGDC") == [f"OGDC{PSX_SUFFIX}"]
    assert symbol_candidates("ogdc") == [f"OGDC{PSX_SUFFIX}"]
    assert to_yahoo_symbol("MEBL") == f"MEBL{PSX_SUFFIX}"
    assert is_psx_symbol("LUCK") and is_psx_symbol("kel")
    assert not is_psx_symbol("AAPL")


@pytest.mark.parametrize("symbol", ["OGDC.KA", "BRK.B", "GC=F", "EURUSD=X", "^GSPC"])
def test_already_qualified_symbols_are_used_as_is(symbol):
    assert symbol_candidates(symbol) == [symbol.upper()]


def test_unknown_symbol_gets_a_single_suffix_fallback():
    assert symbol_candidates("ZZTEST") == ["ZZTEST", "ZZTEST.KA"]
    # For calls where an empty answer is valid (news), never probe a variant.
    assert symbol_candidates("ZZTEST", suffix_fallback=False) == ["ZZTEST"]


def test_blank_ticker_is_handled_without_crashing():
    assert symbol_candidates("") == [""]
    assert symbol_candidates("   ") == [""]


# ---------------------------------------------------------------------------
# Provider behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_uses_karachi_symbol_directly_for_known_psx():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    seen: list[str] = []

    def fake_fetch(symbol, start, end, interval):
        seen.append(symbol)
        return _frame() if symbol == "OGDC.KA" else pd.DataFrame()

    with patch.object(provider, "_fetch", side_effect=fake_fetch):
        df = await provider.get_history("OGDC", date.today() - timedelta(days=60), date.today())

    assert not df.empty
    assert seen == ["OGDC.KA"]  # never wastes a request on the bare symbol


@pytest.mark.asyncio
async def test_history_falls_back_to_suffix_for_unknown_symbol():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    seen: list[str] = []

    def fake_fetch(symbol, start, end, interval):
        seen.append(symbol)
        return _frame() if symbol == "ZZTEST.KA" else pd.DataFrame()

    with patch.object(provider, "_fetch", side_effect=fake_fetch):
        df = await provider.get_history("ZZTEST", date.today() - timedelta(days=60), date.today())

    assert not df.empty
    assert seen == ["ZZTEST", "ZZTEST.KA"]


@pytest.mark.asyncio
async def test_history_raises_when_no_candidate_has_data():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    with patch.object(provider, "_fetch", return_value=pd.DataFrame()):
        with pytest.raises(ProviderError):
            await provider.get_history("NOPEZZ", date.today() - timedelta(days=10), date.today())


@pytest.mark.asyncio
async def test_quote_falls_back_to_karachi_symbol():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    seen: list[str] = []

    def fake_fetch(symbol, start, end, interval):
        seen.append(symbol)
        return _frame() if symbol == "OGDC.KA" else pd.DataFrame()

    with patch.object(provider, "_fetch", side_effect=fake_fetch):
        quote = await provider.get_quote("OGDC")

    assert quote.ticker == "OGDC"  # caller-facing ticker stays bare
    assert quote.price > 0
    assert seen == ["OGDC.KA"]


@pytest.mark.asyncio
async def test_profile_reports_caller_ticker_not_internal_suffix():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)

    def fake_info(symbol):
        return {"longName": "Meezan Bank Limited", "currency": "PKR"} if symbol == "MEBL.KA" else {}

    with patch.object(provider, "_fetch_info", side_effect=fake_info):
        profile = await provider.get_profile("MEBL")

    assert profile["ticker"] == "MEBL"
    assert profile["name"] == "Meezan Bank Limited"


@pytest.mark.asyncio
async def test_news_uses_karachi_symbol_for_known_psx():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    seen: list[str] = []

    def fake_news(symbol):
        seen.append(symbol)
        if symbol != "SYS.KA":
            return []
        return [{"title": "Systems Ltd wins contract", "publisher": "Business Recorder",
                 "link": "https://example.test/a", "type": "STORY", "providerPublishTime": 1_700_000_000}]

    with patch.object(provider, "_fetch_news", side_effect=fake_news):
        items = await provider.get_news("SYS")

    assert seen == ["SYS.KA"]
    assert items[0]["title"] == "Systems Ltd wins contract"


@pytest.mark.asyncio
async def test_news_does_not_probe_suffix_for_unknown_symbol():
    """An empty headline list is a valid answer — don't pay for a second call."""
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    seen: list[str] = []

    def fake_news(symbol):
        seen.append(symbol)
        return []

    with patch.object(provider, "_fetch_news", side_effect=fake_news):
        items = await provider.get_news("ZZTEST")

    assert items == []
    assert seen == ["ZZTEST"]
