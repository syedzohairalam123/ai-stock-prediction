"""
Phase 21 — modular quant analytics tests.

Coverage mirrors the package's contract:

  * series prep — non-finite/non-positive prices never survive; alignment on
    shared timestamps; insufficient-sample reasons
  * distributions — quantile engines agree with SciPy; AIC model selection;
    Jarque-Bera rejects fat tails
  * stationarity — ADF/KPSS verdicts, variance ratio on synthetic random walks
    vs mean-reverting processes, Hurst band, regime hints
  * regression — HAC standard errors against statsmodels' own Newey-West
    implementation; naive-vs-HAC ordering; rolling beta
  * risk — VaR/ES across estimators (t-tails make t-VaR exceed normal-VaR),
    drawdown profile, moments, risk-of-ruin summary
  * event study — Patell test on constructed abnormal returns; the minimum
    sample floor; bootstrap CI containing the true mean
  * service + routes end to end with the provider manager faked at its seam

No test anywhere contacts a real market-data provider.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.quant import series as qseries
from app.quant.config import quant_settings
from app.quant.data import fetch_prices
from app.quant.distributions import distribution_fit, goodness_of_fit, normal_quantile, student_t_quantile
from app.quant.event_study import abnormal_return_study, bootstrap_mean_ci, patell_test
from app.quant.regression import hac_beta, hac_ols, rolling_beta
from app.quant.risk import drawdown_profile, moment_report, risk_of_ruin_summary, tail_risk, volatility_report
from app.quant.stationarity import hurst_exponent, regime_hint, stationarity_report, variance_ratio_test


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #

def _gbm_prices(n: int = 300, seed: int = 11, drift: float = 0.0004, vol: float = 0.012) -> list[float]:
    rng = np.random.default_rng(seed)
    shocks = rng.normal(drift, vol, n)
    return [float(100.0 * float(np.prod(np.exp(shocks[: i + 1])))) for i in range(n)]


def _ou_prices(n: int = 300, seed: int = 13, kappa: float = 0.35) -> list[float]:
    """Mean-reverting Ornstein-Uhlenbeck level process around 100."""
    rng = np.random.default_rng(seed)
    level = 100.0
    out = []
    for _ in range(n):
        level = level + kappa * (100.0 - level) + rng.normal(0, 1.2)
        out.append(float(level))
    return out


def _frame(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=len(prices), freq="B")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [1_000_000.0] * len(prices),
        },
        index=idx,
    )


class FakeManager:
    """Provider-manager stub returning one deterministic real-shaped frame."""

    def __init__(self, prices: list[float]):
        self.prices = prices
        self.history_calls: list[tuple] = []

    async def history(self, ticker, start, end, interval="1d"):
        self.history_calls.append((ticker, start, end, interval))
        return _frame(self.prices), "yfinance", type("S", (), {"value": "LIVE"})()

    async def quote(self, ticker):
        raise AssertionError("quant analytics must not need live quotes")


@pytest.fixture()
def fake_manager():
    from app.quant import state as quant_state

    manager = FakeManager(_gbm_prices())
    quant_state.configure(manager)
    yield manager
    quant_state.reset()


# --------------------------------------------------------------------------- #
# Series preparation
# --------------------------------------------------------------------------- #

def test_to_float_series_drops_junk():
    out = qseries.to_float_series([1.5, None, "x", float("nan"), float("inf"), True, 2.5])
    assert out == [1.5, 2.5]


def test_log_returns_skip_nonpositive_prices():
    values = [100.0, -5.0, 101.0, 0.0, 102.0]
    r = qseries.log_returns(values)
    # Only consecutive positive pairs produce returns: 100→101, 101→102.
    assert len(r) == 2 and all(math.isfinite(x) for x in r)


def test_align_returns_uses_shared_timestamps():
    base = date(2026, 1, 1)
    a = {base + timedelta(days=i): 100.0 + i for i in range(10)}
    b = {base + timedelta(days=i): 50.0 + 2 * i for i in range(4, 12)}  # overlap days 4..9
    ra, rb, ts = qseries.align_returns(a, b)
    assert len(ra) == len(rb) == len(ts) == 5  # days 5..9 give 5 diffs
    assert ts[0] == base + timedelta(days=5)


def test_build_return_series_reports_dropped_prices():
    prices = [100.0, float("nan"), 101.0, -3.0, 102.0]
    rs = qseries.build_return_series(prices)
    assert rs.n == 2
    assert any("excluded" in w for w in rs.warnings)


# --------------------------------------------------------------------------- #
# Distributions
# --------------------------------------------------------------------------- #

def test_quantiles_match_scipy_reference():
    z = normal_quantile(0.05)
    t = student_t_quantile(0.05, 5)
    assert z is not None and abs(z - (-1.6449)) < 1e-3
    assert t is not None and t < z  # fat tails widen the left quantile


def test_distribution_fit_prefers_t_for_fat_tails():
    fat = (np.random.default_rng(4).standard_t(4, 800) * 0.01).tolist()
    fit = distribution_fit(fat)
    assert fit["available"]
    assert fit["bestByAic"] == "student_t"
    assert fit["normalIsRejected"]


def test_goodness_of_fit_flags_nonnormal():
    fat = (np.random.default_rng(5).standard_t(3, 500) * 0.01).tolist()
    gof = goodness_of_fit(fat)
    assert gof["available"]
    assert any(t["rejectNormal"] for t in gof["tests"])


# --------------------------------------------------------------------------- #
# Stationarity
# --------------------------------------------------------------------------- #

def test_stationarity_random_walk_vs_mean_reverting():
    rw = stationarity_report(_gbm_prices(300))
    ou = stationarity_report(_ou_prices(300))
    assert rw["available"] and ou["available"]
    # Random-walk levels: ADF should not reject a unit root.
    assert rw["levelsAdf"]["available"]
    assert rw["levelsAdf"]["rejectNull"] is False
    # OU levels: ADF should reject the unit root (stationary).
    assert ou["levelsAdf"]["rejectNull"] is True
    # The returns of both are stationary — first-differencing is the fix.
    assert rw["returnsAdf"]["rejectNull"] is True
    assert rw["verdict"]["headline"] in {"levels_non_stationary", "conflicting_evidence", "inconclusive"}


def test_variance_ratio_flags_mean_reversion_for_ou():
    ou_returns = qseries.log_returns(_ou_prices(400))
    vr = variance_ratio_test(_ou_prices(400))
    assert vr["available"]
    assert any(r["reading"] == "mean_reverting" for r in vr["results"])
    # Sanity: the returns themselves are finite numbers.
    assert all(math.isfinite(x) for x in ou_returns)


def test_hurst_exponent_in_random_walk_band():
    h = hurst_exponent(_gbm_prices(500, seed=21))
    assert h["available"]
    assert 0.3 < h["hurst"] < 0.75  # R/S on finite samples wanders around 0.5
    assert h["rSquared"] is not None


def test_regime_hint_names_a_model():
    hint = regime_hint(_gbm_prices(300))
    assert hint["preferredModel"] in {"directional_momentum", "mean_reversion", "random_walk"}
    assert hint["why"]


def test_stationarity_too_short_sample_reason():
    rep = stationarity_report([100.0, 101.0, 100.5])
    assert not rep["available"] and "at least" in rep["reason"]


# --------------------------------------------------------------------------- #
# Regression (HAC)
# --------------------------------------------------------------------------- #

def test_hac_ols_recovers_beta_and_reports_both_errors():
    rng = np.random.default_rng(31)
    m = rng.normal(0, 0.01, 260)
    a = 0.0002 + 1.4 * m + rng.normal(0, 0.004, 260)
    fit = hac_ols(a.tolist(), m.tolist(), names=["market"])
    assert fit["available"]
    beta = next(c for c in fit["coefficients"] if c["name"] == "market")
    assert abs(beta["estimate"] - 1.4) < 0.15
    assert beta["stdErrHac"] is not None and beta["stdErrHac"] > 0
    assert beta["stdErrOls"] is not None
    assert fit["hacLags"] >= 1
    assert fit["rSquared"] is not None and 0 < fit["rSquared"] <= 1


def test_hac_ols_matches_statsmodels_newey_west():
    import statsmodels.api as sm

    rng = np.random.default_rng(41)
    m = rng.normal(0, 0.012, 300)
    a = 0.0003 + 0.9 * m + rng.normal(0, 0.005, 300)
    fit = hac_ols(a.tolist(), m.tolist(), names=["market"], maxlags=10)
    X = sm.add_constant(m)
    res = sm.OLS(a, X).fit(cov_type="HAC", cov_kwds={"maxlags": 10, "use_correction": False})
    own = next(c for c in fit["coefficients"] if c["name"] == "market")
    assert abs(own["estimate"] - res.params[1]) < 1e-6  # pinv vs lstsq rounding
    assert abs(own["stdErrHac"] - res.bse[1]) / res.bse[1] < 0.05  # within 5%


def test_hac_ols_rejects_short_samples():
    fit = hac_ols([0.01, -0.02, 0.03], [0.01, 0.0, -0.01])
    assert not fit["available"] and "aligned observations" in fit["reason"]


def test_hac_beta_flags_insignificant_beta():
    rng = np.random.default_rng(51)
    m = rng.normal(0, 0.01, 240)
    a = rng.normal(0, 0.02, 240)  # independent of m
    fit = hac_beta(a.tolist(), m.tolist())
    assert fit["available"]
    assert fit["betaSignificant"] is False


def test_rolling_beta_tracks_sensitivity_shift():
    rng = np.random.default_rng(61)
    m = rng.normal(0, 0.01, 400)
    a = np.concatenate([0.3 * m[:200], 1.8 * m[200:]]) + rng.normal(0, 0.002, 400)
    rb = rolling_beta(a.tolist(), m.tolist(), window=100)
    assert rb["available"]
    assert rb["latest"] is not None and rb["latest"] > 1.0  # the high-beta regime
    assert rb["rangeShift"] is not None and rb["rangeShift"] > 0.5


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #

def test_tail_risk_t_widens_var_against_normal():
    fat = (np.random.default_rng(71).standard_t(4, 600) * 0.01).tolist()
    tr = tail_risk(fat)
    assert tr["available"]
    lv99 = next(l for l in tr["levels"] if l["confidenceLevel"] == 0.99)
    t_var = lv99["parametricStudentT"]["var"]
    n_var = lv99["parametricNormal"]["var"]
    h_var = lv99["historic"]["var"]
    # At the 99% level the fitted fat tail dominates: variance-matched t-VaR
    # exceeds the Gaussian VaR (standardized t_4 1% quantile 2.65σ vs 2.33σ).
    assert t_var > n_var
    assert h_var > 0 and lv99["historic"]["cvar"] >= h_var  # ES beyond VaR
    assert tr["tailShape"]["methodSpread"] is not None


def test_volatility_report_regime_and_annualisation():
    vol = volatility_report((np.random.default_rng(81).normal(0, 0.01, 300)).tolist())
    assert vol["available"]
    assert abs(vol["annualisedVolatilityPct"] - 0.01 * math.sqrt(252) * 100) < 0.6
    assert vol["regime"] in {"volatility_expanding", "volatility_contracting", "volatility_stable"}


def test_drawdown_profile_finds_worst_episode():
    prices = [100, 120, 90, 95, 60, 110, 130]
    dd = drawdown_profile(prices)
    assert dd["available"]
    assert dd["maxDrawdownPct"] == pytest.approx(-50.0, abs=0.01)  # 120 → 60
    assert dd["recovered"] is True  # 130 > 120


def test_moment_report_flags_small_sample_mean():
    r = (np.random.default_rng(91).normal(0.0001, 0.01, 60)).tolist()
    mr = moment_report(r)
    assert mr["available"]
    assert mr["skewStdErr"] is not None
    assert "not be read as an expected return" in mr["meanCaveat"]


def test_risk_of_ruin_is_descriptive_not_predictive():
    r = (np.random.default_rng(101).normal(0.0002, 0.01, 200)).tolist()
    rr = risk_of_ruin_summary(r)
    assert rr["available"]
    assert "not a guarantee" in rr["notAGuarantee"].lower() or "do not" in rr["notAGuarantee"].lower()


# --------------------------------------------------------------------------- #
# Event study
# --------------------------------------------------------------------------- #

def test_patell_test_detects_constructed_effect():
    rng = np.random.default_rng(111)
    cars = [0.03 + rng.normal(0, 0.005) for _ in range(12)]
    ses = [0.004] * 12
    p = patell_test(cars, ses)
    assert p["available"]
    assert p["significant"] is True
    assert p["zStatistic"] > 3


def test_patell_test_respects_minimum_sample():
    p = patell_test([0.01, 0.02, 0.03], [0.01, 0.01, 0.01])
    assert not p["available"] and "at least" in p["reason"]


def test_bootstrap_ci_contains_true_mean():
    boot = bootstrap_mean_ci((np.random.default_rng(121).normal(0.02, 0.01, 60)).tolist())
    assert boot["available"]
    lo, hi = boot["ci"]
    assert lo < 0.02 < hi
    assert boot["excludesZero"] is True


def test_event_study_full_pipeline():
    rng = np.random.default_rng(131)
    n = 300
    m = rng.normal(0, 0.008, n)
    a = 0.5 * m + rng.normal(0, 0.006, n)
    # Inject a genuine +3% abnormal jump at five event bars (Patell's floor).
    for idx in (60, 100, 140, 200, 260):
        a[idx] += 0.03
    study = abnormal_return_study(
        asset_series=a.tolist(),
        market_series=m.tolist(),
        event_indices=[60, 100, 140, 200, 260],
        estimation_window=50,
        gap_window=5,
        offsets=[0, 1],
    )
    assert study["available"]
    assert study["eventsAnalysed"] == 5
    assert study["meanCar"] > 0.02  # the injected effect dominates
    assert study["patell"]["available"] and study["patell"]["significant"]


def test_event_study_skips_unfittable_events():
    rng = np.random.default_rng(141)
    m = rng.normal(0, 0.008, 300)
    a = 0.5 * m + rng.normal(0, 0.006, 300)
    study = abnormal_return_study(
        asset_series=a.tolist(), market_series=m.tolist(),
        event_indices=[2, 299],  # one too early, one too late
        estimation_window=50, gap_window=5, offsets=[0, 1],
    )
    assert study["available"] is False or study["eventsSkipped"] >= 1


# --------------------------------------------------------------------------- #
# Data layer + service + routes (provider manager faked at the seam)
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_fetch_prices_coerces_real_frame(anyio_backend, fake_manager):
    bundle = await fetch_prices("AAPL", lookback_days=365)
    assert bundle.available
    assert bundle.observations == len(fake_manager.prices)
    assert bundle.source == "yfinance"
    assert bundle.highs and bundle.lows  # honest column extraction
    rs = bundle.return_series()
    assert rs.n == bundle.observations - 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_fetch_prices_reports_error_without_fabrication(anyio_backend):
    from app.quant import state as quant_state

    class Failing:
        async def history(self, *a, **k):
            raise RuntimeError("provider down")

    quant_state.configure(Failing())
    bundle = await fetch_prices("AAPL")
    quant_state.reset()
    assert not bundle.available and bundle.error and bundle.closes == []


def test_instrument_analytics_route(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/quant/instruments/AAPL/analytics")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["stationarity"]["available"]
    assert body["tailRisk"]["available"]
    assert body["regimeHint"]["preferredModel"]
    assert "not investment advice" in body["disclaimer"].lower() or "education" in body["disclaimer"].lower()


def test_beta_route(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/quant/instruments/AAPL/beta?benchmark=MSFT")
    assert r.status_code == 200
    body = r.json()
    assert body["benchmark"] == "MSFT"
    # Same fake series → beta ≈ 1, whatever the estimate's precision.
    if body["available"]:
        assert 0.5 < body["beta"]["beta"] < 1.5


def test_tail_risk_route_rejects_bad_ticker(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/quant/instruments/AA%20PL/tail-risk")
    assert r.status_code in {422, 400}


def test_bootstrap_route_rejects_short_payload(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/quant/bootstrap", json={"values": [0.1, 0.2]})
    assert r.status_code == 422


def test_bootstrap_route_roundtrip(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/quant/bootstrap", json={"values": [0.02, 0.03, 0.025, 0.018, 0.022, 0.031, 0.027, 0.024], "seed": 7})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] and body["excludesZero"] is True


def test_config_route_publishes_thresholds(fake_manager):
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/quant/config")
    assert r.status_code == 200
    body = r.json()
    assert body["significanceLevel"] == quant_settings.quant_significance_level
    assert body["engines"]["statsmodels"] is True
