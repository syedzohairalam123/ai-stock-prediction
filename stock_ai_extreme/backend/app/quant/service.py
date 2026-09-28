"""
Phase 21 — orchestration layer for the analytics API.

`routes.py` stays thin (parse → call → serialize); this module owns the actual
workflow: fetch real data through `quant.data`, hand it to the right engine,
attach provenance, and degrade honestly when the sample is too small or the
provider is down. Nothing here computes statistics itself — that is the
specialist modules' job — and nothing here fabricates a number.
"""
from __future__ import annotations

from typing import Any, Optional

from ..logging_config import get_logger
from .config import quant_settings
from .data import fetch_aligned, fetch_benchmark, fetch_prices, fetch_series
from .event_study import abnormal_return_study, bootstrap_mean_ci
from .regression import hac_beta, hac_ols, rolling_beta
from .risk import drawdown_profile, moment_report, risk_of_ruin_summary, tail_risk, volatility_report
from .series import MIN_OBSERVATIONS
from .stationarity import regime_hint, stationarity_report
from .distributions import distribution_fit, goodness_of_fit
from .state import get_manager

logger = get_logger("neural_market.quant.service")


def _meta(bundle, *, extra: Optional[dict] = None) -> dict:
    meta = bundle.describe() if bundle is not None else {"observations": 0}
    meta.update(extra or {})
    return meta


async def instrument_analytics(
    symbol: str,
    *,
    kind: Optional[str] = None,
    lookback_days: Optional[int] = None,
) -> dict:
    """Full statistical picture for one real instrument.

    This is the endpoint the Quant Lab page's analyzer panel calls. It returns
    the six question-blocks side by side — stationarity, distribution, moments,
    volatility, tail risk, drawdown — each with its own availability flag, so a
    thin sample shows "unavailable + reason" for one block while the others
    still answer.
    """
    provider_symbol = kind if (kind and kind.strip().upper() == "PSX") else None
    bundle, returns = await fetch_series(
        symbol,
        provider_symbol=provider_symbol,
        lookback_days=lookback_days or quant_settings.quant_default_lookback_days,
    )
    prices = bundle.closes

    payload: dict[str, Any] = {
        "symbol": bundle.symbol,
        "providerSymbol": bundle.provider_symbol,
        "available": bundle.available,
        "data": _meta(bundle),
        "stationarity": stationarity_report(prices) if prices else {"available": False, "reason": bundle.error},
        "returnsStationarity": (
            stationarity_report(returns.values, include_variance_ratio=False, include_hurst=False)
            if returns.n >= quant_settings.quant_min_stationarity_observations
            else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_stationarity_observations, what="returns")}
        ),
        "distribution": distribution_fit(returns.values) if returns.n >= MIN_OBSERVATIONS else {"available": False, "reason": returns.insufficient(5, what="returns")},
        "goodnessOfFit": goodness_of_fit(returns.values) if returns.n >= 8 else {"available": False, "reason": returns.insufficient(8, what="returns")},
        "moments": moment_report(returns.values) if returns.n >= 4 else {"available": False, "reason": returns.insufficient(4, what="returns")},
        "volatility": volatility_report(returns.values) if returns.n >= quant_settings.quant_min_observations else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_observations, what="returns")},
        "tailRisk": tail_risk(returns.values) if returns.n >= quant_settings.quant_min_observations else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_observations, what="returns")},
        "drawdown": drawdown_profile(prices) if prices else {"available": False, "reason": bundle.error or "no prices"},
        "regimeHint": regime_hint(prices) if prices else {"preferredModel": "unknown", "why": bundle.error or "no price data"},
        "riskOfRuin": risk_of_ruin_summary(returns.values) if returns.n >= quant_settings.quant_min_observations else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_observations, what="returns")},
        "disclaimer": (
            "Statistical description of observed data for education. None of this "
            "is investment advice, and none of it predicts the future with certainty."
        ),
    }
    if not bundle.available:
        payload["note"] = bundle.error
    return payload


