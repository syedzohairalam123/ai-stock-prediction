"""
Phase 21 — regression with Newey–West (HAC) standard errors.

A beta is only useful if you know how precisely it was estimated. Financial
return regressions violate the OLS assumptions in a specific, predictable way:
residuals are heteroskedastic and autocorrelated (volatility clusters, thin
trading, overlapping windows). Under those conditions the textbook OLS standard
error is biased — usually *downward*, which makes an insignificant beta look
significant.

Newey–West corrects the variance-covariance matrix with a Bartlett kernel, so
the t-statistics this module returns are the ones you can actually quote. It
also reports the naive OLS errors next to the HAC ones, which makes the size of
the correction visible instead of hidden.
"""
from __future__ import annotations

import math

import numpy as np

from .config import quant_settings
from .series import safe_float

try:  # pragma: no cover
    from statsmodels.regression.linear_model import OLS as _SM_OLS  # type: ignore
    import statsmodels.api as _sm  # type: ignore

    HAVE_STATSMODELS = True
except Exception:  # pragma: no cover
    _SM_OLS = None  # type: ignore
    _sm = None  # type: ignore
    HAVE_STATSMODELS = False


def _newey_west_lags(n: int) -> int:
    """Newey–West (1994) automatic bandwidth: floor(4*(T/100)^(2/9))."""
    if quant_settings.quant_hac_maxlags is not None:
        return int(quant_settings.quant_hac_maxlags)
    return max(1, int(math.floor(4.0 * (max(n, 1) / 100.0) ** (2.0 / 9.0))))


def _design(y, x) -> tuple[np.ndarray, np.ndarray]:
    yy = np.asarray(list(y), dtype=float)
    xx = np.asarray(list(x), dtype=float)
    if xx.ndim == 1:
        xx = xx.reshape(-1, 1)
    n = min(len(yy), xx.shape[0])
    yy = yy[:n]
    xx = xx[:n]
    mask = np.isfinite(yy) & np.all(np.isfinite(xx), axis=1)
    return yy[mask], xx[mask]


def _ols_core(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    """OLS fit plus a hand-rolled Newey–West covariance estimator.

    Written out explicitly (rather than only delegating) because it makes the
    correction auditable and keeps the module functional without statsmodels.
    """
    n, k = X.shape
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.pinv(XtX)
    except np.linalg.LinAlgError:  # pragma: no cover
        return {"ok": False, "reason": "design matrix is singular"}
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof

    # --- naive (homoskedastic) covariance ---
    cov_ols = sigma2 * XtX_inv

    # --- Newey-West HAC covariance (Bartlett kernel) ---
    S = np.zeros((k, k))
    for t in range(n):
        xt = X[t].reshape(-1, 1)
        S += (resid[t] ** 2) * (xt @ xt.T)
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)  # Bartlett
        gamma = np.zeros((k, k))
        for t in range(lag, n):
            xt = X[t].reshape(-1, 1)
            xtl = X[t - lag].reshape(-1, 1)
            gamma += (resid[t] * resid[t - lag]) * (xt @ xtl.T)
        S += weight * (gamma + gamma.T)
    cov_hac = XtX_inv @ S @ XtX_inv * (n / dof)

    ss_tot = float(np.sum((y - y.mean()) ** 2))
    ss_res = float(resid @ resid)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    adj_r2 = None
    if r2 is not None and n > k:
        adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - k)

    return {
        "ok": True,
        "n": n,
        "k": k,
        "beta": beta,
        "resid": resid,
        "covOls": cov_ols,
        "covHac": cov_hac,
        "r2": r2,
        "adjR2": adj_r2,
        "sigma": math.sqrt(sigma2) if sigma2 > 0 else 0.0,
        "lags": lags,
    }


def _t_pvalue(t: float, dof: int) -> float | None:
    """Two-sided p-value for a t statistic, normal approximation for large dof."""
    if not math.isfinite(t):
        return None
    try:
        from scipy import stats as _st  # type: ignore

        return safe_float(float(2.0 * _st.t.sf(abs(t), max(dof, 1))), places=6)
    except Exception:
        # Normal approximation; accurate to ~1e-4 for dof > 30.
        return safe_float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0)))), places=6)


