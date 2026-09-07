import numpy as np
import pandas as pd
import pytest

from app.indicators import add_indicators


def _sample_ohlcv(n=120, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 2.0, n)
    low = close - rng.uniform(0.1, 2.0, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


def test_existing_indicators_still_present_and_finite():
    out = add_indicators(_sample_ohlcv())
    for col in ["sma_10", "sma_30", "ema_10", "ema_26", "rsi_14", "macd", "macd_signal", "bb_upper", "bb_lower", "returns"]:
        assert col in out.columns
        assert out[col].notna().all()


def test_atr_is_non_negative():
    out = add_indicators(_sample_ohlcv())
    assert "atr_14" in out.columns
    assert (out["atr_14"] >= 0).all()


def test_stochastic_bounded_between_0_and_100():
    out = add_indicators(_sample_ohlcv())
    assert out["stoch_k"].between(0, 100).all()
    assert out["stoch_d"].between(0, 100).all()


def test_adx_and_directional_indices_are_bounded_and_non_negative():
    out = add_indicators(_sample_ohlcv())
    assert (out["adx_14"] >= 0).all() and (out["adx_14"] <= 100).all()
    assert (out["plus_di_14"] >= 0).all()
    assert (out["minus_di_14"] >= 0).all()


def test_vwap_is_close_to_the_traded_price_range():
    out = add_indicators(_sample_ohlcv())
    # VWAP should sit in a sane range relative to price — not exactly between
    # High/Low every single row (it's a rolling average), but not wildly off either.
    assert out["vwap_14"].min() > out["Low"].min() - 5
    assert out["vwap_14"].max() < out["High"].max() + 5


def test_rsi_bounded_between_0_and_100():
    out = add_indicators(_sample_ohlcv())
    assert out["rsi_14"].between(0, 100).all()


def test_rsi_handles_zero_loss_window_without_producing_nan():
    """Regression test: a strong, steady uptrend can have a 14-day window with
    zero down-days, which used to make RSI divide-by-NaN into NaN and silently
    drop every row downstream (found via the backtest engine's own tests)."""
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    strictly_rising = pd.DataFrame({
        "Open": np.arange(100, 140, dtype=float),
        "High": np.arange(100.5, 140.5, dtype=float),
        "Low": np.arange(99.5, 139.5, dtype=float),
        "Close": np.arange(100, 140, dtype=float),
        "Volume": np.full(40, 1_000_000.0),
    }, index=idx)
    out = add_indicators(strictly_rising)
    assert not out.empty
    assert (out["rsi_14"] == 100.0).all()  # zero down-days in every window -> RSI=100, never NaN



def test_missing_high_low_volume_does_not_crash():
    # A frame with only Close (e.g. some providers) should still work — the
    # High/Low/Volume-dependent indicators are just skipped, not fabricated.
    close_only = _sample_ohlcv()[["Close"]]
    out = add_indicators(close_only)
    assert "sma_10" in out.columns
    assert "atr_14" not in out.columns  # honestly absent, not a fake zero
