"""
Phase 21 — series preparation.

Every statistical routine in this package consumes *this* module's outputs, so
there is exactly one place where a price series is coerced, cleaned and turned
into returns. That gives three properties the rest of the app depends on:

1. **No NaN/Inf survives.** Non-finite and non-positive prices are dropped
   before any arithmetic happens, so `np.log(p)`, ratios and divisions can never
   produce a value that would then fail JSON serialization.
2. **Alignment is explicit.** Two series are joined on shared timestamps via
   `align_returns`, not by assuming equal length — mismatched history is the
   single most common way a beta gets computed against the wrong days.
3. **Sample size is checked once, up front.** Callers pass a floor and receive
   `(None, reason)` instead of a spurious statistic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence

import numpy as np

#: Below this many observations nothing distributional is reported at all.
MIN_OBSERVATIONS = 3


def _is_finite_number(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return math.isfinite(float(value))
    return False


def to_float_series(values: Iterable[object]) -> list[float]:
    """Coerce anything iterable into a list of finite floats, skipping junk.

    `None`, strings, booleans, NaN and ±Inf are all dropped rather than
    coerced — a bad tick should shrink the sample, not poison the statistic.
    """
    out: list[float] = []
    for value in values or []:
        if _is_finite_number(value):
            out.append(float(value))
    return out


def _as_array(values: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    if arr.size == 0:
        return arr
    return arr[np.isfinite(arr)]


def simple_returns(prices: Sequence[float] | np.ndarray) -> list[float]:
    """Arithmetic (pct-change) returns. Non-positive prices are skipped."""
    arr = _as_array(prices)
    if arr.size < 2:
        return []
    arr = arr[arr > 0.0]
    if arr.size < 2:
        return []
    r = np.diff(arr) / arr[:-1]
    return [float(x) for x in r[np.isfinite(r)]]


def log_returns(prices: Sequence[float] | np.ndarray) -> list[float]:
    """Continuously compounded returns: ln(P_t / P_{t-1}).

    Preferred for regression and event-study work because multi-period returns
    are sums of one-period returns, which is what the market-model arithmetic
    assumes. Non-positive prices are dropped (log is undefined there).
    """
    arr = _as_array(prices)
    if arr.size < 2:
        return []
    arr = arr[arr > 0.0]
    if arr.size < 2:
        return []
    r = np.diff(np.log(arr))
    return [float(x) for x in r[np.isfinite(r)]]


def align_returns(
    series_a: Mapping[datetime, float] | Sequence[tuple[datetime, float]],
    series_b: Mapping[datetime, float] | Sequence[tuple[datetime, float]],
    *,
    use_log: bool = True,
) -> tuple[list[float], list[float], list[datetime]]:
    """Align two price series on their shared timestamps, then difference.

    Returns `(returns_a, returns_b, timestamps)` where index *i* of each list
    refers to the same real-world interval. Timestamps are the *later* bar of
    each return, which is what a user expects to see against a date axis.
    """
    a_items = series_a.items() if isinstance(series_a, Mapping) else series_a
    b_items = series_b.items() if isinstance(series_b, Mapping) else series_b

    a = {ts: float(v) for ts, v in a_items if _is_finite_number(v) and float(v) > 0.0}
    b = {ts: float(v) for ts, v in b_items if _is_finite_number(v) and float(v) > 0.0}
    shared = sorted(set(a) & set(b))
    if len(shared) < 2:
        return [], [], []

    pa = [a[ts] for ts in shared]
    pb = [b[ts] for ts in shared]
    fn = log_returns if use_log else simple_returns
    ra, rb = fn(pa), fn(pb)
    n = min(len(ra), len(rb))
    if n == 0:
        return [], [], []
    # Both are np.diff of the same length, so n == len(ra) == len(rb); the
    # slice is defensive only.
    return ra[-n:], rb[-n:], shared[-n:]


def mean(values: Sequence[float]) -> float | None:
    arr = _as_array(values)
    if arr.size == 0:
        return None
    return float(arr.mean())


def stdev(values: Sequence[float], *, ddof: int = 1) -> float | None:
    arr = _as_array(values)
    if arr.size <= ddof:
        return None
    s = float(arr.std(ddof=ddof))
    return s if math.isfinite(s) else None


def zscore(values: Sequence[float]) -> list[float]:
    """Standardize, returning [] when the series has no dispersion."""
    arr = _as_array(values)
    if arr.size == 0:
        return []
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if not math.isfinite(sd) or sd <= 0.0:
        return []
    return [float(x) for x in (arr - mu) / sd]


def percent(value: float | None, *, places: int = 4) -> float | None:
    """`0.0123` -> `1.23` (percent), rounded, JSON-safe."""
    if value is None:
        return None
    try:
        out = float(value) * 100.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return round(out, places)


def safe_float(value: object, *, places: int | None = 6) -> float | None:
    """Round and sanitize a number for the wire; None when unusable."""
    if not _is_finite_number(value):
        return None
    out = float(value)  # type: ignore[arg-type]
    return round(out, places) if places is not None else out


@dataclass(slots=True)
class ReturnSeries:
    """A validated return series plus the provenance needed to trust it."""

    values: list[float] = field(default_factory=list)
    timestamps: list[datetime] = field(default_factory=list)
    #: Human-readable statement of where the numbers came from.
    source: str = "unknown"
    #: True when derived from a real external feed, False for demo datasets.
    is_real_data: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.values)

    def has_enough(self, minimum: int) -> bool:
        return self.n >= max(minimum, MIN_OBSERVATIONS)

    def as_array(self) -> np.ndarray:
        return _as_array(self.values)

    def insufficient(self, minimum: int, *, what: str) -> str | None:
        """Reason string when the sample is too small, else None."""
        need = max(minimum, MIN_OBSERVATIONS)
        if self.n >= need:
            return None
        return (
            f"needs at least {need} observations of {what} to be statistically "
            f"meaningful; only {self.n} available from {self.source}"
        )

    def describe(self) -> dict:
        return {
            "observations": self.n,
            "source": self.source,
            "isRealData": self.is_real_data,
            "start": self.timestamps[0].isoformat() if self.timestamps else None,
            "end": self.timestamps[-1].isoformat() if self.timestamps else None,
            "warnings": list(self.warnings),
        }


def build_return_series(
    prices: Sequence[float],
    timestamps: Sequence[datetime] | None = None,
    *,
    source: str = "unknown",
    is_real_data: bool = False,
    use_log: bool = True,
) -> ReturnSeries:
    """Prepare prices into a `ReturnSeries`, keeping timestamps index-aligned."""
    warns: list[str] = []
    clean_prices: list[float] = []
    clean_ts: list[datetime] = []
    dropped = 0
    for i, price in enumerate(prices or []):
        if not _is_finite_number(price) or float(price) <= 0.0:
            dropped += 1
            continue
        clean_prices.append(float(price))
        if timestamps is not None and i < len(timestamps) and timestamps[i] is not None:
            clean_ts.append(timestamps[i])
        else:
            clean_ts.append(datetime(1970, 1, 1, tzinfo=timezone.utc))
    if dropped:
        warns.append(f"{dropped} non-finite or non-positive price(s) excluded before analysis")

    fn = log_returns if use_log else simple_returns
    values = fn(clean_prices)
    ts = clean_ts[1 : len(values) + 1] if clean_ts else []
    if len(ts) != len(values):
        ts = []

    return ReturnSeries(
        values=values,
        timestamps=list(ts),
        source=source,
        is_real_data=is_real_data,
        warnings=warns,
    )
