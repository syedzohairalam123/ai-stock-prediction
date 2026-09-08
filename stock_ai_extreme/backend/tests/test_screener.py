"""Tests for screener.py — factor scoring and composite ranking."""
import asyncio
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.indicators import add_indicators
from app.screener import _composite_rank, scan, score_frame


def _frame(n_days: int = 300, drift: float = 0.3, base: float = 100.0, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0, 0.15, n_days)
    closes = base * np.exp(np.cumsum(steps / 100))
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


class StubManager:
    def __init__(self, drifts: dict[str, float]):
        self.drifts = drifts

    async def history(self, ticker, start, end, interval="1d"):
        if ticker == "BADTICKER":
            raise ValueError("no data")
        return _frame(drift=self.drifts.get(ticker, 0.1)), "yfinance", "LIVE"


def test_score_frame_computes_real_factors():
    enriched = add_indicators(_frame(drift=0.5))
    f = score_frame(enriched)
    assert f["momentum_3m_pct"] > 0  # clean uptrend must show positive momentum
    assert f["last_close"] > 0
    assert f["annualized_volatility_pct"] is not None
    assert f["rsi_14"] is not None


def test_composite_rank_orders_by_score():
    rows = [
        {"ticker": "WEAK", "momentum_1m_pct": -5.0, "momentum_3m_pct": -10.0, "trend_score": -3.0,
         "rsi_14": 40.0, "annualized_volatility_pct": 50.0},
        {"ticker": "STRONG", "momentum_1m_pct": 8.0, "momentum_3m_pct": 15.0, "trend_score": 6.0,
         "rsi_14": 60.0, "annualized_volatility_pct": 20.0},
        {"ticker": "MID", "momentum_1m_pct": 1.0, "momentum_3m_pct": 2.0, "trend_score": 0.5,
         "rsi_14": 52.0, "annualized_volatility_pct": 30.0},
    ]
    ranked = _composite_rank(rows)
    assert ranked[0]["ticker"] == "STRONG"
    assert ranked[-1]["ticker"] == "WEAK"
    assert ranked[0]["rank"] == 1
    assert all(r["composite_score"] is not None for r in ranked)


def test_composite_rank_handles_missing_factors_via_set_average():
    rows = [
        {"ticker": "A", "momentum_1m_pct": 5.0, "momentum_3m_pct": None, "trend_score": 3.0,
         "rsi_14": 55.0, "annualized_volatility_pct": 25.0},
        {"ticker": "B", "momentum_1m_pct": -2.0, "momentum_3m_pct": None, "trend_score": 1.0,
         "rsi_14": 48.0, "annualized_volatility_pct": 35.0},
    ]
    ranked = _composite_rank(rows)
    assert len(ranked) == 2
    assert ranked[0]["ticker"] == "A"


def test_scan_ranks_and_reports_unavailable_honestly():
    manager = StubManager({"GOOD1": 0.6, "GOOD2": 0.2})
    result = asyncio.run(scan(manager, ["GOOD1", "GOOD2", "BADTICKER"]))
    assert result["scanned"] == 3
    assert len(result["ranked"]) == 2
    assert "BADTICKER" in result["unavailable"]
    assert result["ranked"][0]["rank"] == 1
    assert "not investment advice" in result["methodology"]["note"].lower()


def test_scan_rejects_empty_ticker_list():
    with pytest.raises(ValueError, match="at least one"):
        asyncio.run(scan(StubManager({}), []))


def test_scan_higher_drift_ranks_first():
    manager = StubManager({"STRONGBULL": 0.8, "WEAKBULL": 0.05})
    result = asyncio.run(scan(manager, ["STRONGBULL", "WEAKBULL"]))
    assert result["ranked"][0]["ticker"] == "STRONGBULL"
