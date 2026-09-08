import numpy as np
import pandas as pd
import pytest

from app.cross_asset import asset_stats, beta, correlation_matrix, cross_asset_report, relative_strength, rolling_correlation


def _series(n, seed, drift=0.0, scale=1.0, base=100.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = drift + scale * rng.normal(0, 0.01, n)
    prices = base * np.cumprod(1 + returns)
    return pd.Series(prices, index=idx)


def test_correlation_is_near_one_for_a_scaled_copy():
    base = _series(200, seed=1)
    scaled = base * 1.5 + 3  # a price-level transform, but returns should still track closely
    corr = correlation_matrix({"A": base, "B": scaled})
    assert corr["A"]["B"] > 0.99


def test_correlation_is_near_negative_one_for_an_inverted_series():
    base = _series(200, seed=2)
    # construct B's returns as the exact negative of A's returns
    a_returns = base.pct_change().dropna()
    b_prices = [100.0]
    for r in a_returns:
        b_prices.append(b_prices[-1] * (1 - r))
    inverted = pd.Series(b_prices, index=base.index)
    corr = correlation_matrix({"A": base, "B": inverted})
    assert corr["A"]["B"] < -0.99


def test_correlation_matrix_diagonal_is_one():
    a, b = _series(150, seed=3), _series(150, seed=4)
    corr = correlation_matrix({"A": a, "B": b})
    assert corr["A"]["A"] == 1.0
    assert corr["B"]["B"] == 1.0


def test_beta_of_a_double_leveraged_series_is_close_to_two():
    bench = _series(300, seed=5, scale=1.0)
    bench_returns = bench.pct_change().dropna()
    leveraged_prices = [100.0]
    for r in bench_returns:
        leveraged_prices.append(leveraged_prices[-1] * (1 + 2 * r))
    leveraged = pd.Series(leveraged_prices, index=bench.index)
    b = beta({"LEV": leveraged, "SPY": bench}, "LEV", "SPY")
    assert b == pytest.approx(2.0, abs=0.05)


def test_relative_strength_shows_outperformance():
    bench = _series(200, seed=6, drift=0.0002)
    bench_returns = bench.pct_change().dropna()
    # Construct the outperformer as the benchmark's own returns plus a fixed
    # extra edge every day — deterministically ahead, not just "different
    # random seed, hopefully drifts up more" (which can flake on noise alone).
    outperformer_prices = [100.0]
    for r in bench_returns:
        outperformer_prices.append(outperformer_prices[-1] * (1 + r + 0.003))
    outperformer = pd.Series(outperformer_prices, index=bench.index)
    rs = relative_strength({"OUT": outperformer, "SPY": bench}, "OUT", "SPY")
    assert rs[0]["relative_strength"] == pytest.approx(100.0, abs=0.01)
    assert rs[-1]["relative_strength"] > 100.0


def test_rolling_correlation_returns_expected_length():
    a, b = _series(200, seed=8), _series(200, seed=9)
    rc = rolling_correlation({"A": a, "B": b}, "A", "B", window=30)
    assert len(rc) > 0
    assert all(-1.0 <= r["correlation"] <= 1.0 for r in rc)


def test_correlation_raises_on_no_overlap():
    a = pd.Series([1, 2, 3], index=pd.date_range("2024-01-01", periods=3))
    b = pd.Series([1, 2, 3], index=pd.date_range("2025-01-01", periods=3))
    with pytest.raises(ValueError):
        correlation_matrix({"A": a, "B": b})


def test_cross_asset_report_structure():
    spy, aapl, msft = _series(200, seed=10), _series(200, seed=11), _series(200, seed=12)
    report = cross_asset_report({"SPY": spy, "AAPL": aapl, "MSFT": msft}, benchmark="SPY")
    assert report["benchmark"] == "SPY"
    assert set(report["beta"].keys()) == {"AAPL", "MSFT"}
    assert set(report["relative_strength_latest"].keys()) == {"AAPL", "MSFT"}
    assert "SPY" in report["correlation_matrix"]


def test_asset_stats_total_return_matches_simple_calculation():
    prices = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2024-01-01", periods=3))
    stats = asset_stats({"X": prices})
    assert stats["X"]["total_return_pct"] == pytest.approx(21.0, abs=0.01)


def test_asset_stats_volatility_is_zero_for_a_perfectly_flat_series():
    prices = pd.Series([100.0] * 50, index=pd.date_range("2024-01-01", periods=50))
    stats = asset_stats({"FLAT": prices})
    assert stats["FLAT"]["annualized_volatility_pct"] == 0.0


def test_asset_stats_includes_volume_when_provided():
    prices = _series(100, seed=20)
    volumes = pd.Series([1_000_000.0] * 100, index=prices.index)
    stats = asset_stats({"X": prices}, volumes={"X": volumes})
    assert stats["X"]["avg_volume"] == 1_000_000.0


def test_asset_stats_volume_is_none_when_not_provided():
    prices = _series(100, seed=21)
    stats = asset_stats({"X": prices})
    assert stats["X"]["avg_volume"] is None


def test_cross_asset_report_includes_asset_stats_for_every_ticker():
    spy, aapl = _series(150, seed=30), _series(150, seed=31)
    report = cross_asset_report({"SPY": spy, "AAPL": aapl}, benchmark="SPY")
    assert set(report["asset_stats"].keys()) == {"SPY", "AAPL"}
    assert "total_return_pct" in report["asset_stats"]["AAPL"]
    assert "annualized_volatility_pct" in report["asset_stats"]["AAPL"]
