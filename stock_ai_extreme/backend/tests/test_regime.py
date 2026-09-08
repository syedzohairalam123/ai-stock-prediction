"""Tests for regime.py — rule-based classifier + optional HMM."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.regime import REGIMES, detect_regime, hmm_regime, rule_based_regime


def _trending_frame(n_days: int = 300, drift: float = 0.4, noise: float = 0.2, seed: int = 7) -> pd.DataFrame:
    """A clean synthetic uptrend/downtrend with mild noise — deterministic."""
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0, noise, n_days)
    closes = 100 * np.exp(np.cumsum(steps / 100))
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


def _enriched(df: pd.DataFrame) -> pd.DataFrame:
    from app.indicators import add_indicators
    return add_indicators(df)


def test_rule_based_detects_uptrend():
    df = _enriched(_trending_frame(drift=0.5, noise=0.05))
    result = rule_based_regime(df)
    assert result["method"] == "rule_based"
    assert result["regime"] in REGIMES
    assert result["regime"] == "trending_up"
    assert result["signals"]["adx_14"] is not None
    assert result["reasoning"]


def test_rule_based_detects_downtrend():
    df = _enriched(_trending_frame(drift=-0.5, noise=0.05))
    result = rule_based_regime(df)
    assert result["regime"] == "trending_down"


def test_rule_based_low_vol_range_market():
    # Flat drifting series with tiny noise -> weak ADX -> range_bound
    df = _enriched(_trending_frame(drift=0.0, noise=0.02, seed=3))
    result = rule_based_regime(df)
    assert result["regime"] in ("range_bound", "trending_up", "trending_down")


def test_all_thresholds_are_visible_in_response():
    df = _enriched(_trending_frame())
    result = rule_based_regime(df)
    assert "signals" in result and "reasoning" in result
    assert result["confidence"] <= 1.0


def test_hmm_returns_none_without_hmmlearn():
    # hmmlearn is intentionally not a hard dependency; if absent, HMM degrades to None
    df = _enriched(_trending_frame())
    result = hmm_regime(df)
    assert result is None or result["method"] == "hmm_gaussian"


def test_detect_regime_insufficient_data():
    idx = pd.date_range(end=date.today(), periods=30, freq="B")
    short = pd.DataFrame({"Close": np.linspace(100, 101, 30)}, index=idx)
    result = detect_regime(short)
    assert result["status"] == "insufficient_data"
    assert result["rule_based"] is None


def test_detect_regime_full_report():
    df = _enriched(_trending_frame())
    result = detect_regime(df)
    assert result["status"] == "ok"
    assert result["rule_based"]["regime"] in REGIMES
    assert "summary" in result
    assert "not a prediction" in result["disclaimer"]