async def beta_analytics(
    symbol: str,
    benchmark: Optional[str] = None,
    *,
    lookback_days: Optional[int] = None,
    window: int = 60,
) -> dict:
    """Market-model beta with HAC inference + rolling beta, on aligned real bars."""
    bench = (benchmark or "").strip().upper() or None
    lookback = lookback_days or quant_settings.quant_default_lookback_days

    asset_bundle = await fetch_prices(symbol, lookback_days=lookback)
    if bench:
        bench_bundle = await fetch_prices(bench, lookback_days=lookback)
    else:
        bench_bundle = await fetch_benchmark(lookback_days=lookback)
        bench = bench_bundle.symbol

    aligned = await fetch_aligned(asset_bundle.symbol, bench_bundle.symbol, lookback_days=lookback)
    ra = aligned.get("returnsA") or []
    rb = aligned.get("returnsB") or []

    fit = hac_beta(ra, rb, market_name=bench) if ra and rb else {
        "available": False,
        "reason": aligned.get("reason") or "not enough aligned observations for a regression",
    }
    rolling = rolling_beta(ra, rb, window=min(window, max(20, len(ra) // 3 or 20))) if ra and rb else {"available": False, "reason": "no aligned returns"}

    return {
        "symbol": asset_bundle.symbol,
        "benchmark": bench_bundle.symbol,
        "available": bool(fit.get("available")),
        "data": {"asset": _meta(asset_bundle), "benchmark": _meta(bench_bundle), "alignment": {
            "observations": aligned.get("observations", 0),
            "aligned": aligned.get("aligned", False),
            "reason": aligned.get("reason"),
        }},
        "beta": fit,
        "rolling": rolling,
        "disclaimer": "Association measured on historical bars; a beta is an estimate with error, not a constant.",
    }


async def stationarity_analytics(symbol: str, *, lookback_days: Optional[int] = None) -> dict:
    """Dedicated stationarity endpoint: levels, returns, VR, Hurst, regime hint."""
    bundle, returns = await fetch_series(symbol, lookback_days=lookback_days or quant_settings.quant_default_lookback_days)
    prices = bundle.closes
    return {
        "symbol": bundle.symbol,
        "available": bundle.available,
        "data": _meta(bundle),
        "levels": stationarity_report(prices) if prices else {"available": False, "reason": bundle.error},
        "returns": (
            stationarity_report(returns.values, include_variance_ratio=True, include_hurst=True)
            if returns.n >= quant_settings.quant_min_stationarity_observations
            else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_stationarity_observations, what="returns")}
        ),
        "regimeHint": regime_hint(prices) if prices else {"preferredModel": "unknown", "why": bundle.error},
    }


async def tail_risk_analytics(
    symbol: str,
    *,
    lookback_days: Optional[int] = None,
    horizon: int = 1,
) -> dict:
    """Dedicated VaR/CVaR endpoint with all estimators side by side."""
    bundle, returns = await fetch_series(symbol, lookback_days=lookback_days or quant_settings.quant_default_lookback_days)
    return {
        "symbol": bundle.symbol,
        "available": bundle.available,
        "data": _meta(bundle),
        "tailRisk": tail_risk(returns.values, horizon=max(1, int(horizon))) if returns.n >= quant_settings.quant_min_observations else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_observations, what="returns")},
        "volatility": volatility_report(returns.values) if returns.n >= quant_settings.quant_min_observations else {"available": False, "reason": returns.insufficient(quant_settings.quant_min_observations, what="returns")},
        "distribution": distribution_fit(returns.values) if returns.n >= 5 else {"available": False, "reason": returns.insufficient(5, what="returns")},
    }


