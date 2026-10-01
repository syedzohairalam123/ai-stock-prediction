"""
Shared test fixtures: deterministic synthetic candles.

Fixtures here are used ONLY inside tests (spec §0 permits fixtures for unit and
integration tests; no production code path imports this module). The series is
deterministic — a seeded sine wave with drift — so assertions can be exact and a
failing test is always reproducible.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import List

from app.crypto.schemas import Candle

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candles(
    count: int = 220,
    *,
    start: float = 100.0,
    step_seconds: int = 3600,
    amplitude: float = 1.0,
    drift: float = 0.0005,
    volume: float = 10.0,
    phase: float = 0.0,
) -> List[Candle]:
    """A deterministic price series: gentle drift plus a sine oscillation."""
    candles: List[Candle] = []
    price = start
    for index in range(count):
        open_price = price
        wave = math.sin(phase + index / 6.0) * amplitude
        close = max(0.01, open_price * (1.0 + drift) + wave)
        high = max(open_price, close) + amplitude * 0.5
        low = min(open_price, close) - amplitude * 0.5
        candles.append(
            Candle(
                timestamp=EPOCH + timedelta(seconds=step_seconds * index),
                open=round(open_price, 8),
                high=round(high, 8),
                low=round(max(0.0, low), 8),
                close=round(close, 8),
                volume=volume + index % 3,
            )
        )
        price = close
    return candles


def flat_candles(count: int = 50, *, price: float = 50.0, step_seconds: int = 3600) -> List[Candle]:
    """A perfectly flat series (for degenerate-window edge cases)."""
    return [
        Candle(
            timestamp=EPOCH + timedelta(seconds=step_seconds * index),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1.0,
        )
        for index in range(count)
    ]


def with_gaps(candles: List[Candle], *, drop_indices: List[int], step_seconds: int = 3600) -> List[Candle]:
    """Remove specific candles so the gap detector has something real to find."""
    return [c for i, c in enumerate(candles) if i not in set(drop_indices)]


def out_of_order(candles: List[Candle]) -> List[Candle]:
    """Swap two neighbours so the normalizer must re-sort."""
    if len(candles) < 3:
        return list(candles)
    shuffled = list(candles)
    shuffled[1], shuffled[2] = shuffled[2], shuffled[1]
    return shuffled


def duplicated(candles: List[Candle]) -> List[Candle]:
    """Duplicate one candle so the normalizer must collapse it."""
    if not candles:
        return []
    doubled = list(candles)
    doubled.insert(1, candles[1])
    return doubled
