"""
Small, explainable time-series analytics for trend history (spec §12, §18).

Used by ``GET /api/discover/trends/{id}`` over *actual stored observations*
({timestamp, activity, score}). Everything here is a classical, inspectable
statistic — no black-box model — and every output can be recomputed by hand
from the points returned alongside it:

    * exponential moving average   smooths the score for display
    * rolling z-score              "is the latest activity unusual *for this
                                   entity*?", using the sample's own mean/σ
    * acceleration                 second difference of activity per hour²
    * linear slope                 least-squares trend direction (rise/fall/
                                   flat) with a documented dead-band

If fewer than two points exist the helpers return ``None`` — the API then says
"not enough observations yet" instead of drawing a confident line through one
dot (spec §17).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

try:  # numpy is a hard dependency of pandas (already required by this app)
    import numpy as np
except Exception:  # pragma: no cover - numpy is always present in practice
    np = None  # type: ignore[assignment]


def _series(points: Sequence[Dict[str, Any]], key: str) -> List[float]:
    values: List[float] = []
    for point in points:
        raw = point.get(key)
        if raw is None:
            values.append(float("nan"))
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            values.append(float("nan"))
    return values


def exponential_moving_average(values: Sequence[float], alpha: float = 0.35) -> List[Optional[float]]:
    """EMA display series; ``None`` until the first real value arrives."""
    out: List[Optional[float]] = []
    previous: Optional[float] = None
    for value in values:
        if math.isnan(value):
            out.append(previous)
            continue
        previous = value if previous is None else alpha * value + (1 - alpha) * previous
        out.append(round(previous, 4))
    return out


def rolling_zscore(values: Sequence[float]) -> Optional[float]:
    """Z-score of the *latest* value against the whole sample.

    Returns ``None`` when the sample is too small or has no variance — a
    zero-variance series has no meaningful "unusual".
    """
    usable = [v for v in values if not math.isnan(v)]
    if len(usable) < 3 or np is None:
        return None
    array = np.asarray(usable, dtype=float)
    std = float(array.std(ddof=1))
    if std == 0:
        return None
    z = (float(array[-1]) - float(array.mean())) / std
    return round(float(z), 3)


def linear_slope_per_hour(timestamps: Sequence[float], values: Sequence[float]) -> Optional[float]:
    """Least-squares slope of ``values`` over ``timestamps`` (unix seconds)."""
    pairs = [(t, v) for t, v in zip(timestamps, values) if not math.isnan(v)]
    if len(pairs) < 2 or np is None:
        return None
    xs = np.asarray([p[0] for p in pairs], dtype=float)
    ys = np.asarray([p[1] for p in pairs], dtype=float)
    if float(xs.max() - xs.min()) <= 0:
        return None
    slope, _intercept = np.polyfit(xs, ys, 1)
    return float(slope) * 3600.0  # per hour


def analyze(points: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Explainable summary of an observation series.

    ``points``: ``[{"timestamp": iso, "activity": x, "score": y}, ...]``
    sorted ascending by timestamp.
    """
    if not points:
        return {
            "count": 0,
            "available": False,
            "reason": "No observations recorded yet for this entity.",
            "activitySeries": [],
            "scoreSeries": [],
            "scoreEma": [],
            "slopePerHour": None,
            "accelerationPerHour2": None,
            "zscore": None,
            "anomaly": False,
            "direction": "STABLE",
        }

    scores = _series(points, "score")
    activity = _series(points, "activity")
    timestamps: List[float] = []
    for point in points:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(str(point.get("timestamp")).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                from datetime import timezone

                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt.timestamp())
        except (ValueError, TypeError):
            timestamps.append(float("nan"))

    slope = linear_slope_per_hour(timestamps, scores)
    zscore = rolling_zscore(scores)

    # Acceleration: change in per-hour activity slope over the last 3 points.
    acceleration: Optional[float] = None
    usable_activity = [(t, a) for t, a in zip(timestamps, activity) if not math.isnan(a)]
    if len(usable_activity) >= 3 and np is not None:
        xs = np.asarray([p[0] for p in usable_activity[-3:]], dtype=float)
        ys = np.asarray([p[1] for p in usable_activity[-3:]], dtype=float)
        if float(xs.max() - xs.min()) > 0:
            coeffs = np.polyfit(xs, ys, 2)
            acceleration = float(coeffs[0]) * 3600.0 ** 2  # units per hour²

    # Direction from the slope with a small dead-band: a series that is
    # essentially flat reports STABLE rather than a jittery direction.
    if slope is None:
        direction = "STABLE"
    elif abs(slope) < 0.02:
        direction = "STABLE"
    else:
        direction = "RISING" if slope > 0 else "FALLING"

    return {
        "count": len(points),
        "available": len(points) >= 2,
        "reason": None if len(points) >= 2 else "Only one observation recorded so far.",
        "activitySeries": [None if math.isnan(v) else round(v, 4) for v in activity],
        "scoreSeries": [None if math.isnan(v) else round(v, 4) for v in scores],
        "scoreEma": exponential_moving_average([v if not math.isnan(v) else float("nan") for v in scores]),
        "slopePerHour": round(slope, 6) if slope is not None else None,
        "accelerationPerHour2": round(acceleration, 6) if acceleration is not None else None,
        "zscore": zscore,
        "anomaly": bool(zscore is not None and abs(zscore) >= 2.0),
        "direction": direction,
        "note": (
            "Statistics are computed over the observed points listed here — "
            "no value is predicted or extrapolated."
        ),
    }


__all__ = [
    "analyze",
    "exponential_moving_average",
    "rolling_zscore",
    "linear_slope_per_hour",
]
