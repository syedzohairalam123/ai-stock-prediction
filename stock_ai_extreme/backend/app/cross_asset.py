"""
Phase 12 — cross-asset intelligence.

Pure computation on price series the app has already fetched — no new data
source needed, correlation/beta/relative-strength are all just statistics
over returns. Everything here is deterministic and testable with synthetic
price series, no network required.
"""
from __future__ import annotations

import pandas as pd


def build_return_frame(price_series: dict[str, pd.Series]) -> pd.DataFrame:
    """price_series: {ticker: Close series indexed by date}. Aligns all
    series on their shared dates and converts to daily returns — correlation
    and beta must be computed on returns, never on raw price levels (raw
    prices are almost always spuriously correlated just because they trend)."""
    prices = pd.DataFrame(price_series).sort_index()
    prices = prices.dropna(how="any")
    if prices.empty:
        raise ValueError("No overlapping dates across the requested tickers.")
    return prices.pct_change().dropna()


def correlation_matrix(price_series: dict[str, pd.Series]) -> dict:
    returns = build_return_frame(price_series)
    corr = returns.corr()
    return {row: {col: round(float(val), 4) for col, val in corr[row].items()} for row in corr.index}


def rolling_correlation(price_series: dict[str, pd.Series], a: str, b: str, window: int = 30) -> list[dict]:
    returns = build_return_frame(price_series)
    if a not in returns.columns or b not in returns.columns:
        raise ValueError(f"{a} or {b} not present in the supplied price series.")
    rc = returns[a].rolling(window).corr(returns[b]).dropna()
    return [{"date": pd.Timestamp(d).date().isoformat(), "correlation": round(float(v), 4)} for d, v in rc.items()]


def beta(price_series: dict[str, pd.Series], ticker: str, benchmark: str) -> float:
    returns = build_return_frame(price_series)
    if ticker not in returns.columns or benchmark not in returns.columns:
        raise ValueError(f"{ticker} or {benchmark} not present in the supplied price series.")
    cov_matrix = returns[[ticker, benchmark]].cov()
    benchmark_var = cov_matrix.loc[benchmark, benchmark]
    if benchmark_var == 0:
        raise ValueError(f"{benchmark} has zero variance over this window — cannot compute beta.")
    return round(float(cov_matrix.loc[ticker, benchmark] / benchmark_var), 4)


def relative_strength(price_series: dict[str, pd.Series], ticker: str, benchmark: str) -> list[dict]:
    """Indexed relative performance: how `ticker` did versus `benchmark`,
    both rebased to 100 at the start of the window. Above 100 and rising =
    outperforming; below and falling = underperforming."""
    prices = pd.DataFrame({ticker: price_series[ticker], benchmark: price_series[benchmark]}).dropna()
    if prices.empty:
        raise ValueError(f"No overlapping dates between {ticker} and {benchmark}.")
    rebased_asset = prices[ticker] / prices[ticker].iloc[0] * 100
    rebased_bench = prices[benchmark] / prices[benchmark].iloc[0] * 100
    rs = (rebased_asset / rebased_bench * 100).round(4)
    return [{"date": pd.Timestamp(d).date().isoformat(), "relative_strength": float(v)} for d, v in rs.items()]


def asset_stats(price_series: dict[str, pd.Series], volumes: dict[str, pd.Series] | None = None) -> dict:
    """Per-ticker summary stats — total return, annualized volatility, and
    average volume — the three axes Phase 15's 3D market map plots. Reuses
    the exact same price data the correlation matrix is built from."""
    stats = {}
    for ticker, prices in price_series.items():
        returns = prices.pct_change().dropna()
        if returns.empty:
            continue
        total_return_pct = round(float((prices.iloc[-1] / prices.iloc[0] - 1) * 100), 4)
        annualized_vol_pct = round(float(returns.std() * (252 ** 0.5) * 100), 4)
        avg_volume = None
        if volumes and ticker in volumes and not volumes[ticker].empty:
            avg_volume = round(float(volumes[ticker].mean()), 2)
        stats[ticker] = {"total_return_pct": total_return_pct, "annualized_volatility_pct": annualized_vol_pct, "avg_volume": avg_volume}
    return stats


def cross_asset_report(price_series: dict[str, pd.Series], benchmark: str = "SPY", volumes: dict[str, pd.Series] | None = None) -> dict:
    """One-shot summary: full correlation matrix, plus each non-benchmark
    ticker's beta and latest relative-strength reading versus `benchmark`,
    plus per-ticker return/volatility/volume stats for the 3D market map."""
    corr = correlation_matrix(price_series)
    betas, rel_strength_latest = {}, {}
    if benchmark in price_series:
        for ticker in price_series:
            if ticker == benchmark:
                continue
            try:
                betas[ticker] = beta(price_series, ticker, benchmark)
                rs = relative_strength(price_series, ticker, benchmark)
                rel_strength_latest[ticker] = rs[-1]["relative_strength"] if rs else None
            except ValueError:
                continue  # e.g. no overlap with this particular ticker — skip it, don't fail the whole report
    return {
        "benchmark": benchmark, "correlation_matrix": corr, "beta": betas,
        "relative_strength_latest": rel_strength_latest, "asset_stats": asset_stats(price_series, volumes),
    }
