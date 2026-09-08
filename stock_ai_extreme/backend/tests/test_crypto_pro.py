"""Tests for crypto_pro.py — source selection + normalization."""
import asyncio
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.crypto_pro import coingecko_rows, crypto_overview, yfinance_rows


def _fake_frame(n_days: int = 60, base: float = 50000.0) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    closes = [base * (1 + i * 0.001) for i in range(n_days)]
    return pd.DataFrame({
        "Open": closes, "High": [c * 1.01 for c in closes], "Low": [c * 0.99 for c in closes],
        "Close": closes, "Volume": [1_000] * n_days,
    }, index=idx)


class StubManager:
    async def history(self, ticker, start, end, interval="1d"):
        return _fake_frame(base=50000.0 if "BTC" in ticker else 3000.0), "yfinance", "LIVE"


FAKE_CG = [
    {
        "id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 65000.0,
        "price_change_percentage_24h_in_currency": 1.2,
        "price_change_percentage_7d_in_currency": -3.4,
        "price_change_percentage_30d_in_currency": 10.0,
        "market_cap": 1_280_000_000_000, "market_cap_rank": 1,
        "total_volume": 30_000_000_000, "circulating_supply": 19_700_000,
        "ath": 73000.0, "ath_change_percentage": -10.9,
    },
    {
        "id": "ethereum", "symbol": "eth", "name": "Ethereum", "current_price": 3200.0,
        "price_change_percentage_24h_in_currency": -0.8,
        "price_change_percentage_7d_in_currency": 2.0,
        "price_change_percentage_30d_in_currency": 5.0,
        "market_cap": 384_000_000_000, "market_cap_rank": 2,
        "total_volume": 15_000_000_000, "circulating_supply": 120_000_000,
        "ath": 4800.0, "ath_change_percentage": -33.3,
    },
]


def test_coingecko_rows_normalize():
    with patch("app.crypto_pro._fetch_coingecko_markets", return_value=FAKE_CG):
        rows = coingecko_rows()
    assert rows[0]["symbol"] == "BTC-USD"
    assert rows[0]["price"] == 65000.0
    assert rows[0]["market_cap_rank"] == 1
    assert rows[0]["source"] == "coingecko"


def test_yfinance_rows_same_shape():
    rows = asyncio.run(yfinance_rows(StubManager()))
    assert rows, "should return a row per curated symbol"
    btc = next(r for r in rows if r["symbol"] == "BTC-USD")
    assert btc["price"] > 0
    assert btc["market_cap"] is None  # honest: this source can't know it
    assert set(btc.keys()) >= {"symbol", "name", "price", "change_percent_24h", "market_cap", "source"}


def test_overview_coingecko_summary_dominance():
    with patch("app.crypto_pro._fetch_coingecko_markets", return_value=FAKE_CG):
        report = asyncio.run(crypto_overview(StubManager(), source="coingecko"))
    assert report["status"] == "OK"
    assert report["summary"]["btc_dominance_pct"] == pytest.approx(
        1_280_000_000_000 / (1_280_000_000_000 + 384_000_000_000) * 100, abs=0.1
    )
    assert report["summary"]["top_gainer_7d"] in ("BTC-USD", "ETH-USD")


def test_overview_coingecko_failure_is_unavailable_not_substituted():
    with patch("app.crypto_pro._fetch_coingecko_markets", side_effect=ConnectionError("rate limited")):
        report = asyncio.run(crypto_overview(StubManager(), source="coingecko"))
    assert report["status"] == "UNAVAILABLE"
    assert report["reason"] == "rate limited"
    assert report["coins"] == []


def test_overview_rejects_unknown_source():
    with pytest.raises(ValueError, match="Unknown source"):
        asyncio.run(crypto_overview(StubManager(), source="magic"))


def test_overview_yfinance_source_works():
    report = asyncio.run(crypto_overview(StubManager(), source="yfinance"))
    assert report["status"] == "OK"
    assert all(r["source"] in ("yfinance", "none") for r in report["coins"])
