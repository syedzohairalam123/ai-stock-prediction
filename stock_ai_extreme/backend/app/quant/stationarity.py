"""
Phase 21 — is the series even analysable?

Before a model is fitted to a price series, the honest first question is whether
that series is stationary. Fitting a mean-reversion model to a random walk, or a
regression to two co-trending series, produces confident nonsense — the classic
spurious-regression trap. This module answers the question three ways, because
no single test is authoritative:

* **ADF** (`statsmodels.tsa.stattools.adfuller`) — null is *a unit root exists*.
* **KPSS** (`statsmodels.tsa.stattools.kpss`) — null is *the series is
  stationary*. ADF and KPSS have opposite nulls; agreeing tests are much more
  informative than one alone, and disagreement is itself a useful signal.
* **Lo–MacKinlay variance ratio** — tests whether variance scales linearly with
  horizon. VR > 1 is trending/momentum, VR < 1 is mean-reverting.
* **Hurst exponent** (rescaled range) — the same question as a single number,
  and the input that decides whether the forecast layer should trust a
  directional model at all.

`statsmodels` is imported defensively. Without it the variance-ratio and Hurst
tests still run (pure NumPy), and the ADF/KPSS blocks report themselves as
unavailable with a reason rather than guessing.
"""
from __future__ import annotations

import math
import warnings

import numpy as np

from .config import quant_settings
from .series import safe_float

try:  # pragma: no cover
    from statsmodels.tsa.stattools import adfuller as _adfuller  # type: ignore
    from statsmodels.tsa.stattools import kpss as _kpss  # type: ignore

    HAVE_STATSMODELS = True
except Exception:  # pragma: no cover
    _adfuller = None  # type: ignore
    _kpss = None  # type: ignore
    HAVE_STATSMODELS = False


def _autolag_value() -> str | int | None:
    setting = quant_settings.quant_adf_autolag
    if setting == "none":
        return None
    return setting


def adf_test(values, *, maxlags: int | None = None) -> dict:
    """Augmented Dickey–Fuller. H0: the series has a unit root (non-stationary)."""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    if n < quant_settings.quant_min_stationarity_observations:
        return {
            "available": False,
            "reason": (
                f"ADF needs at least {quant_settings.quant_min_stationarity_observations} "
                f"observations; got {n}"
            ),
        }
    if not HAVE_STATSMODELS:
        return {
            "available": False,
            "reason": "statsmodels is not installed, so the ADF test cannot be run",
            "install": "pip install statsmodels",
        }
    if float(np.std(arr, ddof=1)) == 0.0:
        return {"available": False, "reason": "series has zero variance; ADF is undefined"}

    try:
        lag_kwargs: dict = {}
        autolag = _autolag_value()
        if maxlags is not None:
            lag_kwargs["maxlag"] = int(maxlags)
        if autolag is None:
            lag_kwargs["autolag"] = None
        else:
            lag_kwargs["autolag"] = autolag
        # statsmodels >= 0.14 emits FutureWarnings about its upcoming result
        # objects and KPSS interpolates p-values at the table edges; both are
        # expected here and would otherwise pollute every analytics response.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stat, pvalue, used_lag, nobs, crit, icbest = _adfuller(arr, **lag_kwargs)
    except Exception as exc:  # pragma: no cover
        return {"available": False, "reason": f"ADF failed: {exc}"}

    return {
        "available": True,
        "test": "augmented_dickey_fuller",
        "statistic": safe_float(stat),
        "pValue": safe_float(pvalue, places=6),
        "usedLag": int(used_lag),
        "observations": int(nobs),
        "criticalValues": {k: safe_float(v) for k, v in (crit or {}).items()},
        "nullHypothesis": "series has a unit root (non-stationary)",
        "rejectNull": bool(pvalue < quant_settings.quant_significance_level),
        "conclusion": (
            "stationary at the "
            f"{int((1 - quant_settings.quant_significance_level) * 100)}% confidence level"
            if pvalue < quant_settings.quant_significance_level
            else "cannot reject a unit root (treat as non-stationary)"
        ),
        "autolag": autolag or "fixed",
    }


