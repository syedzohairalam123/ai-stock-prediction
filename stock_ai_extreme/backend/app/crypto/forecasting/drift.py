"""
Model drift monitoring + outlier detection (spec §77, §78, §79).

**Drift.** :class:`ModelDriftMonitor` compares the feature distribution a model
was trained on against the recent production distribution, per feature, using
two independent, standard measures:

  * **Population Stability Index** — ``Σ (p_actual - p_expected) · ln(p_actual/p_expected)``
    over bins derived from the reference data's own quantiles. The conventional
    interpretation (PSI < 0.1 stable, 0.1–0.25 watch, > 0.25 shifted) is stated
    explicitly so nobody has to guess at a threshold.
  * **Two-sample Kolmogorov–Smirnov** (SciPy) — a distribution-free test with a
    real p-value.

Both are computed from stored observations, so a degraded model is *labelled*
degraded (``MODEL PERFORMANCE DEGRADED``) rather than quietly continuing to
present itself as healthy (spec §77).

**Outliers.** :func:`detect_outliers` flags abnormal observations with a robust
z-score (median/MAD), an IQR rule and rolling volatility. The output is
``DATA ANOMALY`` — never a directional claim such as "price will crash" (§79).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("neural_market.crypto.forecasting.drift")

#: Conventional PSI interpretation bands (documented, not magic).
PSI_STABLE = 0.10
PSI_SHIFTED = 0.25

#: KS p-value below which the two samples are treated as differently distributed.
KS_ALPHA = 0.05

#: Robust z-score above which an observation is flagged.
Z_THRESHOLD = 3.5

#: Rolling-volatility multiple above which a bar is flagged as abnormally wide.
VOLATILITY_MULTIPLE = 4.0


@dataclass
class FeatureDrift:
    feature: str
    psi: Optional[float]
    ks_statistic: Optional[float]
    ks_pvalue: Optional[float]
    status: str  # STABLE | WATCH | SHIFTED | UNKNOWN

    def to_dict(self) -> Dict[str, object]:
        return {
            "feature": self.feature,
            "psi": self.psi,
            "ks_statistic": self.ks_statistic,
            "ks_pvalue": self.ks_pvalue,
            "status": self.status,
        }


@dataclass
class DriftReport:
    status: str  # STABLE | WATCH | MODEL PERFORMANCE DEGRADED | UNKNOWN
    compared_at: datetime
    reference_size: int
    recent_size: int
    features: List[FeatureDrift] = field(default_factory=list)
    degraded_share: float = 0.0
    training_age_days: Optional[float] = None
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "compared_at": self.compared_at.isoformat(),
            "reference_size": self.reference_size,
            "recent_size": self.recent_size,
            "degraded_share": self.degraded_share,
            "training_age_days": self.training_age_days,
            "note": self.note,
            "features": [f.to_dict() for f in self.features],
        }


def population_stability_index(
    reference: Sequence[float], actual: Sequence[float], *, bins: int = 10
) -> Optional[float]:
    """
    PSI of ``actual`` relative to ``reference`` using reference-derived quantile bins.

    Returns ``None`` when either sample is empty or the reference has no spread
    (a constant feature carries no distribution to shift).
    """
    reference_array = np.asarray([v for v in reference if v is not None], dtype=float)
    actual_array = np.asarray([v for v in actual if v is not None], dtype=float)
    if reference_array.size == 0 or actual_array.size == 0:
        return None
    edges = np.unique(np.quantile(reference_array, np.linspace(0, 1, bins + 1)))
    if edges.size < 3:
        return None
    edges[0] = -np.inf
    edges[-1] = np.inf

    expected_counts, _ = np.histogram(reference_array, bins=edges)
    actual_counts, _ = np.histogram(actual_array, bins=edges)
    expected = expected_counts / max(1, expected_counts.sum())
    observed = actual_counts / max(1, actual_counts.sum())

    eps = 1e-6  # avoid log(0); documented floor, not a data value
    expected = np.clip(expected, eps, None)
    observed = np.clip(observed, eps, None)
    return float(np.sum((observed - expected) * np.log(observed / expected)))


def ks_test(reference: Sequence[float], actual: Sequence[float]) -> tuple[Optional[float], Optional[float]]:
    """Two-sample Kolmogorov–Smirnov statistic and p-value (SciPy)."""
    reference_array = np.asarray([v for v in reference if v is not None], dtype=float)
    actual_array = np.asarray([v for v in actual if v is not None], dtype=float)
    if reference_array.size < 2 or actual_array.size < 2:
        return (None, None)
    try:
        from scipy import stats

        result = stats.ks_2samp(reference_array, actual_array)
        return (float(result.statistic), float(result.pvalue))
    except Exception as exc:  # pragma: no cover - SciPy is a hard dependency here
        logger.warning("KS test unavailable: %s", exc)
        return (None, None)


def _classify(psi: Optional[float], ks_pvalue: Optional[float]) -> str:
    if psi is None and ks_pvalue is None:
        return "UNKNOWN"
    if psi is not None and psi > PSI_SHIFTED:
        return "SHIFTED"
    if ks_pvalue is not None and ks_pvalue < KS_ALPHA:
        return "SHIFTED"
    if psi is not None and psi > PSI_STABLE:
        return "WATCH"
    return "STABLE"


class ModelDriftMonitor:
    """
    Compares a stored training feature distribution with recent observations.

    The reference distribution is whatever was actually used at training time;
    the recent window is the newest available rows. Nothing is synthesised — if
    either side is missing, the report says ``UNKNOWN``.
    """

    def compare(
        self,
        *,
        reference: Dict[str, Sequence[float]],
        recent: Dict[str, Sequence[float]],
        training_time: Optional[datetime] = None,
    ) -> DriftReport:
        features: List[FeatureDrift] = []
        now = datetime.now(timezone.utc)
        for name in sorted(reference):
            reference_values = list(reference.get(name) or [])
            recent_values = list(recent.get(name) or [])
            psi = population_stability_index(reference_values, recent_values)
            ks_statistic, ks_pvalue = ks_test(reference_values, recent_values)
            features.append(
                FeatureDrift(
                    feature=name,
                    psi=psi,
                    ks_statistic=ks_statistic,
                    ks_pvalue=ks_pvalue,
                    status=_classify(psi, ks_pvalue),
                )
            )

        if not features:
            return DriftReport(
                status="UNKNOWN",
                compared_at=now,
                reference_size=0,
                recent_size=0,
                note="No reference feature distribution recorded for this model.",
            )

        shifted = sum(1 for f in features if f.status == "SHIFTED")
        watch = sum(1 for f in features if f.status == "WATCH")
        share = shifted / len(features)

        if share >= 0.4:
            status = "MODEL PERFORMANCE DEGRADED"
        elif shifted or watch > len(features) // 2:
            status = "WATCH"
        else:
            status = "STABLE"

        age_days = None
        if training_time is not None:
            reference_time = training_time
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            age_days = (now - reference_time).total_seconds() / 86400.0

        return DriftReport(
            status=status,
            compared_at=now,
            reference_size=max((len(v) for v in reference.values()), default=0),
            recent_size=max((len(v) for v in recent.values()), default=0),
            features=features,
            degraded_share=round(share, 6),
            training_age_days=round(age_days, 3) if age_days is not None else None,
            note=(
                f"{shifted} of {len(features)} features shifted (PSI>{PSI_SHIFTED} "
                f"or KS p<{KS_ALPHA}); {watch} on watch."
            ),
        )


# ---------------------------------------------------------------------------
# outliers / anomalies
# ---------------------------------------------------------------------------
@dataclass
class AnomalyReport:
    status: str  # DATA ANOMALY | NORMAL | INSUFFICIENT_DATA
    flags: List[str] = field(default_factory=list)
    robust_z: Optional[float] = None
    iqr_outlier: Optional[bool] = None
    volatility_multiple: Optional[float] = None
    sample_size: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "flags": list(self.flags),
            "robust_z": self.robust_z,
            "iqr_outlier": self.iqr_outlier,
            "volatility_multiple": self.volatility_multiple,
            "sample_size": self.sample_size,
            # Explicitly non-directional: we report an observation, not a call.
            "note": "An anomaly flag is a statistical observation about the data, not a price prediction.",
        }


def robust_z_scores(values: Sequence[float]) -> List[Optional[float]]:
    """
    Median/MAD z-scores — resistant to the very outliers they are meant to find.

    MAD == 0 (a degenerate window) yields ``None`` rather than a division blow-up.
    """
    array = np.asarray(list(values), dtype=float)
    if array.size < 3:
        return [None] * array.size
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    if mad <= 0:
        return [None] * array.size
    return [float((value - median) / (1.4826 * mad)) for value in array]


def detect_outliers(
    *,
    returns: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    window: int = 20,
) -> AnomalyReport:
    """
    Flag an abnormal latest observation (spec §79).

    Uses three independent rules so a single mechanism cannot produce a false
    alarm on its own: robust z-score of returns, the IQR fence, and the latest
    bar range versus its rolling average.
    """
    usable_returns = [float(r) for r in returns if r is not None]
    if len(usable_returns) < max(10, window // 2):
        return AnomalyReport(status="INSUFFICIENT_DATA", sample_size=len(usable_returns))

    zscores = robust_z_scores(usable_returns)
    latest_z = zscores[-1] if zscores else None

    array = np.asarray(usable_returns, dtype=float)
    q1, q3 = np.quantile(array, [0.25, 0.75])
    iqr = float(q3 - q1)
    lower, upper = float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)
    iqr_outlier = bool(array[-1] < lower or array[-1] > upper)

    volatility_multiple: Optional[float] = None
    if len(highs) > window and len(lows) > window:
        ranges = [h - l for h, l in zip(highs, lows)]  # noqa: E741
        baseline = float(np.mean(ranges[-window - 1 : -1]))
        if baseline > 0:
            volatility_multiple = float(ranges[-1] / baseline)

    flags: List[str] = []
    if latest_z is not None and abs(latest_z) > Z_THRESHOLD:
        flags.append(f"return |robust z| = {abs(latest_z):.2f} > {Z_THRESHOLD}")
    if iqr_outlier:
        flags.append("latest return outside the 1.5x IQR fence")
    if volatility_multiple is not None and volatility_multiple > VOLATILITY_MULTIPLE:
        flags.append(f"bar range {volatility_multiple:.2f}x the rolling mean")

    return AnomalyReport(
        status="DATA ANOMALY" if flags else "NORMAL",
        flags=flags,
        robust_z=latest_z,
        iqr_outlier=iqr_outlier,
        volatility_multiple=volatility_multiple,
        sample_size=len(usable_returns),
    )


def training_age_status(training_time: Optional[datetime], *, max_age_days: float = 7.0) -> str:
    """Label a model as fresh or stale purely from its real training timestamp."""
    if training_time is None:
        return "UNKNOWN"
    reference = training_time
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - reference).total_seconds() / 86400.0
    if not math.isfinite(age_days):
        return "UNKNOWN"
    return "FRESH" if age_days <= max_age_days else "STALE"


#: Process-wide singleton (stateless).
drift_monitor = ModelDriftMonitor()
