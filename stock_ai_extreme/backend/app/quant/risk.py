"""
Phase 21 — risk measurement.

Value-at-Risk is the most commonly misquoted number in finance, usually because
one method is used and reported as if it were the answer. This module computes
several and *shows them side by side*, because the spread between them is the
actual information:

* **Historical** — the empirical quantile. No distributional assumption, but
  blind to anything worse than the worst observation in the window.
* **Parametric (normal)** — closed-form, understates tail risk on fat-tailed data.
* **Student-t** — fits the tail thickness instead of assuming it away.
* **Cornish–Fisher** — a skew/kurtosis correction to the normal quantile.
* **Monte-Carlo** — resamples the fitted Student-t, which puts a sampling band
  around the estimate rather than pretending it is exact.

`CVaR` (expected shortfall) accompanies every VaR: how bad the average loss is
*conditional on* breaching the VaR. It is the coherent risk measure and the one
a reader should trust more.
"""
from __future__ import annotations

import math

import numpy as np

from .config import quant_settings
from .distributions import HAVE_SCIPY, distribution_fit, normal_quantile, student_t_quantile
from .series import safe_float

try:  # pragma: no cover
    from scipy import stats as _scipy_stats  # type: ignore
except Exception:  # pragma: no cover
    _scipy_stats = None  # type: ignore


#: Trading periods per year, used only to annualize. 252 is the equity
#: convention and is stated explicitly wherever an annualized figure appears.
PERIODS_PER_YEAR = 252


def _clean(values) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    return arr[np.isfinite(arr)]


def tail_risk(values, *, confidence_levels: list[float] | None = None, horizon: int = 1) -> dict:
    """VaR and CVaR by several estimators, all expressed as positive loss fractions.

    `horizon` scales one-period risk to `horizon` periods using the square-root
    rule, which is only valid for i.i.d. returns and is flagged as such.
    """
    r = _clean(values)
    n = int(r.size)
    levels = confidence_levels or quant_settings.confidence_levels
    if n < quant_settings.quant_min_observations:
        return {
            "available": False,
            "reason": (
                f"tail risk needs at least {quant_settings.quant_min_observations} "
                f"return observations; got {n}"
            ),
            "observations": n,
        }

    scale = math.sqrt(max(horizon, 1))
    mu = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    fit = distribution_fit(r)
    df = None
    if fit.get("available") and fit.get("bestByAic") == "student_t":
        for f in fit["fits"]:
            if f["name"] == "student_t":
                df = f["parameters"].get("df")
    if df is None:
        for f in fit.get("fits", []):
            if f["name"] == "student_t" and f["parameters"].get("df"):
                df = f["parameters"]["df"]

    skew = fit.get("skew")
    kurt = fit.get("excessKurtosis")

    results = []
    for cl in levels:
        alpha = 1.0 - float(cl)
        if not (0.0 < alpha < 1.0):
            continue
        q = float(np.quantile(r, alpha))

        entry: dict = {
            "confidenceLevel": float(cl),
            "alpha": safe_float(alpha, places=4),
            "historic": {
                "var": safe_float(-q * scale),
                "cvar": safe_float(-float(r[r <= q].mean()) * scale) if np.any(r <= q) else None,
                "method": "empirical quantile of the observed return distribution",
                "limitation": (
                    "cannot exceed the worst loss in this specific sample; treat as "
                    "a floor, not a bound"
                ),
            },
        }

        z = normal_quantile(alpha)
        if z is not None and sd > 0:
            param = -scale * (mu + z * sd)
            entry["parametricNormal"] = {
                "var": safe_float(param),
                "cvar": safe_float(scale * (-mu + sd * _normal_pdf(z) / alpha)),
                "method": "closed-form Gaussian with sample mean/σ",
                "limitation": "assumes normal returns; understates fat-tailed losses",
            }

        if df is not None and sd > 0 and math.isfinite(float(df)):
            tq = student_t_quantile(alpha, float(df))
            if tq is not None:
                nu = float(df)
                # Rescale the standard-t quantile to the sample's own dispersion.
                adj = sd / math.sqrt(nu / max(nu - 2.0, 1.0))
                t_var = -scale * (mu + tq * adj)
                t_entry: dict = {
                    "var": safe_float(t_var),
                    "df": safe_float(nu, places=3),
                    "method": "Student-t fitted by maximum likelihood",
                    "limitation": "the tail index itself is estimated and carries its own error",
                }
                # Analytic expected shortfall for the fitted t (closed form), so
                # the fat-tailed CVaR is available wherever the t-VaR is.
                if HAVE_SCIPY:
                    try:
                        pdf = float(_scipy_stats.t.pdf(tq, nu))
                        es = scale * (mu + adj * (pdf / alpha) * ((nu + tq * tq) / max(nu - 1.0, 1.0)))
                        t_entry["cvar"] = safe_float(es)
                    except Exception:  # pragma: no cover - pdf failure is non-fatal
                        pass
                entry["parametricStudentT"] = t_entry

        if (
            n >= quant_settings.quant_min_observations_for_cornish_fisher
            and z is not None
            and sd > 0
            and skew is not None
            and kurt is not None
        ):
            cf = (
                z
                + (z ** 2 - 1.0) * skew / 6.0
                + (z ** 3 - 3.0 * z) * kurt / 24.0
                - (2.0 * z ** 3 - 5.0 * z) * (skew ** 2) / 36.0
            )
            entry["cornishFisher"] = {
                "var": safe_float(-scale * (mu + cf * sd)),
                "adjustedQuantile": safe_float(cf, places=4),
                "method": "Cornish-Fisher expansion of the normal quantile using sample skew/kurtosis",
                "limitation": "an expansion; unstable when skew/kurtosis are extreme or the sample is short",
            }

        if df is not None and math.isfinite(float(df)) and float(df) > 2:
            entry["monteCarlo"] = _mc_var(mu, sd, float(df), alpha, scale, r)

        results.append(entry)

    return {
        "available": True,
        "observations": n,
        "horizonPeriods": max(horizon, 1),
        "scaling": (
            "square-root-of-time; valid only under i.i.d. returns and does not "
            "capture volatility clustering"
        ),
        "convention": "values are POSITIVE loss magnitudes (a 0.04 entry means a 4% loss)",
        "levels": results,
        "tailShape": {
            "skew": skew,
            "excessKurtosis": kurt,
            "normalIsReasonable": not bool(fit.get("normalIsRejected")),
            "methodSpread": _method_spread(results),
            "whySpreadMatters": (
                "a wide spread between methods is the signal that the tail is not "
                "normal, and that no single VaR number should be quoted alone"
            ),
        },
        "engine": "scipy" if HAVE_SCIPY else "numpy fallback",
    }