def kpss_test(values, *, regression: str = "c") -> dict:
    """KPSS. H0: the series *is* stationary (the opposite null to ADF)."""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    if n < quant_settings.quant_min_stationarity_observations:
        return {
            "available": False,
            "reason": (
                f"KPSS needs at least {quant_settings.quant_min_stationarity_observations} "
                f"observations; got {n}"
            ),
        }
    if not HAVE_STATSMODELS:
        return {
            "available": False,
            "reason": "statsmodels is not installed, so the KPSS test cannot be run",
            "install": "pip install statsmodels",
        }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stat, pvalue, lags, crit = _kpss(arr, regression=regression)
    except Exception as exc:  # pragma: no cover
        return {"available": False, "reason": f"KPSS failed: {exc}"}

    pv = safe_float(pvalue, places=6)
    return {
        "available": True,
        "test": "kpss",
        "statistic": safe_float(stat),
        "pValue": pv,
        "lags": int(lags) if lags is not None and math.isfinite(float(lags)) else None,
        "criticalValues": {"10%": safe_float(crit.get("10%")), "5%": safe_float(crit.get("5%")), "2.5%": safe_float(crit.get("2.5%")), "1%": safe_float(crit.get("1%"))},
        "nullHypothesis": "series is stationary (level or trend)",
        "rejectNull": bool(pv is not None and pv < quant_settings.quant_significance_level),
        "conclusion": (
            "stationarity rejected"
            if pv is not None and pv < quant_settings.quant_significance_level
            else "stationarity not rejected"
        ),
    }


