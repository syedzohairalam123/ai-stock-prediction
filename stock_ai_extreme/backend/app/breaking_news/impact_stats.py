"""
Observed-movement event study (spec §7, §9, §10, §14).

A single :class:`~.models.models.MarketImpactEvent` row is an anecdote: one
event, one instrument, one window. Read on its own it invites exactly the mistake
the phase forbids — "this news moved the price". This module aggregates the
movement rows the desk has *already recorded* into a sample with an honest
denominator, so the desk can say:

    across 17 observed events for OGDC, the mean 1h move was -0.42%
    (median -0.31%, 9 up / 8 down)

instead of implying that one number is a law.

What is measured, and from what
-------------------------------
Every figure here is a statistic over real stored rows. Nothing is modelled,
projected or smoothed:

* Only rows with ``window_available`` **and** a real ``price_change_percent``
  enter the sample. A row that was recorded UNAVAILABLE has no measured move, so
  counting it as 0% would bias the mean toward zero — it is counted separately as
  ``unavailable_samples`` instead, which keeps the denominator visible.
* ``sample_size`` is therefore the number of *measured* observations, and
  ``sufficient_sample`` is false until that reaches the configured minimum. The
  caller is expected to render the "too few observations" state rather than a
  confident-looking average.
* ``stdev_percent`` is the sample standard deviation (``n-1``) and is only
  reported for ``n >= 2``; a dispersion of one point is not a dispersion.
* ``hit_rate_up`` is the share of measured observations with a positive move. It
  is a description of the sample, not a probability of anything future.

The label is enforced in the payload: every response carries
``disclaimer`` = observed-not-causal, so a consumer that reads a single field
still sees it.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable, Optional

from .config import breaking_news_settings
from .schemas import ImpactMagnitude
from .timeutil import iso, to_naive_utc, utcnow

#: Row attributes the study reads. Declared once so the ORM dependency is
#: explicit and a schema change is a one-line fix rather than a silent ``None``.
_FIELDS = (
    "entity",
    "entity_type",
    "observation_window",
    "price_change_percent",
    "max_favorable_excursion_percent",
    "max_adverse_excursion_percent",
    "realized_volatility_percent",
    "confidence",
    "impact_magnitude",
    "window_available",
    "news_published_at",
    "breaking_news_id",
    "article_id",
)

DISCLAIMER = (
    "Aggregates describe price movements observed after publication across the stored "
    "sample. They are descriptive statistics, not causal evidence and not a forecast."
)


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # NaN/inf are not observations; report them as absent rather than let them
    # poison a mean.
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def _stdev(values: list[float]) -> Optional[float]:
    """Sample standard deviation (n-1); undefined for a single observation."""
    if len(values) < 2:
        return None
    try:
        return round(statistics.stdev(values), 4)
    except statistics.StatisticsError:  # pragma: no cover - defensive
        return None


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    try:
        return round(statistics.median(values), 4)
    except statistics.StatisticsError:  # pragma: no cover - defensive
        return None


def _movement_ref(row: Any, change: Optional[float]) -> dict:
    """A compact, linkable reference to one observation (never fabricated)."""
    published = to_naive_utc(_value(row, "news_published_at"))
    return {
        "entity": _value(row, "entity"),
        "entity_type": _value(row, "entity_type"),
        "observation_window": _value(row, "observation_window"),
        "price_change_percent": change,
        "news_published_at": iso(published),
        "breaking_news_id": _value(row, "breaking_news_id"),
        "article_id": _value(row, "article_id"),
    }


def summarize_observed_movements(rows: Iterable[Any]) -> dict:
    """Statistics for one set of movement rows.

    Returns a plain dict matching
    :class:`~.schemas.ObservedMovementStats`. Rows are partitioned into measured
    observations (usable) and unavailable/unmeasured ones (reported as a count,
    never folded into the sample).
    """
    rows = list(rows)
    measured: list[Any] = []
    changes: list[float] = []

    for row in rows:
        change = _as_float(_value(row, "price_change_percent"))
        available = bool(_value(row, "window_available"))
        if available and change is not None:
            measured.append(row)
            changes.append(change)

    up = sum(1 for value in changes if value > 0)
    down = sum(1 for value in changes if value < 0)
    flat = len(changes) - up - down

    magnitudes = {
        member.value: 0 for member in ImpactMagnitude
    }
    for row in measured:
        label = str(_value(row, "impact_magnitude") or "").upper()
        if label in magnitudes:
            magnitudes[label] += 1

    timestamps = [
        to_naive_utc(_value(row, "news_published_at"))
        for row in measured
    ]
    timestamps = [stamp for stamp in timestamps if stamp is not None]

    best_row = best_change = None
    worst_row = worst_change = None
    for row, change in zip(measured, changes):
        if best_change is None or change > best_change:
            best_row, best_change = row, change
        if worst_change is None or change < worst_change:
            worst_row, worst_change = row, change

    return {
        "sample_size": len(changes),
        "unavailable_samples": len(rows) - len(measured),
        "up": up,
        "down": down,
        "flat": flat,
        "hit_rate_up": round(up / len(changes), 4) if changes else None,
        "mean_percent": _mean(changes),
        "median_percent": _median(changes),
        "stdev_percent": _stdev(changes),
        "mean_absolute_percent": _mean([abs(value) for value in changes]),
        "max_gain_percent": round(max(changes), 4) if changes else None,
        "max_loss_percent": round(min(changes), 4) if changes else None,
        "mean_max_favorable_percent": _mean([
            value for value in (
                _as_float(_value(row, "max_favorable_excursion_percent")) for row in measured
            ) if value is not None
        ]),
        "mean_max_adverse_percent": _mean([
            value for value in (
                _as_float(_value(row, "max_adverse_excursion_percent")) for row in measured
            ) if value is not None
        ]),
        "mean_realized_volatility_percent": _mean([
            value for value in (
                _as_float(_value(row, "realized_volatility_percent")) for row in measured
            ) if value is not None
        ]),
        "mean_confidence": _mean([
            value for value in (
                _as_float(_value(row, "confidence")) for row in measured
            ) if value is not None
        ]),
        "magnitude_breakdown": magnitudes,
        "first_observed_at": iso(min(timestamps)) if timestamps else None,
        "last_observed_at": iso(max(timestamps)) if timestamps else None,
        "best": _movement_ref(best_row, best_change) if best_row is not None else None,
        "worst": _movement_ref(worst_row, worst_change) if worst_row is not None else None,
    }


def _group(buckets: list[tuple[tuple, list[Any]]], *, min_sample: int) -> list[dict]:
    """Turn ``(key, rows)`` buckets into scored, self-describing groups."""
    out: list[dict] = []
    for key, members in buckets:
        stats = summarize_observed_movements(members)
        out.append({
            "key": key[0],
            "label": key[1],
            "entity_type": key[2],
            "observation_window": key[3],
            "sufficient_sample": stats["sample_size"] >= min_sample,
            "stats": stats,
        })
    return out


def _bucket(
    rows: list[Any],
    selector,
) -> list[tuple[tuple, list[Any]]]:
    """Group rows by ``selector(row)``, preserving first-seen key order.

    Key order is then re-sorted by sample size at the call site, so the groups a
    reader sees first are the ones with the most evidence behind them.
    """
    buckets: dict[tuple, list[Any]] = {}
    for row in rows:
        buckets.setdefault(selector(row), []).append(row)
    return list(buckets.items())


def build_impact_study(
    rows: Iterable[Any],
    *,
    hours: int,
    min_sample: Optional[int] = None,
    window: Optional[str] = None,
    entity_type: Optional[str] = None,
) -> dict:
    """Aggregate movement rows into an overall figure plus honest breakdowns.

    ``min_sample`` defaults to :attr:`BreakingNewsSettings.impact_study_min_sample`
    so the "is this enough evidence?" bar is configuration, not a magic number
    buried in a route.
    """
    rows = list(rows)
    threshold = int(
        min_sample if min_sample is not None else breaking_news_settings.impact_study_min_sample
    )
    max_groups = int(breaking_news_settings.impact_study_max_groups)

    overall = summarize_observed_movements(rows)

    by_entity = _bucket(
        rows,
        lambda row: (
            str(_value(row, "entity") or "UNKNOWN"),
            str(_value(row, "entity") or "UNKNOWN"),
            _value(row, "entity_type"),
            None,
        ),
    )
    by_entity_type = _bucket(
        rows,
        lambda row: (
            str(_value(row, "entity_type") or "UNKNOWN"),
            str(_value(row, "entity_type") or "UNKNOWN").replace("_", " ").title(),
            str(_value(row, "entity_type") or "UNKNOWN"),
            None,
        ),
    )
    by_window = _bucket(
        rows,
        lambda row: (
            str(_value(row, "observation_window") or "UNKNOWN"),
            f"{_value(row, 'observation_window') or 'unknown'} window",
            None,
            str(_value(row, "observation_window") or "UNKNOWN"),
        ),
    )

    def ordered(buckets: list[tuple[tuple, list[Any]]]) -> list[dict]:
        groups = _group(sorted(buckets, key=lambda item: (-len(item[1]), item[0][0])), min_sample=threshold)
        return groups[:max_groups]

    entity_groups = ordered(by_entity)
    type_groups = ordered(by_entity_type)
    window_groups = ordered(by_window)
    sufficient = sum(
        1
        for group in (*entity_groups, *type_groups, *window_groups)
        if group["sufficient_sample"]
    )

    return {
        "generated_at": iso(utcnow()),
        "hours": int(hours),
        "min_sample": threshold,
        "window": window,
        "entity_type": entity_type,
        "samples_considered": len(rows),
        "measured_samples": overall["sample_size"],
        "unavailable_samples": overall["unavailable_samples"],
        "sufficient_groups": sufficient,
        "overall": overall,
        "by_entity": entity_groups,
        "by_entity_type": type_groups,
        "by_window": window_groups,
        "note": (
            "Each group reports the number of measured observations it is based on. "
            "Groups below the minimum sample size are marked insufficient_sample=true "
            "and should be read as an indication of what has been recorded, not as an average."
        ),
        "disclaimer": DISCLAIMER,
    }


__all__ = [
    "DISCLAIMER",
    "build_impact_study",
    "summarize_observed_movements",
]