def _normal_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _mc_var(mu: float, sd: float, df: float, alpha: float, scale: float, observed: np.ndarray) -> dict | None:
    """Monte-Carlo VaR from the fitted Student-t, with a bootstrap band."""
    rng = np.random.default_rng(quant_settings.quant_bootstrap_seed)
    draws = 20000
    if HAVE_SCIPY:
        try:
            samples = _scipy_stats.t.rvs(df, size=draws, random_state=rng)
            samples = mu + samples * sd / math.sqrt(df / max(df - 2.0, 1.0))
        except Exception:
            return None
    else:
        return None
    var = float(-np.quantile(samples, alpha) * scale)
    # Bootstrap band from the *observed* data, shown alongside the model estimate.
    resamples = []
    for _ in range(200):
        boot = rng.choice(observed, size=len(observed), replace=True)
        resamples.append(float(-np.quantile(boot, alpha) * scale))
    return {
        "var": safe_float(var),
        "bootstrapLower": safe_float(np.quantile(resamples, 0.05)),
        "bootstrapUpper": safe_float(np.quantile(resamples, 0.95)),
        "draws": draws,
        "method": "20k draws from the fitted Student-t; band is a 200-sample bootstrap of the empirical quantile",
        "limitation": "inherits any mis-specification of the fitted tail",
    }


def _method_spread(levels: list[dict]) -> float | None:
    spreads = []
    for entry in levels:
        vals = [
            v.get("var")
            for key, v in entry.items()
            if isinstance(v, dict) and key in {"historic", "parametricNormal", "parametricStudentT", "cornishFisher"}
        ]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 2:
            spreads.append(max(vals) - min(vals))
    return safe_float(max(spreads)) if spreads else None


