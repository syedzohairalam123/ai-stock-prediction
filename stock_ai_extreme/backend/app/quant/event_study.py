"""
Phase 21 — event studies done properly.

"Did this event move the price?" is a statistical question, and answering it by
eyeballing a 2% move is how noise gets published as a finding. The standard
method is an event study:

1. Fit a market model on a clean **estimation window** that ends before the
   event (with a gap, so the event's own volatility cannot leak into the fit).
2. Forecast what the asset *should* have done over the **event window**.
3. The difference is the **abnormal return**. Cumulate it to get the CAR.
4. Test whether the CAR is distinguishable from zero.

Step 4 is what this module adds over the existing implementation. The
**Patell (1976) standardized test** scales each event's abnormal return by its
own forecast standard error and then aggregates, which is far more powerful than
a naive t-test because it accounts for each event's estimation precision. A
**bootstrap** CI on the cross-sectional mean is reported alongside it, since
bootstrap inference does not assume normality of abnormal returns — which
financial returns are known not to satisfy.
"""
from __future__ import annotations

import math

import numpy as np

from .config import quant_settings
from .regression import hac_ols
from .series import safe_float

try:  # pragma: no cover
    from scipy import stats as _scipy_stats  # type: ignore

    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _scipy_stats = None  # type: ignore
    HAVE_SCIPY = False


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _two_sided_p(t: float) -> float | None:
    if not math.isfinite(t):
        return None
    if HAVE_SCIPY:
        try:
            return safe_float(float(2.0 * _scipy_stats.norm.sf(abs(t))), places=6)
        except Exception:
            pass
    return safe_float(2.0 * (1.0 - _normal_cdf(abs(t))), places=6)


def bootstrap_mean_ci(
    samples,
    *,
    resamples: int | None = None,
    seed: int | None = None,
    confidence: float = 0.95,
) -> dict:
    """Percentile bootstrap CI for the mean of an arbitrary sample.

    Used for abnormal returns because they are not normally distributed:
    a t-interval would be too narrow exactly when it matters most.
    """
    r = np.asarray(list(samples), dtype=float)
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n < 3:
        return {"available": False, "reason": f"bootstrap needs at least 3 observations; got {n}"}

    reps = resamples or quant_settings.quant_bootstrap_resamples
    rng = np.random.default_rng(seed if seed is not None else quant_settings.quant_bootstrap_seed)
    means = np.empty(reps, dtype=float)
    for i in range(reps):
        means[i] = r[rng.integers(0, n, n)].mean()

    alpha = (1.0 - confidence) / 2.0
    lo = float(np.quantile(means, alpha))
    hi = float(np.quantile(means, 1.0 - alpha))
    observed = float(r.mean())
    excludes_zero = (lo > 0 and hi > 0) or (lo < 0 and hi < 0)

    return {
        "available": True,
        "method": f"percentile bootstrap, {reps:,} resamples",
        "observations": n,
        "mean": safe_float(observed),
        "confidenceLevel": confidence,
        "ci": [safe_float(lo), safe_float(hi)],
        "bootstrapStdErr": safe_float(float(means.std(ddof=1))),
        "excludesZero": bool(excludes_zero),
        "pValueApprox": _bootstrap_p(means, observed),
        "interpretation": (
            "the interval excludes zero, so the mean effect is distinguishable "
            "from noise at this confidence level"
            if excludes_zero
            else "the interval contains zero; the mean effect is not distinguishable from noise on this sample"
        ),
        "seed": seed if seed is not None else quant_settings.quant_bootstrap_seed,
        "reproducibility": "the seed is fixed and reported so the interval can be reproduced exactly",
    }


def _bootstrap_p(means: np.ndarray, observed: float) -> float | None:
    """Two-sided bootstrap p-value relative to a zero-centred null."""
    if means.size == 0:
        return None
    centred = means - observed
    p = float(np.mean(np.abs(centred) >= abs(observed)))
    return safe_float(min(max(p, 1.0 / means.size), 1.0), places=6)


