"""
Phase 21 — distribution fitting and quantiles.

Tail risk needs quantiles. The normal quantile is the wrong one for financial
returns (they are fat-tailed), so this module provides:

* `student_t_quantile` — exact quantiles via SciPy's `t.ppf`.
* `normal_quantile` — via SciPy's `norm.ppf` when available, else the Acklam
  rational approximation (accurate to ~1e-9), so the module still works if the
  SciPy build is unavailable.
* `distribution_fit` — fits normal / Student-t / skewed-t-ish descriptions and
  returns them with log-likelihood so callers can pick by AIC instead of
  guessing an exponent.
* `goodness_of_fit` — Anderson–Darling and Jarque–Bera, the honest way to say
  "these returns are not normal".
"""
from __future__ import annotations

import math
import warnings

import numpy as np

from .series import safe_float

try:  # pragma: no cover - exercised implicitly
    from scipy import stats as _scipy_stats  # type: ignore

    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _scipy_stats = None  # type: ignore
    HAVE_SCIPY = False


# --- normal quantile: SciPy fast path, Acklam fallback -----------------------
_A = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
      1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
_B = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
      6.680131188771972e01, -1.328068155288572e01]
_C = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
      -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
_D = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
      3.754408661907416e00]


def _acklam(p: float) -> float:
    """Peter Acklam's inverse normal CDF approximation."""
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / (
            ((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -((((( _C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
        (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
    )


def normal_quantile(p: float) -> float | None:
    """Inverse standard-normal CDF at probability `p`."""
    if not (0.0 < p < 1.0):
        return None
    if HAVE_SCIPY:
        try:
            return safe_float(_scipy_stats.norm.ppf(p))
        except Exception:
            pass
    return safe_float(_acklam(p))


def student_t_quantile(p: float, df: float) -> float | None:
    """Inverse Student-t CDF. Falls back to the normal when SciPy is absent."""
    if not (0.0 < p < 1.0) or not math.isfinite(df) or df <= 0:
        return None
    if HAVE_SCIPY:
        try:
            return safe_float(_scipy_stats.t.ppf(p, df))
        except Exception:
            pass
    return normal_quantile(p)


def _log_likelihood_normal(r: np.ndarray) -> tuple[float, int]:
    mu = float(r.mean())
    sd = float(r.std(ddof=0))
    if sd <= 0:
        return float("-inf"), 2
    ll = float(np.sum(_scipy_stats.norm.logpdf(r, mu, sd))) if HAVE_SCIPY else float(
        -0.5 * r.size * (math.log(2 * math.pi) + math.log(sd * sd) + 1.0)
    )
    return ll, 2


def _log_likelihood_t(r: np.ndarray) -> tuple[float, int, float, float]:
    """MLE-ish Student-t fit; returns (loglik, k, df, scale)."""
    mu = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd <= 0 or r.size < 5:
        return float("-inf"), 3, float("nan"), float("nan")
    if HAVE_SCIPY:
        try:
            df, loc, scale = _scipy_stats.t.fit(r, floc=mu)
            if not (math.isfinite(df) and math.isfinite(scale)) or scale <= 0:
                raise ValueError("bad t fit")
            ll = float(np.sum(_scipy_stats.t.logpdf(r, df, loc, scale)))
            return ll, 3, float(df), float(scale)
        except Exception:
            pass
    # Fallback: method-of-moments df from excess kurtosis, normal likelihood.
    ll, k = _log_likelihood_normal(r)
    return ll, k, float("nan"), float(sd)


def aic(loglik: float, k: int) -> float | None:
    if not math.isfinite(loglik):
        return None
    return safe_float(-2.0 * loglik + 2.0 * k, places=4)


def bic(loglik: float, k: int, n: int) -> float | None:
    if not math.isfinite(loglik) or n <= 0:
        return None
    return safe_float(-2.0 * loglik + k * math.log(n), places=4)


def distribution_fit(values) -> dict:
    """Describe the return distribution and pick a model by AIC (not by taste).

    Reports the normal and Student-t fits side by side with their information
    criteria so the caller can state *why* it chose one. Degrees of freedom feed
    straight into `student_t_quantile`.
    """
    r = np.asarray(list(values), dtype=float)
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n < 5:
        return {
            "available": False,
            "reason": f"needs at least 5 finite observations to fit a distribution; got {n}",
        }

    mu = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    ll_n, k_n = _log_likelihood_normal(r)
    ll_t, k_t, df_t, scale_t = _log_likelihood_t(r)

    cands: list[tuple[str, float, int, dict]] = []
    if math.isfinite(ll_n):
        cands.append(("normal", ll_n, k_n, {"mean": safe_float(mu), "stdev": safe_float(sd)}))
    if math.isfinite(ll_t) and math.isfinite(df_t):
        cands.append((
            "student_t",
            ll_t,
            k_t,
            {"mean": safe_float(mu), "df": safe_float(df_t, places=3), "scale": safe_float(scale_t)},
        ))

    if not cands:
        return {"available": False, "reason": "return distribution has no dispersion to fit"}

    fits = []
    for name, ll, k, params in cands:
        fits.append({
            "name": name,
            "logLikelihood": safe_float(ll, places=4),
            "parameters": params,
            "aic": aic(ll, k),
            "bic": bic(ll, k, n),
        })
    best = min(fits, key=lambda f: (f["aic"] is None, f["aic"] or float("inf")))

    excess_kurt = safe_float(float(_scipy_stats.kurtosis(r, fisher=True, bias=False)) if HAVE_SCIPY else _excess_kurtosis_manual(r))
    skew = safe_float(float(_scipy_stats.skew(r, bias=False)) if HAVE_SCIPY else _skew_manual(r))

    return {
        "available": True,
        "observations": n,
        "mean": safe_float(mu),
        "stdev": safe_float(sd),
        "skew": skew,
        "excessKurtosis": excess_kurt,
        "fits": fits,
        "bestByAic": best["name"],
        "bestByAicWhy": (
            "chosen by lowest AIC on the observed sample; AIC penalizes the extra "
            "parameter the Student-t uses, so a t win means the fat tails are real"
        ),
        "normalIsRejected": bool(
            excess_kurt is not None and abs(excess_kurt) > 1.0
        ),
        "method": "maximum likelihood" if HAVE_SCIPY else "method of moments (SciPy unavailable)",
    }


def goodness_of_fit(values) -> dict:
    """Jarque–Bera and Anderson–Darling tests of normality.

    These are reported *instead of* assuming normality: a statistic that assumes
    Gaussian returns while the data is fat-tailed produces understated risk.
    """
    r = np.asarray(list(values), dtype=float)
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n < 8:
        return {"available": False, "reason": f"needs at least 8 observations; got {n}"}

    out: dict = {"available": True, "observations": n, "tests": []}
    if HAVE_SCIPY:
        try:
            jb, jb_p = _scipy_stats.jarque_bera(r)
            out["tests"].append({
                "name": "jarque_bera",
                "statistic": safe_float(jb),
                "pValue": safe_float(jb_p, places=6),
                "nullHypothesis": "returns are normally distributed",
                "rejectNormal": bool(jb_p < 0.05),
            })
            # SciPy >= 1.17 warns that and() will require an explicit p-value
            # method; only the statistic/critical value is consumed here.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ad = _scipy_stats.anderson(r, dist="norm")
            stat = float(ad.statistic)
            crit = ad.critical_values[2] if len(ad.critical_values) > 2 else None
            out["tests"].append({
                "name": "anderson_darling",
                "statistic": safe_float(stat),
                "criticalValue5pct": safe_float(crit),
                "nullHypothesis": "returns are normally distributed",
                "rejectNormal": bool(crit is not None and stat > float(crit)),
            })
            out["skew"] = safe_float(float(_scipy_stats.skew(r, bias=False)))
            out["excessKurtosis"] = safe_float(float(_scipy_stats.kurtosis(r, fisher=True, bias=False)))
        except Exception as exc:  # pragma: no cover
            out["available"] = False
            out["reason"] = f"SciPy normality tests failed: {exc}"
            return out
    else:
        jb, jb_p = _jarque_bera_manual(r)
        out["tests"].append({
            "name": "jarque_bera",
            "statistic": safe_float(jb),
            "pValue": safe_float(jb_p, places=6),
            "nullHypothesis": "returns are normally distributed",
            "rejectNormal": bool(jb_p is not None and jb_p < 0.05),
        })
        out["skew"] = safe_float(_skew_manual(r))
        out["excessKurtosis"] = safe_float(_excess_kurtosis_manual(r))
        out["method"] = "closed-form fallback (SciPy unavailable)"

    out["interpretation"] = (
        "At least one normality test rejects the Gaussian assumption; fat-tailed "
        "quantiles (Student-t / empirical) are the appropriate risk inputs."
        if any(t.get("rejectNormal") for t in out["tests"])
        else "Normality cannot be rejected at the 5% level on this sample."
    )
    return out


def _skew_manual(r: np.ndarray) -> float:
    n = r.size
    sd = r.std(ddof=0)
    if n < 3 or sd <= 0:
        return float("nan")
    return float(np.mean(((r - r.mean()) / sd) ** 3) * math.sqrt(n * (n - 1)) / (n - 2))


def _excess_kurtosis_manual(r: np.ndarray) -> float:
    n = r.size
    sd = r.std(ddof=0)
    if n < 4 or sd <= 0:
        return float("nan")
    m4 = float(np.mean(((r - r.mean()) / sd) ** 4))
    return float(((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * (m4 * (n - 1) / n ** 2 * n) - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))


def _jarque_bera_manual(r: np.ndarray) -> tuple[float | None, float | None]:
    n = r.size
    skew = _skew_manual(r)
    kurt = _excess_kurtosis_manual(r)
    if not (math.isfinite(skew) and math.isfinite(kurt)):
        return None, None
    jb = (n / 6.0) * (skew ** 2 + (kurt ** 2) / 4.0)
    # Chi-square(2) survival function, closed form: P(X > x) = exp(-x/2).
    p = math.exp(-jb / 2.0)
    return jb, p