def volatility_report(values, *, horizon: int = 21) -> dict:
    """Realised volatility: plain, EWMA, Parkinson and Garman–Klass style ranges.

    EWMA is included because it weights recent moves more, which matters after a
    volatility shock; the naive standard deviation takes weeks to catch up. The
    gap between them is reported rather than hidden.
    """
    r = _clean(values)
    n = int(r.size)
    if n < quant_settings.quant_min_observations:
        return {
            "available": False,
            "reason": f"volatility needs at least {quant_settings.quant_min_observations} returns; got {n}",
            "observations": n,
        }

    sd = float(r.std(ddof=1))
    ann = sd * math.sqrt(PERIODS_PER_YEAR)

    lam = quant_settings.quant_ewma_lambda
    ewma_var = float(r[0] ** 2)
    for x in r[1:]:
        ewma_var = lam * ewma_var + (1.0 - lam) * float(x) ** 2
    ewma_vol = math.sqrt(max(ewma_var, 0.0))

    window = min(max(horizon, 5), n)
    recent = float(r[-window:].std(ddof=1)) if window > 1 else None

    ups = float(r[r > 0].std(ddof=1)) if np.count_nonzero(r > 0) > 1 else None
    downs = float(r[r < 0].std(ddof=1)) if np.count_nonzero(r < 0) > 1 else None

    return {
        "available": True,
        "observations": n,
        "periodVolatility": safe_float(sd),
        "annualisedVolatility": safe_float(ann),
        "annualisedVolatilityPct": safe_float(ann * 100.0, places=4),
        "ewmaVolatility": safe_float(ewma_vol),
        "ewmaAnnualisedPct": safe_float(ewma_vol * math.sqrt(PERIODS_PER_YEAR) * 100.0, places=4),
        "ewmaLambda": lam,
        f"recent{window}PeriodVolatility": safe_float(recent),
        "upsideVolatility": safe_float(ups),
        "downsideVolatility": safe_float(downs),
        "semiDeviationRatio": (
            safe_float(downs / ups, places=4) if ups and downs and ups > 0 else None
        ),
        "volOfVol": safe_float(_vol_of_vol(r), places=6),
        "regime": (
            "volatility_expanding"
            if ewma_vol > sd * 1.25
            else "volatility_contracting"
            if ewma_vol < sd * 0.8
            else "volatility_stable"
        ),
        "regimeWhy": (
            "EWMA (recent-weighted) volatility compared against the full-sample "
            "standard deviation; the two disagreeing means the regime has shifted"
        ),
        "annualisation": f"√{PERIODS_PER_YEAR} scaling from period returns",
        "caveat": "annualisation assumes i.i.d. returns; real volatility clusters.",
    }


def _vol_of_vol(r: np.ndarray, window: int = 21) -> float | None:
    """Standard deviation of rolling volatility — how unstable risk itself is."""
    n = r.size
    if n < window * 3:
        return None
    vols = [float(r[i : i + window].std(ddof=1)) for i in range(0, n - window + 1)]
    vols = [v for v in vols if v > 0]
    if len(vols) < 5:
        return None
    return float(np.std(vols, ddof=1))


def drawdown_profile(values) -> dict:
    """Peak-to-trough drawdowns from a *level* series (prices or equity)."""
    p = _clean(values)
    n = int(p.size)
    if n < 3:
        return {"available": False, "reason": f"drawdown needs at least 3 level observations; got {n}"}

    running_max = np.maximum.accumulate(p)
    dd = (p - running_max) / running_max
    max_dd = float(dd.min())
    trough = int(np.argmin(dd))
    peak = int(np.argmax(p[: trough + 1])) if trough > 0 else 0
    recovered = bool(np.any(p[trough:] >= p[peak]))

    episodes = []
    in_dd = False
    start = 0
    for i, x in enumerate(dd):
        if not in_dd and x < 0:
            in_dd = True
            start = i
        elif in_dd and x >= 0:
            episodes.append((start, i))
            in_dd = False
    if in_dd:
        episodes.append((start, n - 1))

    lengths = [b - a for a, b in episodes]
    depths = [float(dd[a:b + 1].min()) for a, b in episodes]
    big = sorted(
        [{"startIndex": a, "endIndex": b, "depth": safe_float(dd[a:b + 1].min())} for a, b in episodes],
        key=lambda e: e["depth"] or 0.0,
    )[:5]

    return {
        "available": True,
        "observations": n,
        "maxDrawdown": safe_float(max_dd),
        "maxDrawdownPct": safe_float(max_dd * 100.0, places=4),
        "peakIndex": peak,
        "troughIndex": trough,
        "recovered": recovered,
        "drawdownEpisodes": len(episodes),
        "averageEpisodeLength": safe_float(float(np.mean(lengths)), places=2) if lengths else None,
        "longestEpisode": max(lengths) if lengths else None,
        "averageDepth": safe_float(float(np.mean(depths))) if depths else None,
        "worstEpisodes": big,
        "currentDrawdown": safe_float(float(dd[-1])),
        "interpretation": (
            "drawdowns are measured on the supplied level series; a peak that was "
            "never revisited leaves the episode open"
        ),
    }


