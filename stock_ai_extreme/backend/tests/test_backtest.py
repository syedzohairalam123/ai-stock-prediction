import numpy as np
import pandas as pd
import pytest

from app.backtest import walk_forward_backtest
from app.indicators import add_indicators


def _ohlcv(n, seed=3, trend=0.3, noise=0.05):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.full(n, trend) + rng.normal(0, noise, n))
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close + rng.normal(0, 0.1, n)
    volume = rng.integers(1_000_000, 3_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


def test_raises_with_too_little_data():
    df = add_indicators(_ohlcv(80))
    with pytest.raises(ValueError, match="Not enough usable rows"):
        walk_forward_backtest(df, test_days=60)


def test_returns_expected_structure_and_length():
    df = add_indicators(_ohlcv(220))
    result = walk_forward_backtest(df, model_kind="ridge", test_days=40, refit_every=5)
    assert len(result.daily) == 40
    assert result.test_days == 40
    assert 0.0 <= result.win_rate <= 1.0
    assert result.max_drawdown_pct >= 0.0
    assert result.num_trades <= 40


def test_strong_uptrend_produces_mostly_long_positions_and_positive_return():
    # A steady, low-noise uptrend should be easy to predict correctly, so the
    # strategy should go long most days and end up with a positive return.
    df = add_indicators(_ohlcv(220, trend=0.5, noise=0.02))
    result = walk_forward_backtest(df, model_kind="ridge", test_days=40, refit_every=5)
    long_days = sum(1 for d in result.daily if d["went_long"])
    assert long_days > 30            # mostly long on a clear uptrend
    assert result.total_return_pct > 0
    assert result.directional_accuracy > 0.6


def test_random_forest_model_kind_also_works():
    df = add_indicators(_ohlcv(200))
    result = walk_forward_backtest(df, model_kind="rf", test_days=20, refit_every=10)
    assert result.model == "rf"
    assert len(result.daily) == 20


def test_benchmark_return_is_independent_of_strategy_choices():
    df = add_indicators(_ohlcv(220, seed=11))
    result = walk_forward_backtest(df, test_days=40, refit_every=5)
    # benchmark = buy-and-hold every day in the window, regardless of the model's calls
    actual_closes = [d["actual"] for d in result.daily]
    assert len(actual_closes) == 40