def patell_test(cars: list[float], forecast_stderrs: list[float]) -> dict:
    """Patell (1976) standardized cross-sectional test on cumulative abnormal returns.

    Each event's CAR is divided by its own forecast standard error, converting
    every event to a comparable unit (a standardized abnormal return). Under the
    null those are ~N(0,1), so their sum scales as √N — this is why the test is
    more powerful than a naive t-test when events have unequal precision.
    """
    n = min(len(cars), len(forecast_stderrs))
    if n < quant_settings.quant_min_event_study_sample:
        return {
            "available": False,
            "reason": (
                f"Patell test needs at least {quant_settings.quant_min_event_study_sample} "
                f"events; got {n}"
            ),
            "events": n,
        }

    sar: list[float] = []
    for i in range(n):
        car = cars[i]
        se = forecast_stderrs[i]
        if car is None or se is None or not math.isfinite(float(car)) or not math.isfinite(float(se)) or float(se) <= 0:
            continue
        sar.append(float(car) / float(se))

    m = len(sar)
    if m < quant_settings.quant_min_event_study_sample:
        return {
            "available": False,
            "reason": f"only {m} events had a usable forecast standard error",
            "events": n,
        }

    sarr = np.asarray(sar)
    z = float(sarr.sum()) / math.sqrt(m) if m > 1 else float(sarr.sum())
    p = _two_sided_p(z)
    mean_car = float(np.mean([c for c in cars[:n] if c is not None]))

    return {
        "available": True,
        "test": "patell_standardized_cross_sectional",
        "events": m,
        "meanStandardizedAbnormalReturn": safe_float(float(sarr.mean())),
        "zStatistic": safe_float(z, places=4),
        "pValue": p,
        "meanCar": safe_float(mean_car),
        "nullHypothesis": "the event had no effect (mean CAR = 0)",
        "significant": bool(p is not None and p < quant_settings.quant_significance_level),
        "conclusion": (
            "the cumulative abnormal return is statistically distinguishable from zero"
            if p is not None and p < quant_settings.quant_significance_level
            else "no statistically significant abnormal return was detected"
        ),
        "whyStandardize": (
            "events estimated on noisier windows carry larger forecast errors; "
            "standardizing stops a single imprecise event from dominating the average"
        ),
    }


def _market_model_expectation(
    estimation_returns: np.ndarray,
    market_returns: np.ndarray,
) -> dict | None:
    """Fit r_i = alpha + beta*r_m on the estimation window and return the fit stats.

    Returns the residual standard error and the market mean, which together give
    the forecast standard error of an abnormal return (the denominator of the
    Patell standardization).
    """
    if len(estimation_returns) < 20 or len(market_returns) < 20:
        return None
    fit = hac_ols(
        estimation_returns,
        market_returns,
        names=["market"],
        add_constant=True,
        minimum_observations=20,
    )
    if not fit.get("available"):
        return None
    alpha = beta = None
    for c in fit["coefficients"]:
        if c["name"] == "const":
            alpha = c["estimate"]
        elif c["name"] == "market":
            beta = c["estimate"]
    if alpha is None or beta is None:
        return None
    resid_se = fit.get("residualStdErr") or 0.0
    return {
        "alpha": alpha,
        "beta": beta,
        "residualStdErr": resid_se,
        "rSquared": fit.get("rSquared"),
        "estimationN": fit["observations"],
        "marketMean": float(np.mean(market_returns)),
    }