def variance_ratio_test(values, *, periods: list[int] | None = None, use_log: bool = True) -> dict:
    """Lo–MacKinlay variance-ratio test with heteroskedasticity-robust variance.

    Under a random walk the variance of *q*-period returns is exactly *q* times
    the variance of one-period returns, so VR(q) = 1. VR > 1 means returns are
    positively autocorrelated (trending); VR < 1 means mean reversion.
    Implemented directly in NumPy so it works without statsmodels.
    """
    from .series import log_returns, simple_returns  # local import avoids a cycle

    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    fn = log_returns if use_log else simple_returns
    r = np.asarray(fn(arr), dtype=float)
    n = int(r.size)
    qs = periods or quant_settings.variance_ratio_periods
    if n < 20:
        return {"available": False, "reason": f"variance-ratio test needs at least 20 returns; got {n}"}

    mu = float(r.mean())
    var1 = float(np.sum((r - mu) ** 2) / (n - 1))
    if var1 <= 0.0:
        return {"available": False, "reason": "one-period variance is zero; ratio is undefined"}

    results = []
    for q in qs:
        q = int(q)
        if q < 2 or q >= n // 2:
            continue
        # Overlapping q-period returns.
        sums = np.convolve(r, np.ones(q), mode="valid")
        m = q * (n - q + 1) * (1.0 - q / n)
        if m <= 0:
            continue
        varq = float(np.sum((sums - q * mu) ** 2) / m)
        vr = varq / (q * var1)

        # Heteroskedasticity-robust standard error (Lo-MacKinlay z2 statistic).
        delta = 0.0
        for j in range(1, q):
            num = float(np.sum(((r[j:] - mu) ** 2) * ((r[:-j] - mu) ** 2)))
            den = float(np.sum((r - mu) ** 2)) ** 2
            dj = num / den if den > 0 else 0.0
            delta += ((2.0 * (q - j) / q) ** 2) * dj
        z = (vr - 1.0) / math.sqrt(delta) if delta > 0 else None
        p = None
        if z is not None and math.isfinite(z):
            p = safe_float(2.0 * (1.0 - _normal_cdf(abs(z))), places=6)

        if vr >= quant_settings.quant_trending_threshold:
            reading = "trending"
        elif vr <= quant_settings.quant_mean_reverting_threshold:
            reading = "mean_reverting"
        else:
            reading = "random_walk_like"
        results.append({
            "period": q,
            "varianceRatio": safe_float(vr, places=4),
            "zStatistic": safe_float(z, places=4),
            "pValue": p,
            "reading": reading,
            "significant": bool(p is not None and p < quant_settings.quant_significance_level),
        })

    if not results:
        return {"available": False, "reason": "no testable periods fit inside the available sample"}

    return {
        "available": True,
        "test": "lo_mackinlay_variance_ratio",
        "observations": n,
        "results": results,
        "vetoThresholds": {
            "trendingAtOrAbove": quant_settings.quant_trending_threshold,
            "meanRevertingAtOrBelow": quant_settings.quant_mean_reverting_threshold,
        },
        "interpretation": (
            "VR(q)=1 is a pure random walk; above 1 returns trend, below 1 they "
            "mean-revert. Only the 'significant' flag accounts for estimation error."
        ),
    }


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def hurst_exponent(values, *, windows: list[int] | None = None, use_log: bool = True) -> dict:
    """Hurst exponent by rescaled range (R/S) analysis, log-log OLS fitted.

    H ≈ 0.5 random walk · H > 0.5 persistent/trending · H < 0.5 mean-reverting.
    Windows whose R/S is undefined (zero range) are skipped rather than
    substituted, and the fit reports R² so a meaningless slope is visible.
    """
    from .series import log_returns, simple_returns

    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    fn = log_returns if use_log else simple_returns
    r = np.asarray(fn(arr), dtype=float)
    n = int(r.size)
    wins = [w for w in (windows or quant_settings.hurst_window_list) if 8 <= w <= n // 2]
    if not wins:
        return {
            "available": False,
            "reason": f"Hurst needs at least ~16 returns inside the sample; got {n}",
        }

    xs: list[float] = []
    ys: list[float] = []
    points: list[dict] = []
    for w in wins:
        segments = n // w
        if segments < 1:
            continue
        rs_values: list[float] = []
        for s in range(segments):
            seg = r[s * w : (s + 1) * w]
            seg_mean = float(seg.mean())
            dev = np.cumsum(seg - seg_mean)
            spread = float(dev.max() - dev.min())
            sd = float(seg.std(ddof=1))
            if sd > 0 and spread > 0:
                rs_values.append(spread / sd)
        if not rs_values:
            continue
        rs_mean = float(np.mean(rs_values))
        if rs_mean <= 0:
            continue
        xs.append(math.log(w))
        ys.append(math.log(rs_mean))
        points.append({"window": w, "rescaledRange": safe_float(rs_mean, places=4), "segments": len(rs_values)})

    if len(xs) < 2:
        return {"available": False, "reason": "not enough usable window sizes to fit a Hurst slope"}

    x = np.asarray(xs)
    y = np.asarray(ys)
    slope, intercept = np.polyfit(x, y, 1)
    yhat = slope * x + intercept
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(np.sum((y - yhat) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None

    h = safe_float(slope, places=4)
    if h is None:
        return {"available": False, "reason": "Hurst slope could not be estimated"}
    if h > 0.55:
        reading = "persistent_trending"
    elif h < 0.45:
        reading = "mean_reverting"
    else:
        reading = "random_walk_like"

    return {
        "available": True,
        "method": "rescaled_range_rs",
        "hurst": h,
        "rSquared": safe_float(r2, places=4),
        "reading": reading,
        "points": points,
        "interpretation": (
            "H≈0.5 is a random walk, >0.5 persistent, <0.5 mean-reverting; the "
            "R² tells you how well a straight line actually described the scaling."
        ),
    }


def regime_hint(values) -> dict:
    """Turn the tests above into one decision the forecast layer can act on.

    This is the point of the whole module: a model should be *selected* because
    the series was tested, not because it looked good in a backtest. Returns
    `preferredModel` plus the evidence behind it.
    """
    stats = stationarity_report(values, include_variance_ratio=True, include_hurst=True)
    vr = stats.get("varianceRatio", {})
    hurst = stats.get("hurst", {})
    levels_adf = stats.get("adf", {})
    returns_adf = stats.get("returnsAdf", {})

    vr_readings = {r["reading"] for r in vr.get("results", []) if r.get("significant")}
    h = hurst.get("hurst")

    if "trending" in vr_readings or (h is not None and h > 0.55):
        preferred = "directional_momentum"
        why = "variance ratio above 1 and/or Hurst > 0.55: moves persist, so a directional model is defensible"
    elif "mean_reverting" in vr_readings or (h is not None and h < 0.45):
        preferred = "mean_reversion"
        why = "variance ratio below 1 and/or Hurst < 0.45: moves fade, so a mean-reversion model is defensible"
    else:
        preferred = "random_walk"
        why = "no persistence or reversion detected; a directional forecast would be noise, prefer a driftless/wide-interval output"

    return {
        "preferredModel": preferred,
        "why": why,
        "levelStationary": bool(levels_adf.get("available") and levels_adf.get("rejectNull")),
        "returnsStationary": bool(returns_adf.get("available") and returns_adf.get("rejectNull")),
        "hurst": h,
        "significantVarianceRatios": sorted(vr_readings),
        "caveat": "statistical character is estimated from the observed window and can change regime",
    }


def stationarity_report(
    values,
    *,
    include_variance_ratio: bool = True,
    include_hurst: bool = True,
) -> dict:
    """Full stationarity picture: levels, first differences, VR, Hurst."""
    from .series import simple_returns

    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(arr.size)
    if n < quant_settings.quant_min_stationarity_observations:
        return {
            "available": False,
            "reason": (
                f"stationarity testing needs at least "
                f"{quant_settings.quant_min_stationarity_observations} observations; got {n}"
            ),
            "observations": n,
        }

    diffs = np.diff(arr)
    report: dict = {
        "available": True,
        "observations": n,
        "significanceLevel": quant_settings.quant_significance_level,
        "engine": "statsmodels" if HAVE_STATSMODELS else "numpy (statsmodels unavailable)",
        "levelsAdf": adf_test(arr),
        "returnsAdf": adf_test(diffs),
    }
    report["levelsKpss"] = kpss_test(arr)
    report["returnsKpss"] = kpss_test(diffs)

    if include_variance_ratio:
        # Variance ratios are computed on returns, so pass raw prices in and let
        # the function difference them.
        report["varianceRatio"] = variance_ratio_test(arr)
    if include_hurst:
        report["hurst"] = hurst_exponent(arr)

    report["verdict"] = _verdict(report)
    return report


def _verdict(report: dict) -> dict:
    levels_adf = report.get("levelsAdf", {})
    levels_kpss = report.get("levelsKpss", {})
    ret_adf = report.get("returnsAdf", {})

    adf_stationary = levels_adf.get("available") and levels_adf.get("rejectNull")
    kpss_stationary = levels_kpss.get("available") and not levels_kpss.get("rejectNull")

    if adf_stationary and kpss_stationary:
        headline = "levels_look_stationary"
        note = "both tests agree the level series is stationary"
    elif not adf_stationary and kpss_stationary is False and levels_kpss.get("available"):
        headline = "levels_non_stationary"
        note = "ADF cannot reject a unit root and KPSS rejects stationarity"
    elif adf_stationary and levels_kpss.get("available") and levels_kpss.get("rejectNull"):
        headline = "conflicting_evidence"
        note = "ADF rejects a unit root but KPSS rejects stationarity — likely trend-stationary or structurally broken; treat with caution"
    else:
        headline = "inconclusive"
        note = "tests do not clearly agree; do not fit a levels model without more evidence"

    return {
        "headline": headline,
        "note": note,
        "returnsStationary": bool(ret_adf.get("available") and ret_adf.get("rejectNull")),
        "guidance": (
            "Model first differences (returns), not levels."
            if headline in {"levels_non_stationary", "conflicting_evidence", "inconclusive"}
            else "Levels may be modelled directly, but re-test on a rolling window."
        ),
    }
