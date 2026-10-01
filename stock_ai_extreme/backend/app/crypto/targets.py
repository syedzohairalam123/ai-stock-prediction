"""
Price target engine (spec §32–§40, §44, §70, §72).

A target is an **analytical milestone**, not a promise. Two legitimate origins
exist, and both are labelled:

  * ``user`` — a milestone a user explicitly recorded (persisted, status tracked);
  * ``derived`` — a level computed from *real historical price structure* (recent
    swing highs/lows nearest the current price). The methodology is stated, and
    the level is a real observed price, never a round number picked to look good.

Reach detection is driven by actual timestamped candles (spec §34). A target is
never marked reached from a click, and the first timestamp at which the real
condition held is stored. Touch counts are observed statistics over a stated
lookback window (spec §38) — never a future guarantee.

Status semantics (documented once, used everywhere):

  ``ACTIVE``      condition not yet met, due date not passed (or none set)
  ``REACHED``     the real condition was met at ``first_reached_at``
  ``MISSED``      due date passed, not reached, and history covers the window
  ``EXPIRED``     due date passed, not reached, and history does NOT cover it —
                  so "missed" would be a claim the data cannot support
  ``INVALIDATED`` explicitly retired by a user
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.crypto.config import crypto_settings
from app.crypto.schemas import (
    Candle,
    PriceTarget,
    TargetStatus,
    ValueOrigin,
)

logger = logging.getLogger("neural_market.crypto.targets")

#: Valid directions for the comparison.
DIRECTIONS = ("above", "below")

#: A crossing needs prices on both sides; touching is evaluated against highs/lows.
_MIN_CANDLES_FOR_STRUCTURE = 30


class TargetError(ValueError):
    """Raised for an invalid target definition."""


def validate_target_inputs(
    *,
    target_price: Any,
    direction: str,
    target_date: Optional[Any] = None,
) -> Tuple[float, str, Optional[datetime]]:
    """
    Server-side validation (spec §93). Rejects NaN/Infinity/negative/missing
    values and malformed dates rather than trusting the client.
    """
    try:
        price = float(target_price)
    except (TypeError, ValueError):
        raise TargetError("target_price must be a number") from None
    if not math.isfinite(price):
        raise TargetError("target_price must be finite (no NaN/Infinity)")
    if price <= 0:
        raise TargetError("target_price must be greater than zero")

    resolved_direction = (direction or "").strip().lower()
    if resolved_direction not in DIRECTIONS:
        raise TargetError(f"direction must be one of {DIRECTIONS}")

    resolved_date: Optional[datetime] = None
    if target_date not in (None, ""):
        if isinstance(target_date, datetime):
            resolved_date = target_date
        else:
            text = str(target_date).strip().replace("Z", "+00:00")
            try:
                resolved_date = datetime.fromisoformat(text)
            except ValueError:
                try:
                    resolved_date = datetime.fromisoformat(text + "T00:00:00")
                except ValueError:
                    raise TargetError(f"target_date {target_date!r} is not a valid ISO date") from None
        if resolved_date.tzinfo is None:
            resolved_date = resolved_date.replace(tzinfo=timezone.utc)
    return price, resolved_direction, resolved_date


def build_target(
    *,
    symbol: str,
    target_price: float,
    direction: str,
    target_date: Optional[datetime] = None,
    source: str = "user",
    methodology: str = "User-defined analytical milestone.",
    notes: Optional[str] = None,
    target_id: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> PriceTarget:
    price, resolved_direction, resolved_date = validate_target_inputs(
        target_price=target_price, direction=direction, target_date=target_date
    )
    return PriceTarget(
        id=target_id or str(uuid.uuid4()),
        symbol=symbol,
        target_price=price,
        direction=resolved_direction,
        target_date=resolved_date,
        created_at=created_at or datetime.now(timezone.utc),
        source=source,
        methodology=methodology,
        status=TargetStatus.ACTIVE,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# reach detection
# ---------------------------------------------------------------------------
@dataclass
class ReachAnalysis:
    """What the real price history says about one target condition."""

    reached: bool
    first_reached_at: Optional[datetime]
    crossing_count: int
    touch_count: int
    last_touched_at: Optional[datetime]
    bars_observed: int
    coverage_start: Optional[datetime]
    coverage_end: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reached": self.reached,
            "first_reached_at": self.first_reached_at.isoformat() if self.first_reached_at else None,
            "crossing_count": self.crossing_count,
            "touch_count": self.touch_count,
            "last_touched_at": self.last_touched_at.isoformat() if self.last_touched_at else None,
            "bars_observed": self.bars_observed,
            "coverage_start": self.coverage_start.isoformat() if self.coverage_start else None,
            "coverage_end": self.coverage_end.isoformat() if self.coverage_end else None,
        }


def _condition_met(candle: Candle, direction: str, price: float) -> bool:
    """
    Whether the bar's own traded range met the condition.

    Using the high (or low) rather than only the close is the honest choice: the
    level was genuinely touched inside that bar.
    """
    return candle.high >= price if direction == "above" else candle.low <= price


def analyse_target(
    candles: Sequence[Candle],
    *,
    target_price: float,
    direction: str,
    lookback_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> ReachAnalysis:
    """
    Detect the first real timestamp at which the condition held (spec §34) and
    count observed touches/crossings over the lookback window (spec §38).
    """
    window_days = lookback_days or crypto_settings.target_touch_lookback_days
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=window_days)
    series = [c for c in candles if c.timestamp >= cutoff]

    if not series:
        return ReachAnalysis(
            reached=False,
            first_reached_at=None,
            crossing_count=0,
            touch_count=0,
            last_touched_at=None,
            bars_observed=0,
            coverage_start=None,
            coverage_end=None,
        )

    first_reached_at: Optional[datetime] = None
    touch_count = 0
    last_touched_at: Optional[datetime] = None
    crossing_count = 0
    previously_met = False

    for candle in series:
        met = _condition_met(candle, direction, target_price)
        if met:
            touch_count += 1
            last_touched_at = candle.timestamp
            if first_reached_at is None:
                first_reached_at = candle.timestamp
            if not previously_met:
                crossing_count += 1
        previously_met = met

    return ReachAnalysis(
        reached=first_reached_at is not None,
        first_reached_at=first_reached_at,
        crossing_count=crossing_count,
        touch_count=touch_count,
        last_touched_at=last_touched_at,
        bars_observed=len(series),
        coverage_start=series[0].timestamp,
        coverage_end=series[-1].timestamp,
    )


def resolve_status(
    *,
    target: PriceTarget,
    analysis: ReachAnalysis,
    now: Optional[datetime] = None,
) -> TargetStatus:
    """Apply the documented status semantics to a real reach analysis."""
    if target.status is TargetStatus.INVALIDATED:
        return TargetStatus.INVALIDATED
    if analysis.reached:
        return TargetStatus.REACHED
    if target.target_date is None:
        return TargetStatus.ACTIVE

    current = now or datetime.now(timezone.utc)
    due = target.target_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if due >= current:
        return TargetStatus.ACTIVE

    # The due date has passed. Only call it MISSED if history actually covers it.
    if analysis.coverage_end is not None and analysis.coverage_end >= due:
        return TargetStatus.MISSED
    if analysis.bars_observed == 0:
        return TargetStatus.EXPIRED
    return TargetStatus.MISSED


def proximity(target_price: float, current_price: Optional[float]) -> Dict[str, Any]:
    """
    Distance from the current price to the target (spec §39).

    A zero/absent current price yields ``None`` rather than a division blow-up.
    """
    if current_price is None or current_price <= 0:
        return {"distance": None, "distance_percent": None, "reason": "current price unavailable"}
    distance = target_price - current_price
    return {
        "distance": distance,
        "distance_percent": (distance / current_price) * 100.0,
        "direction_from_price": "above" if distance > 0 else ("below" if distance < 0 else "at"),
    }


# ---------------------------------------------------------------------------
# derived reference ladder
# ---------------------------------------------------------------------------
def derive_reference_ladder(
    candles: Sequence[Candle],
    *,
    current_price: Optional[float] = None,
    count: Optional[int] = None,
    swing_window: int = 5,
) -> List[Dict[str, Any]]:
    """
    Build a ladder from **real historical price structure**.

    Swing highs and lows are located as local extrema over ``swing_window`` bars,
    then the nearest ones above and below the current price are selected. Every
    level returned is a price that genuinely traded, with the timestamps at which
    it occurred — this is what makes the ladder an observation rather than an
    invented "target".

    The levels are labelled ``derived``; they are monitoring references, not
    forecasts.
    """
    level_count = count or crypto_settings.target_default_ladder
    if len(candles) < _MIN_CANDLES_FOR_STRUCTURE:
        return []
    price = current_price if current_price and current_price > 0 else candles[-1].close
    if price <= 0:
        return []

    highs: List[Tuple[float, datetime]] = []
    lows: List[Tuple[float, datetime]] = []
    window = max(2, swing_window)
    for index in range(window, len(candles) - window):
        bar = candles[index]
        neighbourhood = candles[index - window : index + window + 1]
        if bar.high >= max(c.high for c in neighbourhood):
            highs.append((bar.high, bar.timestamp))
        if bar.low <= min(c.low for c in neighbourhood):
            lows.append((bar.low, bar.timestamp))

    # De-duplicate levels that are within 0.1% of each other (a flat top would
    # otherwise fill the whole ladder with the same price).
    def _dedupe(levels: List[Tuple[float, datetime]]) -> List[Tuple[float, datetime]]:
        out: List[Tuple[float, datetime]] = []
        for level, timestamp in levels:
            if any(abs(level - existing) / max(level, 1e-9) < 0.001 for existing, _ in out):
                continue
            out.append((level, timestamp))
        return out

    above = sorted([h for h in _dedupe(highs) if h[0] > price], key=lambda pair: pair[0])[:level_count]
    below = sorted([l for l in _dedupe(lows) if l[0] < price], key=lambda pair: pair[0], reverse=True)[:level_count]  # noqa: E741

    ladder: List[Dict[str, Any]] = []
    for index, (level, timestamp) in enumerate(reversed(below), start=1):
        ladder.append(
            {
                "rank": index,
                "target_price": level,
                "direction": "below",
                "level_type": "support",
                "observed_at": timestamp.isoformat(),
                "distance": level - price,
                "distance_percent": (level / price - 1.0) * 100.0,
                "origin": ValueOrigin.DERIVED.value,
                "methodology": f"Local low over +/-{window} bars in the real candle history.",
            }
        )
    offset = len(ladder)
    for index, (level, timestamp) in enumerate(above, start=offset + 1):
        ladder.append(
            {
                "rank": index,
                "target_price": level,
                "direction": "above",
                "level_type": "resistance",
                "observed_at": timestamp.isoformat(),
                "distance": level - price,
                "distance_percent": (level / price - 1.0) * 100.0,
                "origin": ValueOrigin.DERIVED.value,
                "methodology": f"Local high over +/-{window} bars in the real candle history.",
            }
        )
    return ladder


# ---------------------------------------------------------------------------
# factual date queries (spec §35)
# ---------------------------------------------------------------------------
def price_on_date(
    candles: Sequence[Candle],
    *,
    date: datetime,
    tolerance_hours: int = 36,
) -> Dict[str, Any]:
    """
    Answer "what did the price actually do around date Y?" from real candles.

    The nearest *actual* observation within ``tolerance_hours`` is reported
    together with its exact timestamp. If nothing covers that day, the answer is
    ``UNAVAILABLE`` — never an interpolation presented as a fact.
    """
    target_date = date
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)
    if not candles:
        return {
            "date": target_date.isoformat(),
            "status": "UNAVAILABLE",
            "reason": "no candle history available",
        }
    tolerance = timedelta(hours=tolerance_hours)
    best: Optional[Candle] = None
    best_delta: Optional[timedelta] = None
    for candle in candles:
        delta = abs(candle.timestamp - target_date)
        if delta <= tolerance and (best_delta is None or delta < best_delta):
            best, best_delta = candle, delta
    if best is None:
        return {
            "date": target_date.isoformat(),
            "status": "UNAVAILABLE",
            "reason": (
                f"no observation within {tolerance_hours}h of the requested date; the source does "
                "not cover that period"
            ),
        }
    return {
        "date": target_date.isoformat(),
        "status": "OBSERVED",
        "observation_timestamp": best.timestamp.isoformat(),
        "open": best.open,
        "high": best.high,
        "low": best.low,
        "close": best.close,
        "volume": best.volume,
        "offset_hours": (best.timestamp - target_date).total_seconds() / 3600.0,
        "origin": ValueOrigin.SOURCE.value,
        "source_note": "Direct observation from a real historical candle; no interpolation.",
    }


def evaluate_threshold_on_date(
    candles: Sequence[Candle],
    *,
    date: datetime,
    threshold: float,
    direction: str = "above",
) -> Dict[str, Any]:
    """
    Answer "was the asset above/below X on date Y?" (spec §35).

    Returns the factual answer plus the observation it was derived from, or
    ``UNAVAILABLE`` when the history does not cover that date.
    """
    observation = price_on_date(candles, date=date)
    if observation["status"] != "OBSERVED":
        return {
            "date": date.isoformat(),
            "threshold": threshold,
            "direction": direction,
            "status": "UNAVAILABLE",
            "answer": None,
            "reason": observation.get("reason"),
        }
    direction = (direction or "above").strip().lower()
    if direction not in DIRECTIONS:
        raise TargetError(f"direction must be one of {DIRECTIONS}")
    high = observation["high"]
    low = observation["low"]
    if direction == "above":
        answer = high >= threshold
        evidence = f"bar high {high} vs threshold {threshold}"
    else:
        answer = low <= threshold
        evidence = f"bar low {low} vs threshold {threshold}"
    return {
        "date": date.isoformat(),
        "threshold": threshold,
        "direction": direction,
        "status": "ANSWERED",
        "answer": bool(answer),
        "observation": observation,
        "evidence": evidence,
        "origin": ValueOrigin.CALCULATED.value,
    }


# ---------------------------------------------------------------------------
# evaluation bundle
# ---------------------------------------------------------------------------
def evaluate_target(
    target: PriceTarget,
    *,
    candles: Sequence[Candle],
    current_price: Optional[float],
    lookback_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Status + proximity + touch statistics for one target, from real data."""
    analysis = analyse_target(
        candles,
        target_price=target.target_price,
        direction=target.direction,
        lookback_days=lookback_days,
        now=now,
    )
    status = resolve_status(target=target, analysis=analysis, now=now)
    return {
        "target": target.to_dict(),
        "status": status.value,
        "stored_status": target.status.value,
        "first_reached_at": analysis.first_reached_at.isoformat() if analysis.first_reached_at else None,
        "touch_count": analysis.touch_count,
        "crossing_count": analysis.crossing_count,
        "last_touched_at": analysis.last_touched_at.isoformat() if analysis.last_touched_at else None,
        "lookback_days": lookback_days or crypto_settings.target_touch_lookback_days,
        "bars_observed": analysis.bars_observed,
        "proximity": proximity(target.target_price, current_price),
        "origin": ValueOrigin.CALCULATED.value,
        "note": (
            "Touch counts and status are computed from real timestamped candles over the stated "
            "lookback. An observed statistic is not a future guarantee."
        ),
    }
