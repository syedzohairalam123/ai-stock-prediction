"""Unit tests for normalization, aggregation, gap detection and downsampling (spec §95, §96)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.crypto.normalization import (
    aggregate_candles,
    candle_closes,
    detect_gaps,
    downsample_for_display,
    normalize_candles,
    parse_binance_kline,
    parse_coingecko_ohlc,
)
from app.crypto.schemas import Candle
from app.crypto.tests.synthetic import duplicated, make_candles, out_of_order, with_gaps

UTC = timezone.utc


def _raw(candles, **overrides):
    rows = []
    for c in candles:
        row = {"timestamp": c.epoch_ms, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
        row.update(overrides)
        rows.append(row)
    return rows


class TestNormalization:
    def test_accepts_a_clean_series(self):
        candles = make_candles(30)
        result, stats = normalize_candles(_raw(candles))
        assert stats["received"] == 30
        assert stats["accepted"] == 30
        assert [c.epoch_ms for c in result] == [c.epoch_ms for c in candles]

    def test_rejects_malformed_records(self):
        candles = make_candles(5)
        rows = _raw(candles)
        rows.append({"timestamp": "not-a-time", "open": 1, "high": 2, "low": 1, "close": 2})
        rows.append({"open": 1, "high": 2, "low": 1, "close": 2})
        result, stats = normalize_candles(rows)
        assert stats["malformed"] == 2
        assert stats["accepted"] == 5
        assert len(result) == 5

    def test_rejects_invariant_violations(self):
        candles = make_candles(5)
        rows = _raw(candles)
        rows.append({"timestamp": candles[-1].epoch_ms + 3_600_000, "open": 10, "high": 5, "low": 1, "close": 9})
        result, stats = normalize_candles(rows)
        assert stats["invalid_invariant"] == 1
        assert len(result) == 5

    def test_rejects_nan_and_infinity(self):
        candles = make_candles(3)
        rows = _raw(candles)
        rows.append({"timestamp": candles[-1].epoch_ms + 3_600_000, "open": float("nan"), "high": 2, "low": 1, "close": 2})
        rows.append({"timestamp": candles[-1].epoch_ms + 7_200_000, "open": 1, "high": float("inf"), "low": 1, "close": 2})
        result, stats = normalize_candles(rows)
        assert stats["malformed"] == 2
        assert len(result) == 3

    def test_collapses_duplicates_keeping_last(self):
        candles = make_candles(6)
        result, stats = normalize_candles(_raw(duplicated(candles)))
        assert stats["duplicates"] == 1
        assert stats["accepted"] == 6

    def test_sorts_out_of_order_rows(self):
        candles = make_candles(8)
        result, stats = normalize_candles(_raw(out_of_order(candles)))
        assert stats["out_of_order"] >= 1
        stamps = [c.epoch_ms for c in result]
        assert stamps == sorted(stamps)

    def test_handles_second_and_iso_timestamps(self):
        candles = make_candles(3)
        rows = _raw(candles)
        rows[0]["timestamp"] = rows[0]["timestamp"] // 1000  # seconds
        rows[1]["timestamp"] = datetime.fromtimestamp(rows[1]["timestamp"] / 1000, tz=UTC).isoformat()
        result, stats = normalize_candles(rows)
        assert stats["accepted"] == 3
        assert [c.epoch_ms for c in result] == [c.epoch_ms for c in candles]

    def test_candle_closes_helper(self):
        candles = make_candles(4)
        assert candle_closes(candles) == [c.close for c in candles]


class TestParsing:
    def test_parse_binance_kline(self):
        row = [1790769600000, "83915.17", "83942.01", "83831.82", "83838.00", "39.30701000",
               1790769899999, "3299495.5", 210, 0, "0", "0"]
        parsed = parse_binance_kline(row)
        assert parsed["timestamp"] == 1790769600000
        assert parsed["close"] == "83838.00"

    def test_parse_binance_kline_rejects_short_rows(self):
        assert parse_binance_kline([1, 2, 3]) is None
        assert parse_binance_kline([]) is None

    def test_parse_coingecko_ohlc_has_no_volume(self):
        parsed = parse_coingecko_ohlc([1790769600000, 100, 110, 95, 105])
        assert parsed["volume"] == 0.0
        assert parsed["high"] == 110


class TestGaps:
    def test_complete_series(self):
        candles = make_candles(48, step_seconds=3600)
        report = detect_gaps(candles, interval_seconds=3600, timeframe="1h")
        assert report.label == "DATA COMPLETE"
        assert report.missing_intervals == 0
        assert report.completeness == pytest.approx(1.0)

    def test_detects_missing_candles(self):
        candles = with_gaps(make_candles(48, step_seconds=3600), drop_indices=[10, 11, 30], step_seconds=3600)
        report = detect_gaps(candles, interval_seconds=3600, timeframe="1h")
        assert report.label == "DATA GAP DETECTED"
        assert report.missing_intervals == 3
        assert report.completeness < 1.0
        assert report.largest_gap_seconds >= 2 * 3600

    def test_empty_series_reports_unavailable(self):
        report = detect_gaps([], interval_seconds=3600, timeframe="1h")
        assert report.label == "DATA UNAVAILABLE"
        assert report.completeness == 0.0


class TestAggregation:
    def test_rollup_rules(self):
        candles = make_candles(8, step_seconds=900)  # 15m of 5m bars -> wait, use 900s bars
        # 4 bars of 900s -> one 3600s bucket
        bucket = aggregate_candles(candles[:4], 3600)
        assert len(bucket) == 1
        assert bucket[0].open == candles[0].open
        assert bucket[0].close == candles[3].close
        assert bucket[0].high == max(c.high for c in candles[:4])
        assert bucket[0].low == min(c.low for c in candles[:4])
        assert bucket[0].volume == sum(c.volume for c in candles[:4])
        assert bucket[0].epoch_ms == candles[0].epoch_ms // 3_600_000 * 3_600_000

    def test_never_invents_empty_buckets(self):
        candles = with_gaps(make_candles(20, step_seconds=600), drop_indices=[5, 6, 7], step_seconds=600)
        buckets = aggregate_candles(candles, 3600)
        # Every emitted bucket must contain at least one real source candle —
        # buckets that would fall entirely inside a gap are never invented.
        real_buckets = {c.epoch_ms // 3_600_000 for c in candles}
        assert {b.epoch_ms // 3_600_000 for b in buckets} == real_buckets
        # And the bucket spanning the dropped bars carries only the surviving candles.
        gap_bucket_ms = candles[4].epoch_ms // 3_600_000 * 3_600_000
        spanning = next(b for b in buckets if b.epoch_ms == gap_bucket_ms)
        survivors = [c for c in candles if c.epoch_ms // 3_600_000 * 3_600_000 == gap_bucket_ms]
        assert spanning.volume == sum(c.volume for c in survivors)
        assert spanning.high == max(c.high for c in survivors)

    def test_identity_when_target_equals_source(self):
        candles = make_candles(10, step_seconds=3600)
        assert aggregate_candles(candles, 3600) == list(candles)


class TestDownsampling:
    def test_preserves_extrema(self):
        candles = make_candles(600, step_seconds=300)
        reduced = downsample_for_display(candles, 60)
        assert 0 < len(reduced) < len(candles)
        assert max(c.high for c in reduced) == pytest.approx(max(c.high for c in candles))
        assert min(c.low for c in reduced) == pytest.approx(min(c.low for c in candles))
        assert reduced[0].epoch_ms <= candles[1].epoch_ms
        assert reduced[-1].epoch_ms == candles[-1].epoch_ms

    def test_noop_when_under_target(self):
        candles = make_candles(20)
        assert downsample_for_display(candles, 100) == list(candles)