def abnormal_return_study(
    *,
    asset_series: list[float],
    market_series: list[float],
    event_indices: list[int],
    event_labels: list[str] | None = None,
    estimation_window: int | None = None,
    gap_window: int | None = None,
    offsets: list[int] | None = None,
    source: str = "unknown",
) -> dict:
    """Run a full event study across multiple events for one asset.

    `event_indices` index into `asset_series` (the same array `market_series` is
    aligned to), pinpointing the bar in which each event landed. For every event:

    * the market model is fitted on `estimation_window` bars ending `gap_window`
      bars *before* the event (so the event cannot contaminate its own baseline),
    * abnormal returns are computed across `offsets` bars,
    * the CAR is accumulated and its forecast standard error recorded.

    The aggregated result is then tested with Patell's standardized test and a
    bootstrap CI. Events whose estimation window does not fit are skipped and
    counted, never padded.
    """
    est_w = estimation_window or quant_settings.quant_event_estimation_window
    gap_w = gap_window if gap_window is not None else quant_settings.quant_event_gap_window
    offs = offsets or quant_settings.event_window_offsets

    a = np.asarray(list(asset_series), dtype=float)
    m = np.asarray(list(market_series), dtype=float)
    n = min(len(a), len(m))
    a, m = a[:n], m[:n]
    if n < est_w + gap_w + max(offs or [0]) + 5:
        return {
            "available": False,
            "reason": (
                f"an event study with a {est_w}-bar estimation window and offsets "
                f"{offs} needs at least {est_w + gap_w + max(offs or [0]) + 5} bars; got {n}"
            ),
            "observations": n,
        }
    if not event_indices:
        return {"available": False, "reason": "no event indices were supplied"}

    events = []
    skipped = 0
    for i, idx in enumerate(event_indices):
        idx = int(idx)
        label = event_labels[i] if event_labels and i < len(event_labels) else f"event_{i}"
        est_end = idx - gap_w
        est_start = est_end - est_w
        if est_start < 0 or est_end <= est_start:
            skipped += 1
            continue
        if idx + max(offs or [0]) >= n:
            skipped += 1
            continue

        fit = _market_model_expectation(a[est_start:est_end], m[est_start:est_end])
        if fit is None:
            skipped += 1
            continue

        alpha, beta = fit["alpha"], fit["beta"]
        # Forecast standard error of a single abnormal return.
        k = fit["estimationN"]
        var_ar = fit["residualStdErr"] ** 2 * (1.0 + 1.0 / k + ((m[idx] - fit["marketMean"]) ** 2) / max(k * float(np.var(m[est_start:est_end])), 1e-12))
        ar_stderr = math.sqrt(var_ar) if var_ar > 0 else None

        ars = []
        for off in offs:
            j = idx + off
            if j < 0 or j >= n:
                ars.append({"offset": off, "abnormalReturn": None, "actualReturn": None, "expectedReturn": None})
                continue
            expected = alpha + beta * m[j]
            abnormal = a[j] - expected
            ars.append({
                "offset": off,
                "abnormalReturn": safe_float(abnormal),
                "actualReturn": safe_float(a[j]),
                "expectedReturn": safe_float(expected),
            })

        car = float(np.nansum([x["abnormalReturn"] for x in ars if x["abnormalReturn"] is not None]))
        events.append({
            "label": label,
            "index": idx,
            "estimationStart": est_start,
            "estimationEnd": est_end,
            "alpha": fit["alpha"],
            "beta": fit["beta"],
            "rSquared": fit["rSquared"],
            "abnormalReturns": ars,
            "car": safe_float(car),
            "carForecastStdErr": safe_float(ar_stderr),
        })

    if not events:
        return {
            "available": False,
            "reason": f"none of {len(event_indices)} events had a full estimation window inside the data",
            "skipped": skipped,
        }

    cars = [e["car"] for e in events]
    stderrs = [e["carForecastStdErr"] for e in events]
    patell = patell_test(cars, stderrs)
    boot = bootstrap_mean_ci([c for c in cars if c is not None])

    mean_car = float(np.mean([c for c in cars if c is not None]))
    sd_car = float(np.std([c for c in cars if c is not None], ddof=1)) if len(cars) > 1 else None
    naive_t = mean_car / (sd_car / math.sqrt(len(cars))) if sd_car and sd_car > 0 and len(cars) > 1 else None

    return {
        "available": True,
        "method": "market-model event study with Patell standardized test",
        "source": source,
        "observations": n,
        "eventsAnalysed": len(events),
        "eventsSkipped": skipped,
        "estimationWindow": est_w,
        "gapWindow": gap_w,
        "eventWindow": offs,
        "events": events,
        "meanCar": safe_float(mean_car),
        "medianCar": safe_float(float(np.median([c for c in cars if c is not None]))),
        "carStdDev": safe_float(sd_car),
        "positiveShare": safe_float(float(np.mean([1.0 if c and c > 0 else 0.0 for c in cars])), places=4),
        "naiveTTest": {
            "tStat": safe_float(naive_t, places=4),
            "pValue": _two_sided_p(naive_t) if naive_t is not None else None,
            "note": "reported for contrast; it ignores each event's estimation precision",
        },
        "patell": patell,
        "bootstrap": boot,
        "significanceLevel": quant_settings.quant_significance_level,
        "caveat": (
            "abnormal returns are associations, not causal effects. Confounding "
            "events, thin trading and bid-ask bounce all inflate apparent impact."
        ),
    }
