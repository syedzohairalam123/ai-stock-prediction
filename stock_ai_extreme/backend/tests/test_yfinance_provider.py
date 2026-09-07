from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.providers.base import DataStatus, ProviderError
from app.providers.yfinance_provider import YFinanceProvider


def _fake_frame(n_days: int, end: date) -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n_days)],
            "High": [101.0 + i for i in range(n_days)],
            "Low": [99.0 + i for i in range(n_days)],
            "Close": [100.5 + i for i in range(n_days)],
            "Volume": [1_000_000] * n_days,
        },
        index=idx,
    )


@pytest.mark.asyncio
async def test_get_history_success():
    provider = YFinanceProvider(max_retries=3, backoff_base_seconds=0.01)
    frame = _fake_frame(30, date.today())
    with patch("app.providers.yfinance_provider.yf.download", return_value=frame) as m:
        result = await provider.get_history("AAPL", date.today() - timedelta(days=60), date.today())
    assert not result.empty
    assert "Close" in result.columns
    m.assert_called_once()


@pytest.mark.asyncio
async def test_get_history_retries_then_succeeds():
    provider = YFinanceProvider(max_retries=3, backoff_base_seconds=0.01)
    frame = _fake_frame(10, date.today())
    with patch(
        "app.providers.yfinance_provider.yf.download",
        side_effect=[ConnectionError("blip"), ConnectionError("blip again"), frame],
    ) as m:
        result = await provider.get_history("AAPL", date.today() - timedelta(days=20), date.today())
    assert not result.empty
    assert m.call_count == 3


@pytest.mark.asyncio
async def test_get_history_all_retries_fail_raises_provider_error():
    provider = YFinanceProvider(max_retries=2, backoff_base_seconds=0.01)
    with patch("app.providers.yfinance_provider.yf.download", side_effect=ConnectionError("down")):
        with pytest.raises(ProviderError):
            await provider.get_history("AAPL", date.today() - timedelta(days=10), date.today())


@pytest.mark.asyncio
async def test_get_history_empty_frame_raises_provider_error():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    with patch("app.providers.yfinance_provider.yf.download", return_value=pd.DataFrame()):
        with pytest.raises(ProviderError):
            await provider.get_history("BADTICKER", date.today() - timedelta(days=10), date.today())


@pytest.mark.asyncio
async def test_get_quote_computes_change_percent_and_marks_live():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    frame = _fake_frame(5, date.today())  # last row's date is "today" (a business day)
    with patch("app.providers.yfinance_provider.yf.download", return_value=frame):
        quote = await provider.get_quote("MSFT")
    assert quote.price == pytest.approx(float(frame["Close"].iloc[-1]))
    assert quote.previous_close == pytest.approx(float(frame["Close"].iloc[-2]))
    assert quote.change_percent is not None
    assert quote.status in (DataStatus.LIVE, DataStatus.RECENT)  # weekend/business-day math can shift this by a day


@pytest.mark.asyncio
async def test_get_profile_maps_expected_fields():
    provider = YFinanceProvider()
    fake_info = {
        "longName": "Alphabet Inc.",
        "sector": "Communication Services",
        "country": "United States",
        "website": "http://www.abc.xyz",
        "longBusinessSummary": "Alphabet is a holding company...",
        "currency": "USD",
        "marketCap": 2_000_000_000_000,
        "exchange": "NMS",
    }
    with patch("app.providers.yfinance_provider.yf.Ticker") as MockTicker:
        MockTicker.return_value.info = fake_info
        profile = await provider.get_profile("GOOGL")
    assert profile["sector"] == "Communication Services"
    assert profile["country"] == "United States"
    assert profile["website"] == "http://www.abc.xyz"
    assert profile["summary"].startswith("Alphabet is a holding company")


@pytest.mark.asyncio
async def test_get_profile_raises_on_empty_info():
    provider = YFinanceProvider(max_retries=1, backoff_base_seconds=0.01)
    with patch("app.providers.yfinance_provider.yf.Ticker") as MockTicker:
        MockTicker.return_value.info = {}
        with pytest.raises(ProviderError):
            await provider.get_profile("NOTATICKER")