def hac_ols(
    y,
    x,
    *,
    names: list[str] | None = None,
    add_constant: bool = True,
    maxlags: int | None = None,
    minimum_observations: int | None = None,
) -> dict:
    """Ordinary least squares with Newey–West HAC standard errors.

    `y[i]` is the dependent variable and `x[i]` the regressor(s) for the same
    interval — callers must align them beforehand (`series.align_returns`).

    Returns coefficients with both standard errors, t-statistics, p-values and
    confidence intervals, plus diagnostics (R², Durbin–Watson) and the bandwidth
    actually used. Everything is JSON-safe or `None` with a stated reason.
    """
    yy, xx = _design(y, x)
    n = int(len(yy))
    floor = minimum_observations or quant_settings.quant_min_regression_observations

    if n < floor:
        return {
            "available": False,
            "reason": f"regression needs at least {floor} aligned observations; got {n}",
            "observations": n,
            "minimumObservations": floor,
        }

    k_features = 1 if xx.ndim == 1 else xx.shape[1]
    regressor_names = names or (
        ["const", "x"] if k_features == 1 and add_constant else [f"x{i+1}" for i in range(k_features)]
    )
    if add_constant:
        X = np.column_stack([np.ones(n), xx])
        if names is None:
            regressor_names = ["const"] + [f"x{i+1}" for i in range(k_features)]
        else:
            regressor_names = ["const"] + list(names)
    else:
        X = xx

    if X.shape[1] >= n:
        return {
            "available": False,
            "reason": f"{X.shape[1]} regressors vs {n} observations: not enough degrees of freedom",
            "observations": n,
        }

    # Guard against a constant regressor with zero variance (nothing to estimate)
    for j in range(1 if add_constant else 0, X.shape[1]):
        if float(np.std(X[:, j], ddof=0)) == 0.0:
            return {
                "available": False,
                "reason": f"regressor '{regressor_names[j]}' is constant and cannot be estimated",
                "observations": n,
            }

    lags = _newey_west_lags(n) if maxlags is None else int(maxlags)
    lags = max(0, min(lags, n - 2))
    core = _ols_core(yy, X, lags)
    if not core.get("ok"):
        return {"available": False, "reason": core.get("reason", "fit failed"), "observations": n}

    beta = core["beta"]
    dof = max(core["n"] - core["k"], 1)
    coeffs = []
    for i, name in enumerate(regressor_names):
        b = float(beta[i])
        se_hac = math.sqrt(float(core["covHac"][i, i])) if core["covHac"][i, i] > 0 else None
        se_ols = math.sqrt(float(core["covOls"][i, i])) if core["covOls"][i, i] > 0 else None
        t = b / se_hac if se_hac and se_hac > 0 else None
        p = _t_pvalue(t, dof) if t is not None else None
        ci_lo = ci_hi = None
        if se_hac and se_hac > 0:
            crit = 1.96  # 95% normal critical value
            ci_lo = safe_float(b - crit * se_hac)
            ci_hi = safe_float(b + crit * se_hac)
        coeffs.append({
            "name": name,
            "estimate": safe_float(b),
            "stdErrHac": safe_float(se_hac),
            "stdErrOls": safe_float(se_ols),
            "tStat": safe_float(t, places=4),
            "pValue": p,
            "ci95": [ci_lo, ci_hi],
            "significant": bool(p is not None and p < quant_settings.quant_significance_level),
        })

    resid = core["resid"]
    dw = None
    if len(resid) > 2:
        denom = float(np.sum(resid ** 2))
        if denom > 0:
            dw = safe_float(float(np.sum(np.diff(resid) ** 2)) / denom, places=4)

    return {
        "available": True,
        "method": "OLS with Newey-West (Bartlett) HAC standard errors",
        "observations": n,
        "regressors": X.shape[1],
        "degreesOfFreedom": dof,
        "hacLags": lags,
        "bandwidthRule": (
            "fixed override" if quant_settings.quant_hac_maxlags is not None
            else "Newey-West automatic: floor(4*(T/100)^(2/9))"
        ),
        "coefficients": coeffs,
        "rSquared": safe_float(core["r2"], places=4),
        "adjustedRSquared": safe_float(core["adjR2"], places=4),
        "residualStdErr": safe_float(core["sigma"]),
        "durbinWatson": dw,
        "autocorrelationNote": (
            "Durbin-Watson materially below 2 indicates positively autocorrelated "
            "residuals, which is exactly why the HAC errors are reported."
            if dw is not None and dw < 1.5
            else "residual autocorrelation looks moderate on this sample"
        ),
        "engine": "statsmodels-available" if HAVE_STATSMODELS else "numpy-only estimator",
    }


