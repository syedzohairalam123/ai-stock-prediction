"""
Threshold probability engine (spec §36, §71, §81).

Answers the informational question *"what is the modelled probability that BTC is
above X at time T?"* — and only when there is real history to base it on.

Two independent estimates are reported side by side, never averaged into one
authoritative number:

  * **empirical** — the observed frequency with which the asset's own h-step log
    return distribution put it above the threshold in the historical window;
  * **model_gbm** — the analytic lognormal (geometric Brownian motion) estimate
    ``P(S_T > X) = Φ(d)`` with drift and volatility estimated on the same window.

**Calibration** (spec §81) is measured, not asserted: for every evaluation point
in a walk-forward pass, a probability is produced using *only* data available at
that time, and it is then scored against the outcome that actually happened. The
Brier score and a reliability table are reported, so a 70% forecast can be
checked against how often 70% forecasts actually came true.

Everything here is labelled ``MODELLED PROBABILITY``. Nothing is presented as a
guaranteed outcome, and an unavailable estimate stays unavailable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.crypto.config import crypto_settings
from app.crypto.indicators import log_returns
from app.crypto.schemas import Candle, DataStatus, ValueOrigin

#: Minimum h-step return observations before a probability is reported.
MIN_SAMPLES = 60

#: Minimum observations before the calibration report is meaningful.
MIN_CALIBRATION_SAMPLES = 40

#: Number of walk-forward evaluation points used for calibration (bounded cost).
MAX_CALIBRATION_POINTS = 200

#: Reliability table bin edges.
RELIABILITY_BINS = 10


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def h_step_returns(closes: Sequence[float], horizon: int) -> List[float]:
    """Real overlapping h-step log returns."""
    if horizon <= 0 or len(closes) <= horizon:
        return []
    out: List[float] = []
    for index in range(len(closes) - horizon):
        start, end = closes[index], closes[index + horizon]
        if start > 0 and end > 0:
            out.append(math.log(end / start))
    return out


def annualised_moments(closes: Sequence[float], duration_seconds: int) -> tuple[Optional[float], Optional[float]]:
    """(drift, volatility) per bar, estimated from the real log-return series."""
    returns = [r for r in log_returns(list(closes)) if r is not None]
    if len(returns) < 10:
        return (None, None)
    array = np.asarray(returns, dtype=float)
    volatility = float(array.std(ddof=1))
    drift = float(array.mean())
    return (drift, volatility)


def empirical_probability_above(
    *,
    closes: Sequence[float],
    threshold: float,
    horizon: int,
) -> Optional[float]:
    """
    Historical frequency of finishing above ``threshold`` after ``horizon`` bars.

    Equivalent to asking: over the observed window, how often did a bar that
    started at its then-current price end above this threshold?
    """
    if threshold <= 0 or not closes or closes[-1] <= 0:
        return None
    returns = h_step_returns(closes, horizon)
    if len(returns) < MIN_SAMPLES:
        return None
    current = closes[-1]
    required = math.log(threshold / current)
    hits = sum(1 for r in returns if r > required)
    return hits / len(returns)


def gbm_probability_above(
    *,
    closes: Sequence[float],
    threshold: float,
    horizon: int,
) -> Optional[float]:
    """
    Analytic lognormal probability ``P(S_T > X)`` under geometric Brownian motion.

    With ``d = (ln(S0/X) + (μ - σ²/2)·h) / (σ·√h)`` the terminal log-price is
    normal with mean ``ln(S0) + (μ - σ²/2)·h`` and deviation ``σ·√h``, so the
    probability of finishing above ``X`` is ``P = Φ(d)`` directly (the classic
    ``1 - Φ`` form applies to puts, i.e. finishing *below*).
    Returns ``None`` when volatility cannot be estimated or is degenerate.
    """
    if threshold <= 0 or not closes or closes[-1] <= 0 or horizon <= 0:
        return None
    returns = [r for r in log_returns(list(closes)) if r is not None]
    if len(returns) < 30:
        return None
    array = np.asarray(returns, dtype=float)
    volatility = float(array.std(ddof=1))
    drift = float(array.mean())
    if volatility <= 0:
        return None
    sigma_h = volatility * math.sqrt(horizon)
    if sigma_h <= 0:
        return None
    numerator = math.log(closes[-1] / threshold) + (drift - 0.5 * volatility**2) * horizon
    d = numerator / sigma_h
    return _phi(d)


# ---------------------------------------------------------------------------
# calibration (spec §81)
# ---------------------------------------------------------------------------
@dataclass
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_predicted: Optional[float]
    observed_frequency: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "mean_predicted": self.mean_predicted,
            "observed_frequency": self.observed_frequency,
        }


@dataclass
class CalibrationReport:
    status: str  # OK | INSUFFICIENT_DATA
    samples: int
    brier_score: Optional[float]
    base_rate: Optional[float]
    brier_skill_score: Optional[float]
    bins: List[ReliabilityBin] = field(default_factory=list)
    threshold: Optional[float] = None
    horizon: int = 0
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "samples": self.samples,
            "brier_score": self.brier_score,
            "base_rate": self.base_rate,
            "brier_skill_score": self.brier_skill_score,
            "threshold": self.threshold,
            "horizon": self.horizon,
            "note": self.note,
            "bins": [b.to_dict() for b in self.bins],
        }


def calibrate_threshold(
    *,
    closes: Sequence[float],
    threshold: float,
    horizon: int,
    method: str = "model_gbm",
) -> CalibrationReport:
    """
    Walk-forward calibration of the threshold probability.

    At each evaluation point ``t`` the probability is rebuilt from ``closes[:t+1]``
    only, then scored against whether the realised price at ``t+horizon`` was
    actually above the threshold. This is a genuine out-of-sample check with no
    look-ahead.
    """
    total = len(closes)
    if total < max(MIN_CALIBRATION_SAMPLES + horizon + 60, 150):
        return CalibrationReport(
            status="INSUFFICIENT_DATA",
            samples=0,
            brier_score=None,
            base_rate=None,
            brier_skill_score=None,
            threshold=threshold,
            horizon=horizon,
            note="not enough history for a walk-forward calibration",
        )

    minimum_train = max(120, total // 4)
    available = total - horizon - minimum_train
    if available <= 0:
        return CalibrationReport(
            status="INSUFFICIENT_DATA",
            samples=0,
            brier_score=None,
            base_rate=None,
            brier_skill_score=None,
            threshold=threshold,
            horizon=horizon,
            note="not enough history for a walk-forward calibration",
        )
    step = max(1, available // MAX_CALIBRATION_POINTS)

    probabilities: List[float] = []
    outcomes: List[int] = []
    for index in range(minimum_train, total - horizon, step):
        history = list(closes[: index + 1])
        if method == "empirical":
            probability = empirical_probability_above(
                closes=history, threshold=threshold, horizon=horizon
            )
        else:
            probability = gbm_probability_above(closes=history, threshold=threshold, horizon=horizon)
        if probability is None:
            continue
        realised = closes[index + horizon]
        probabilities.append(probability)
        outcomes.append(1 if realised > threshold else 0)

    if len(probabilities) < MIN_CALIBRATION_SAMPLES:
        return CalibrationReport(
            status="INSUFFICIENT_DATA",
            samples=len(probabilities),
            brier_score=None,
            base_rate=None,
            brier_skill_score=None,
            threshold=threshold,
            horizon=horizon,
            note=f"only {len(probabilities)} scored points",
        )

    probabilities_array = np.asarray(probabilities, dtype=float)
    outcomes_array = np.asarray(outcomes, dtype=float)
    brier = float(np.mean((probabilities_array - outcomes_array) ** 2))
    base_rate = float(outcomes_array.mean())
    # Brier skill score against the climatological (always base-rate) forecast.
    reference = float(np.mean((base_rate - outcomes_array) ** 2))
    skill = (1.0 - brier / reference) if reference > 0 else None

    bins: List[ReliabilityBin] = []
    edges = np.linspace(0.0, 1.0, RELIABILITY_BINS + 1)
    for index in range(RELIABILITY_BINS):
        lower, upper = float(edges[index]), float(edges[index + 1])
        mask = (probabilities_array >= lower) & (
            probabilities_array < upper if index < RELIABILITY_BINS - 1 else probabilities_array <= upper
        )
        count = int(mask.sum())
        bins.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_predicted=float(probabilities_array[mask].mean()) if count else None,
                observed_frequency=float(outcomes_array[mask].mean()) if count else None,
            )
        )

    return CalibrationReport(
        status="OK",
        samples=len(probabilities),
        brier_score=brier,
        base_rate=base_rate,
        brier_skill_score=skill,
        bins=bins,
        threshold=threshold,
        horizon=horizon,
        note=(
            "Walk-forward reliability: each probability used only data available at its "
            "own timestamp. Brier skill score compares against the base-rate forecast "
            "(0 = no skill, 1 = perfect)."
        ),
    )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def threshold_analysis(
    *,
    symbol: str,
    timeframe: str,
    candles: Sequence[Candle],
    threshold: float,
    horizon: int,
    direction: str = "above",
    currency: str = "USD",
) -> Dict[str, object]:
    """
    Full threshold answer, with both estimates and their calibration.

    ``direction='below'`` inverts the question (``P(S_T < X)``). When the data
    cannot support an estimate, ``probabilities`` is null and the reason is
    stated — the card exists but the number is honestly absent.
    """
    closes = [c.close for c in candles]
    if not closes or threshold <= 0 or horizon <= 0:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "threshold": threshold,
            "horizon": horizon,
            "direction": direction,
            "currency": currency,
            "probabilities": None,
            "label": "MODELLED PROBABILITY",
            "origin": ValueOrigin.MODELLED.value,
            "status": DataStatus.UNAVAILABLE.value,
            "reason": "no usable price series or invalid threshold/horizon",
        }

    empirical = empirical_probability_above(closes=closes, threshold=threshold, horizon=horizon)
    gbm = gbm_probability_above(closes=closes, threshold=threshold, horizon=horizon)
    if direction == "below":
        empirical = None if empirical is None else 1.0 - empirical
        gbm = None if gbm is None else 1.0 - gbm

    if empirical is None and gbm is None:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "threshold": threshold,
            "horizon": horizon,
            "direction": direction,
            "currency": currency,
            "probabilities": None,
            "label": "MODELLED PROBABILITY",
            "origin": ValueOrigin.MODELLED.value,
            "status": DataStatus.UNAVAILABLE.value,
            "reason": (
                f"insufficient history: {len(h_step_returns(closes, horizon))} h-step returns "
                f"(minimum {MIN_SAMPLES})"
            ),
        }

    calibration = calibrate_threshold(
        closes=closes, threshold=threshold, horizon=horizon, method="model_gbm"
    )
    samples = len(h_step_returns(closes, horizon))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "threshold": threshold,
        "horizon": horizon,
        "direction": direction,
        "currency": currency,
        "current_price": closes[-1],
        "distance_percent": (threshold / closes[-1] - 1.0) * 100.0 if closes[-1] else None,
        "probabilities": {
            "empirical": empirical,
            "model_gbm": gbm,
            "samples": samples,
        },
        "calibration": calibration.to_dict(),
        "label": "MODELLED PROBABILITY",
        "origin": ValueOrigin.MODELLED.value,
        "status": DataStatus.LIVE.value,
        "note": (
            "Modelled probabilities from the asset's own historical return distribution and a "
            "lognormal (GBM) estimate. They are analytical estimates, not guarantees, and not "
            "betting or wagering odds."
        ),
    }
