"""
Phase 21 — modular quantitative analytics.

One package, one job: the *statistically correct* tool for each question the
rest of the app asks about a price or probability series. It exists because
several existing call sites were answering statistical questions with
descriptive arithmetic — a beta with no standard error, an event study with no
significance test, a forecast model chosen without testing whether the series
is even mean-reverting.

Design rules (same as the rest of this project):

* **One module per question.** `stationarity`, `regression`, `risk`,
  `event_study`, `distributions`. Each is independently callable and testable.
* **The right algorithm, not the fashionable one.** ADF/KPSS for stationarity,
  Newey–West HAC for return regressions, Student-t and Cornish–Fisher for tail
  risk, a standardized (Patell) test plus a bootstrap for event studies. No
  neural network is asked to do an arithmetic job.
* **Honest degradation.** Too few real observations → `None` plus a stated
  reason, never a number invented to fill a slot. `statsmodels` is imported
  defensively and every call site has a documented fallback, so the app still
  runs without it (the same pattern `regime.py` uses for `hmmlearn`).
* **No NaN/Infinity ever escapes.** Every public function returns JSON-safe
  values.
"""
from .distributions import (
    aic,
    bic,
    distribution_fit,
    goodness_of_fit,
    normal_quantile,
    student_t_quantile,
)
from .event_study import (
    abnormal_return_study,
    bootstrap_mean_ci,
    patell_test,
)
from .regression import (
    hac_beta,
    hac_ols,
    rolling_beta,
)
from .risk import (
    drawdown_profile,
    moment_report,
    risk_of_ruin_summary,
    tail_risk,
    volatility_report,
)
from .routes import quant_router
from .series import (
    MIN_OBSERVATIONS,
    ReturnSeries,
    align_returns,
    build_return_series,
    log_returns,
    simple_returns,
    to_float_series,
)
from .stationarity import (
    hurst_exponent,
    regime_hint,
    stationarity_report,
    variance_ratio_test,
)

__all__ = [
    "quant_router",
    # series
    "ReturnSeries",
    "MIN_OBSERVATIONS",
    "to_float_series",
    "simple_returns",
    "log_returns",
    "align_returns",
    "build_return_series",
    # stationarity
    "stationarity_report",
    "variance_ratio_test",
    "hurst_exponent",
    "regime_hint",
    # regression
    "hac_ols",
    "hac_beta",
    "rolling_beta",
    # risk
    "tail_risk",
    "volatility_report",
    "drawdown_profile",
    "moment_report",
    "risk_of_ruin_summary",
    # event study
    "abnormal_return_study",
    "patell_test",
    "bootstrap_mean_ci",
    # distributions
    "distribution_fit",
    "goodness_of_fit",
    "normal_quantile",
    "student_t_quantile",
    "aic",
    "bic",
]