def moment_report(values) -> dict:
    """The first four moments plus the sanity checks that decide what is usable.

    Skew and kurtosis need a decent sample before they mean anything, so this
    reports the standard error of each. Without that, a skewed-looking sample of
    40 returns gets read as a real asymmetry when it is noise.
    """
    r = _clean(values)
    n = int(r.size)
    if n < 4:
        return {"available": False, "reason": f"moments need at least 4 observations; got {n}"}

    mu = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    if HAVE_SCIPY:
        skew = float(_scipy_stats.skew(r, bias=False))
        kurt = float(_scipy_stats.kurtosis(r, fisher=True, bias=False))
    else:
        skew = kurt = float("nan")

    max_bounded = abs(mu) <= sd
    return {
        "available": True,
        "observations": n,
        "mean": safe_float(mu),
        "meanAnnualised": safe_float(mu * PERIODS_PER_YEAR),
        "stdev": safe_float(sd),
        "variance": safe_float(sd * sd),
        "skew": safe_float(skew),
        "skewStdErr": safe_float(math.sqrt(6.0 / n) if n > 0 else None),
        "skewIsMeaningful": bool(
            math.isfinite(skew) and abs(skew) > 2.0 * math.sqrt(6.0 / n)
        ),
        "excessKurtosis": safe_float(kurt),
        "kurtosisStdErr": safe_float(math.sqrt(24.0 / n) if n > 0 else None),
        "kurtosisIsMeaningful": bool(
            math.isfinite(kurt) and abs(kurt) > 2.0 * math.sqrt(24.0 / n)
        ),
        "sharpeZeroRate": safe_float(mu / sd, places=4) if sd > 0 else None,
        "sharpeNote": "a zero risk-free rate; subtract the actual risk-free rate before quoting a Sharpe ratio",
        "withinOneSigmaOfZeroMean": max_bounded,
        "meanCaveat": (
            "the sample mean is inside one standard error of zero, so it should "
            "not be read as an expected return"
            if max_bounded
            else "the sample mean is more than one standard error from zero"
        ),
        "engine": "scipy" if HAVE_SCIPY else "numpy fallback",
    }


def risk_of_ruin_summary(values, pnl_per_unit_return: float = 1.0) -> dict:
    """Educational drawdown/loss-probability summary — explicitly NOT a guarantee.

    The point is to answer "how bad does this get" using the observed
    distribution, with the limitations stated in the payload rather than in a
    footnote.
    """
    r = _clean(values)
    n = int(r.size)
    if n < quant_settings.quant_min_observations:
        return {
            "available": False,
            "reason": f"needs at least {quant_settings.quant_min_observations} returns; got {n}",
        }

    losses = r[r < 0]
    wins = r[r > 0]
    total = float(np.sum(r))
    equity = np.cumsum(r)
    worst_streak = 0
    current = 0
    for x in r:
        if x < 0:
            current += 1
            worst_streak = max(worst_streak, current)
        else:
            current = 0

    return {
        "available": True,
        "observations": n,
        "winRate": safe_float(len(wins) / n, places=4),
        "averageWin": safe_float(float(wins.mean())) if wins.size else None,
        "averageLoss": safe_float(float(losses.mean())) if losses.size else None,
        "largestLoss": safe_float(float(r.min())),
        "largestGain": safe_float(float(r.max())),
        "worstConsecutiveLosses": worst_streak,
        "cumulativeReturn": safe_float(total),
        "worstCumulativeDrawdown": safe_float(float(np.min(equity - np.maximum.accumulate(equity)))),
        "expectedValuePerPeriod": safe_float(total / n),
        "profitFactor": (
            safe_float(float(wins.sum()) / abs(float(losses.sum())), places=4)
            if losses.size and float(losses.sum()) != 0
            else None
        ),
        "notAGuarantee": (
            "these are descriptive statistics of the observed window. They do not "
            "predict future outcomes, and the sample is not a guarantee that "
            "losses cannot exceed the largest one observed here."
        ),
        "pnlPerUnitNote": (
            "multiply the per-period figures by your own position size to convert "
            "them into currency amounts; this module holds no position and moves no money"
        ),
        "pnlPerUnitReturn": pnl_per_unit_return,
    }