async def event_study_analytics(
    symbol: str,
    event_indices: list[int],
    *,
    labels: Optional[list[str]] = None,
    benchmark: Optional[str] = None,
    lookback_days: Optional[int] = None,
    estimation_window: Optional[int] = None,
    gap_window: Optional[int] = None,
    offsets: Optional[list[int]] = None,
) -> dict:
    """Event study on real bars: market model, Patell test, bootstrap CI.

    `event_indices` are bar positions supplied by the caller — normally the
    indices of dates stored by the breaking-news impact tracker, so the study
    measures the *same* events the news desk recorded.
    """
    if not event_indices:
        return {"available": False, "reason": "no event indices supplied"}
    lookback = lookback_days or quant_settings.quant_default_lookback_days
    asset_bundle = await fetch_prices(symbol, lookback_days=lookback)
    if not asset_bundle.available:
        return {"available": False, "symbol": asset_bundle.symbol, "reason": asset_bundle.error, "data": _meta(asset_bundle)}

    if benchmark:
        bench_bundle = await fetch_prices(benchmark, lookback_days=lookback)
    else:
        bench_bundle = await fetch_benchmark(lookback_days=lookback)
    if not bench_bundle.available:
        return {
            "available": False,
            "symbol": asset_bundle.symbol,
            "reason": f"benchmark {bench_bundle.symbol} unavailable: {bench_bundle.error}",
        }

    from .series import align_returns
    ra, rb, ts = align_returns(asset_bundle.as_timestamped(), bench_bundle.as_timestamped())
    study = abnormal_return_study(
        asset_series=ra,
        market_series=rb,
        event_indices=[i for i in event_indices if 0 <= i < len(ra)],
        event_labels=labels,
        estimation_window=estimation_window,
        gap_window=gap_window,
        offsets=offsets,
        source=f"{asset_bundle.source} / {bench_bundle.source}",
    )
    return {
        "symbol": asset_bundle.symbol,
        "benchmark": bench_bundle.symbol,
        "available": bool(study.get("available")),
        "data": {
            "asset": _meta(asset_bundle),
            "benchmark": _meta(bench_bundle),
            "alignedReturns": len(ra),
            "firstTimestamp": ts[0].isoformat() if ts else None,
        },
        "study": study,
        "requestedEvents": len(event_indices),
    }


async def bootstrap_analytics(values: list[float], *, seed: Optional[int] = None) -> dict:
    """Bootstrap CI over a user-supplied sample (e.g. paper P/L outcomes)."""
    return bootstrap_mean_ci(values, seed=seed)


async def rolling_beta_analytics(
    symbol: str,
    benchmark: Optional[str] = None,
    *,
    window: int = 60,
    lookback_days: Optional[int] = None,
) -> dict:
    """Standalone rolling-beta endpoint for the chart panel."""
    bench = (benchmark or "").strip().upper()
    lookback = lookback_days or quant_settings.quant_default_lookback_days
    asset_bundle = await fetch_prices(symbol, lookback_days=lookback)
    bench_bundle = await fetch_prices(bench, lookback_days=lookback) if bench else await fetch_benchmark(lookback_days=lookback)
    aligned = await fetch_aligned(asset_bundle.symbol, bench_bundle.symbol, lookback_days=lookback)
    ra = aligned.get("returnsA") or []
    rb = aligned.get("returnsB") or []
    result = rolling_beta(ra, rb, window=window) if ra and rb else {"available": False, "reason": aligned.get("reason") or "no aligned returns"}
    return {
        "symbol": asset_bundle.symbol,
        "benchmark": bench_bundle.symbol,
        "available": bool(result.get("available")),
        "data": {"asset": _meta(asset_bundle), "benchmark": _meta(bench_bundle)},
        "rolling": result,
    }


def config_snapshot() -> dict:
    """Publish the tunables so the UI can state the same thresholds the engine uses."""
    s = quant_settings
    return {
        "minObservations": s.quant_min_observations,
        "minRegressionObservations": s.quant_min_regression_observations,
        "minStationarityObservations": s.quant_min_stationarity_observations,
        "minEventStudySample": s.quant_min_event_study_sample,
        "significanceLevel": s.quant_significance_level,
        "adfAutolag": s.quant_adf_autolag,
        "hacMaxLags": s.quant_hac_maxlags,
        "varianceRatioPeriods": s.variance_ratio_periods,
        "hurstWindows": s.hurst_window_list,
        "confidenceLevels": s.confidence_levels,
        "ewmaLambda": s.quant_ewma_lambda,
        "eventEstimationWindow": s.quant_event_estimation_window,
        "eventGapWindow": s.quant_event_gap_window,
        "eventWindowOffsets": s.event_window_offsets,
        "bootstrapResamples": s.quant_bootstrap_resamples,
        "defaultLookbackDays": s.quant_default_lookback_days,
        "engines": {
            "statsmodels": True,
            "scipy": True,
            "numpy": True,
            "pandas": True,
        },
    }


def engine_available() -> bool:
    """True when the provider layer is bound (tests may run without it)."""
    return get_manager() is not None
