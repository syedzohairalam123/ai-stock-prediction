import numpy as np
import pandas as pd
import pytest

from app.baselines import (
    baseline_report,
    evaluate_moving_average,
    evaluate_naive_persistence,
    forecast_moving_average,
    forecast_naive_persistence,
)


def _flat_price_df(n=60, price=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": [price] * n}, index=idx)


def _trending_price_df(n=60, start=100.0, step=1.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": [start + i * step for i in range(n)]}, index=idx)


def test_naive_persistence_is_perfect_on_a_flat_series():
    metrics = evaluate_naive_persistence(_flat_price_df())
    assert metrics["mae"] == 0.0
    assert metrics["rmse"] == 0.0
    assert metrics["name"] == "naive_persistence"


def test_naive_persistence_has_nonzero_error_on_a_trending_series():
    metrics = evaluate_naive_persistence(_trending_price_df())
    assert metrics["mae"] > 0  # always "wrong by one step" on a steady trend


def test_moving_average_lags_behind_a_trend_more_than_naive_persistence():
    df = _trending_price_df()
    naive = evaluate_naive_persistence(df)
    ma = evaluate_moving_average(df, window=10)
    # on a steady uptrend, a 10-day trailing average lags further behind
    # "tomorrow" than just repeating today's price does
    assert ma["mae"] > naive["mae"]


def test_forecast_naive_persistence_repeats_last_close():
    df = _trending_price_df()
    preds = forecast_naive_persistence(df, horizon=5)
    assert preds == [float(df.Close.iloc[-1])] * 5


def test_forecast_moving_average_repeats_the_trailing_mean():
    df = _trending_price_df()
    preds = forecast_moving_average(df, horizon=3, window=10)
    assert preds == [float(df.Close.tail(10).mean())] * 3


def test_baseline_report_contains_both_baselines():
    report = baseline_report(_trending_price_df())
    assert set(report.keys()) == {"naive_persistence", "moving_average_10"}
    for v in report.values():
        assert "mae" in v and "rmse" in v and "directional_accuracy" in v
