"""
OHLCV normalization, gap detection, roll-up aggregation and downsampling.

The provider payload is parsed into a validated :class:`~app.crypto.schemas.Candle`
list. Malformed records are dropped and *counted* (never repaired with a guess);
duplicate timestamps are collapsed keeping the last observation; out-of-order
rows are re-sorted. The resulting gaps are reported, not filled.

Aggregation follows the standard OHLCV roll-up rules (spec §6): open = first
open in the bucket, high = max high, low = min low, close = last close,
volume = sum, timestamp = bucket start. A bucket with no source candle stays
absent — the gap remains visible downstream.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.crypto.schemas import Candle, DataGapReport

logger = logging.getLogger("neural_market.crypto.normalization")


def _to_float(value: Any) -> Optional[float]:
    """Coerce a provider number to float, returning None for junk/NaN/inf."""
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return result


def _to_millis(value: Any) -> Optional[int]:
    """Provider timestamps arrive as ms ints, s ints or ISO strings."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            number = int(text)
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
    else:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
    # Heuristic: anything below ~1e11 is seconds, not milliseconds.
    return number if number > 10_000_000_000 else number * 1000


def parse_binance_kline(row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Binance kline array -> raw dict. Returns None when unusable."""
    if not row or len(row) < 6:
        return None
    return {
        "timestamp": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": row[5],
    }


def parse_coingecko_ohlc(row: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """CoinGecko OHLC array [ts, o, h, l, c] -> raw dict (no volume published)."""
    if not row or len(row) < 5:
        return None
    return {
        "timestamp": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "volume": 0.0,
    }


def normalize_candles(
    raw: Iterable[Dict[str, Any]],
    *,
    expected_interval_seconds: Optional[int] = None,
) -> Tuple[List[Candle], Dict[str, int]]:
    """
    Validate + order a raw candle list.

    Returns ``(candles, stats)`` where stats tallies what was dropped and why, so
    the caller can surface "data rejected" instead of silently trusting input.
    """
    stats = {
        "received": 0,
        "accepted": 0,
        "malformed": 0,
        "invalid_invariant": 0,
        "duplicates": 0,
        "out_of_order": 0,
    }
    by_ts: Dict[int, Candle] = {}
    order: List[int] = []
    previous_ts: Optional[int] = None

    for row in raw:
        if not isinstance(row, dict):
            stats["malformed"] += 1
            continue
        stats["received"] += 1
        millis = _to_millis(row.get("timestamp"))
        o = _to_float(row.get("open"))
        h = _to_float(row.get("high"))
        low = _to_float(row.get("low"))
        c = _to_float(row.get("close"))
        v = _to_float(row.get("volume"))
        if millis is None or None in (o, h, low, c):
            stats["malformed"] += 1
            continue
        try:
            candle = Candle(
                timestamp=datetime.fromtimestamp(millis / 1000, tz=timezone.utc),
                open=o, high=h, low=low, close=c, volume=v if v is not None else 0.0,
            )
        except ValueError:
            # Structural invariant violated (high<max(o,c) or low>min(o,c)).
            stats["invalid_invariant"] += 1
            continue

        if millis in by_ts:
            stats["duplicates"] += 1
            by_ts[millis] = candle  # keep the newest observation for the slot
            continue
        by_ts[millis] = candle
        order.append(millis)
        if previous_ts is not None and millis < previous_ts:
            stats["out_of_order"] += 1
        previous_ts = millis

    candles = [by_ts[ts] for ts in sorted(by_ts)]
    stats["accepted"] = len(candles)
    return candles, stats


def detect_gaps(
    candles: Sequence[Candle],
    *,
    interval_seconds: int,
    timeframe: str,
) -> DataGapReport:
    """
    Expected-vs-received interval audit for one timeframe (spec §7).

    ``expected`` spans the first to the last timestamp inclusive, so a series
    that simply *starts late* is not reported as having missing candles before
    the provider's own history — it reports what is missing inside the range the
    source actually covered.
    """
    if not candles or interval_seconds <= 0:
        return DataGapReport(
            timeframe=timeframe,
            expected_intervals=0,
            received_intervals=len(candles),
            missing_intervals=0,
            duplicate_intervals=0,
            out_of_order=0,
            largest_gap_seconds=0.0,
            completeness=0.0,
            label="DATA UNAVAILABLE",
        )
    span_seconds = (candles[-1].timestamp - candles[0].timestamp).total_seconds()
    expected = int(span_seconds // interval_seconds) + 1
    received = len(candles)
    missing = max(0, expected - received)
    largest = 0.0
    for previous, current in zip(candles, candles[1:]):
        delta = (current.timestamp - previous.timestamp).total_seconds()
        largest = max(largest, delta - interval_seconds)
    completeness = min(1.0, received / expected) if expected else 0.0
    return DataGapReport(
        timeframe=timeframe,
        expected_intervals=expected,
        received_intervals=received,
        missing_intervals=missing,
        duplicate_intervals=0,
        out_of_order=0,
        largest_gap_seconds=round(max(0.0, largest), 3),
        completeness=round(completeness, 6),
        label="DATA COMPLETE" if missing == 0 else "DATA GAP DETECTED",
    )


def aggregate_candles(candles: Sequence[Candle], target_seconds: int) -> List[Candle]:
    """
    Roll a lower-resolution series up to ``target_seconds`` buckets.

    Only buckets that contain at least one real candle are emitted, so an
    aggregation never invents a candle for a period the source did not cover.
    """
    if target_seconds <= 0 or not candles:
        return list(candles)
    buckets: Dict[int, List[Candle]] = {}
    bucket_ms = target_seconds * 1000
    for candle in candles:
        key = (candle.epoch_ms // bucket_ms) * bucket_ms
        buckets.setdefault(key, []).append(candle)

    out: List[Candle] = []
    for key in sorted(buckets):
        group = buckets[key]
        try:
            out.append(
                Candle(
                    timestamp=datetime.fromtimestamp(key / 1000, tz=timezone.utc),
                    open=group[0].open,
                    high=max(c.high for c in group),
                    low=min(c.low for c in group),
                    close=group[-1].close,
                    volume=sum(c.volume for c in group),
                )
            )
        except ValueError as exc:  # pragma: no cover - defensive
            logger.debug("skipping inconsistent bucket %s: %s", key, exc)
    return out


def downsample_for_display(candles: Sequence[Candle], target_points: int) -> List[Candle]:
    """
    Reduce a series for charting **without discarding extrema**.

    Buckets the series and, for each bucket, keeps the first, last and the
    highest-high/lowest-low candles. Nothing is averaged, so a spike is never
    smoothed away (spec §66).
    """
    if target_points <= 0 or len(candles) <= target_points:
        return list(candles)

    out: List[Candle] = []
    total = len(candles)
    bucket_count = max(1, target_points // 3)
    size = max(1, total // bucket_count)
    for start in range(0, total, size):
        group = list(candles[start : start + size])
        if not group:
            continue
        picks = {0, len(group) - 1, max(range(len(group)), key=lambda i: group[i].high),
                 min(range(len(group)), key=lambda i: group[i].low)}
        out.extend(group[i] for i in sorted(picks))
    # De-duplicate while keeping order (a bucket may share an index).
    seen: set = set()
    unique: List[Candle] = []
    for candle in out:
        if candle.epoch_ms in seen:
            continue
        seen.add(candle.epoch_ms)
        unique.append(candle)
    return unique


def candle_closes(candles: Sequence[Candle]) -> List[float]:
    return [c.close for c in candles]


def candle_arrays(candles: Sequence[Candle]) -> Dict[str, List[float]]:
    """Column-oriented view for pandas/NumPy consumers."""
    return {
        "open": [c.open for c in candles],
        "high": [c.high for c in candles],
        "low": [c.low for c in candles],
        "close": [c.close for c in candles],
        "volume": [c.volume for c in candles],
        "timestamp": [c.timestamp.isoformat() for c in candles],
    }