def hac_beta(asset_returns, market_returns, *, market_name: str = "market", minimum_observations: int | None = None) -> dict:
    """Market-model beta with HAC inference — the replacement for a naive ratio.

    A single-factor market model: `r_asset = alpha + beta * r_market + e`. The
    beta *is* the sensitivity, but the point of this function is that it also
    returns whether that sensitivity is distinguishable from zero and from one.
    """
    fit = hac_ols(
        asset_returns,
        market_returns,
        names=[market_name],
        add_constant=True,
        minimum_observations=minimum_observations,
    )
    if not fit.get("available"):
        return fit

    by_name = {c["name"]: c for c in fit["coefficients"]}
    beta = by_name.get(market_name, {})
    alpha = by_name.get("const", {})

    beta_est = beta.get("estimate")
    se = beta.get("stdErrHac")
    t_vs_one = None
    p_vs_one = None
    if beta_est is not None and se and se > 0:
        t_vs_one = (beta_est - 1.0) / se
        p_vs_one = _t_pvalue(t_vs_one, fit["degreesOfFreedom"])

    if beta_est is None:
        reading = "not_estimable"
    elif beta_est > 1.2:
        reading = "amplifies_market_moves"
    elif beta_est < 0.8 and beta_est >= 0:
        reading = "dampens_market_moves"
    elif beta_est < 0:
        reading = "moves_against_market"
    else:
        reading = "tracks_market"

    return {
        "available": True,
        "beta": beta_est,
        "betaStdErrHac": se,
        "betaCi95": beta.get("ci95"),
        "betaPValue": beta.get("pValue"),
        "betaSignificant": beta.get("significant"),
        "alpha": alpha.get("estimate"),
        "alphaPValue": alpha.get("pValue"),
        "rSquared": fit["rSquared"],
        "observations": fit["observations"],
        "hacLags": fit["hacLags"],
        "testBetaEqualsOne": {
            "tStat": safe_float(t_vs_one, places=4),
            "pValue": p_vs_one,
            "rejectTrueBetaIsOne": bool(p_vs_one is not None and p_vs_one < quant_settings.quant_significance_level),
            "why": (
                "beta = 1 means the asset moves one-for-one with the benchmark; "
                "rejecting it is what justifies calling the asset high- or low-beta"
            ),
        },
        "reading": reading,
        "interpretation": (
            f"beta {beta_est} estimated with HAC errors over {fit['observations']} "
            f"observations (R²={fit['rSquared']}); "
            + ("significant at the 5% level" if beta.get("significant") else "NOT statistically distinguishable from zero on this sample")
        ),
        "engine": fit["engine"],
    }


def rolling_beta(
    asset_returns,
    market_returns,
    *,
    window: int = 60,
    market_name: str = "market",
    minimum_observations: int | None = None,
) -> dict:
    """Rolling beta, so a change in sensitivity is visible rather than averaged away.

    Each window is fitted independently with HAC errors. Windows with too few
    observations are skipped, never interpolated.
    """
    a = np.asarray(list(asset_returns), dtype=float)
    m = np.asarray(list(market_returns), dtype=float)
    n = min(len(a), len(m))
    a, m = a[:n], m[:n]
    mask = np.isfinite(a) & np.isfinite(m)
    a, m = a[mask], m[mask]
    n = len(a)

    floor = minimum_observations or max(quant_settings.quant_min_regression_observations // 3, 20)
    if n < max(window, floor):
        return {
            "available": False,
            "reason": f"rolling beta needs at least {max(window, floor)} aligned observations; got {n}",
            "observations": n,
        }
    if window < 10:
        return {"available": False, "reason": "rolling window must be at least 10 observations"}

    points = []
    for end in range(window, n + 1):
        start = end - window
        fit = hac_beta(a[start:end], m[start:end], market_name=market_name, minimum_observations=floor)
        if not fit.get("available"):
            continue
        points.append({
            "index": end - 1,
            "beta": fit.get("beta"),
            "stdErr": fit.get("betaStdErrHac"),
            "lower": (fit.get("betaCi95") or [None, None])[0],
            "upper": (fit.get("betaCi95") or [None, None])[1],
            "rSquared": fit.get("rSquared"),
        })

    if len(points) < 2:
        return {"available": False, "reason": "no overlapping rolling windows produced a usable beta", "observations": n}

    betas = [p["beta"] for p in points if p["beta"] is not None]
    lo = min(betas) if betas else None
    hi = max(betas) if betas else None
    latest = points[-1]["beta"]
    first = points[0]["beta"]
    shift = None
    if latest is not None and first is not None:
        shift = safe_float(latest - first, places=4)

    return {
        "available": True,
        "window": window,
        "points": len(points),
        "observations": n,
        "series": points,
        "latest": latest,
        "min": safe_float(lo),
        "max": safe_float(hi),
        "rangeShift": shift,
        "reading": (
            "beta has moved outside the range it held at the start of the sample"
            if shift is not None and abs(shift) > 0.3
            else "beta is broadly stable across the sample"
        ),
    }
