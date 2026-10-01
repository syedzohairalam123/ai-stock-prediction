"""Unit tests for indicators, volatility, trend and quality (spec §95)."""

from __future__ import annotations

import math

import pytest

from app.crypto.indicators import (
    atr,
    cumulative_return,
    ema,
    log_returns,
    range_position,
    rsi,
    simple_returns,
    sma,
    true_range,
)
from app.crypto.quality import assess, freshness_status, origin_of
from app.crypto.schemas import DataStatus, QualityLabel, VolatilityRegime
from app.crypto.tests.synthetic import flat_candles, make_candles
from app.crypto.trend import MicroTrendEngine, summarize_multi_timeframe
from app.crypto.volatility import (
    classify_regime,
    realized_volatility,
    range_volatility,
    rolling_volatility,
    volatility_engine,
    volatility_percentile,
)


class TestReturns:
    def test_simple_return(self):
        assert simple_returns([100.0, 110.0])[1] == pytest.approx(0.10)

    def test_log_return(self):
        assert log_returns([100.0, 110.0])[1] == pytest.approx(math.log(1.10))

    def test_zero_previous_price_is_none(self):
        assert simple_returns([0.0, 110.0])[1] is None
        assert log_returns([0.0, 110.0])[1] is None

    def test_first_row_has_no_previous(self):
        assert simple_returns([1.0, 2.0])[0] is None
        assert log_returns([1.0, 2.0])[0] is None

    def test_cumulative_return(self):
        assert cumulative_return([100.0, 110.0, 121.0]) == pytest.approx(0.21)


class TestMovingAverages:
    def test_sma_aligned(self):
        result = sma([1.0, 2.0, 3.0, 4.0], 2)
        assert result[0] is None
        assert result[1] == pytest.approx(1.5)
        assert result[3] == pytest.approx(3.5)

    def test_sma_too_short_is_all_none(self):
        assert all(v is None for v in sma([1.0, 2.0], 5))

    def test_ema_seeded_with_sma(self):
        result = ema([2.0, 4.0, 6.0, 8.0], 2)
        assert result[1] == pytest.approx(3.0)  # first SMA seed
        # alpha = 2/(period+1) = 2/3; the newest close carries the alpha weight,
        # so index 2 = 6·(2/3) + 3·(1/3) = 5.0.
        assert result[2] == pytest.approx(5.0)

    def test_ema_too_short(self):
        assert all(v is None for v in ema([1.0], 2))


class TestATR:
    def test_true_range_definition(self):
        highs = [12.0, 13.0]
        lows = [10.0, 9.0]
        closes = [11.0, 12.5]
        tr = true_range(highs, lows, closes)
        assert tr[0] == pytest.approx(2.0)
        # max(13-9, |13-11|, |9-11|) = 4
        assert tr[1] == pytest.approx(4.0)

    def test_atr_constant_range(self):
        candles = flat_candles(30, price=50.0)
        highs = [c.high + 1 for c in candles]
        lows = [c.low - 1 for c in candles]
        closes = [c.close for c in candles]
        values = atr(highs, lows, closes, 14)
        assert values[-1] == pytest.approx(2.0)

    def test_atr_insufficient_data(self):
        assert all(v is None for v in atr([1, 2], [1, 2], [1, 2], 14))


class TestRSI:
    def test_all_gains_is_100(self):
        closes = [float(i) for i in range(1, 30)]
        values = rsi(closes, 14)
        assert values[-1] == 100.0

    def test_all_losses_is_zero(self):
        closes = [float(-i) for i in range(1, 30)]
        values = rsi(closes, 14)
        assert values[-1] == 0.0

    def test_flat_is_neutral(self):
        closes = [10.0] * 30
        values = rsi(closes, 14)
        assert values[-1] == 50.0

    def test_range_bounds(self):
        closes = [c.close for c in make_candles(60, amplitude=0.8)]
        for value in rsi(closes, 14):
            if value is not None:
                assert 0.0 <= value <= 100.0


class TestRangeHelpers:
    def test_range_position_bounds(self):
        candles = make_candles(30)
        position = range_position(
            [c.high for c in candles], [c.low for c in candles], [c.close for c in candles], 20
        )
        assert 0.0 <= position <= 1.0

    def test_range_position_flat_range_is_none(self):
        candles = flat_candles(10)
        assert (
            range_position([c.high for c in candles], [c.low for c in candles], [c.close for c in candles], 5)
            is None
        )


class TestVolatility:
    def test_realized_volatility_positive_for_varied_series(self):
        candles = make_candles(120, amplitude=1.0)
        value = rolling_volatility([c.close for c in candles], window=20, duration_seconds=3600)
        assert value is not None and value > 0

    def test_realized_volatility_flat_is_zero(self):
        value = rolling_volatility([50.0] * 40, window=20, duration_seconds=3600)
        assert value == pytest.approx(0.0)

    def test_realized_volatility_insufficient(self):
        assert realized_volatility([0.01], window=20, duration_seconds=3600) is None

    def test_annualisation_scales_with_timeframe(self):
        # The annualisation factor sqrt(periods_per_year) is a pure multiplier on
        # the SAME per-bar std, so feed identical returns through both durations:
        # hourly uses sqrt(8760), daily uses sqrt(365), and the ratio between the
        # two annualised figures must be exactly sqrt(365/8760) = 1/sqrt(24).
        from app.crypto.volatility import realized_volatility as rv

        returns = [r for r in log_returns([c.close for c in make_candles(80)]) if r is not None]
        hourly = rv(returns, window=60, duration_seconds=3600)
        daily = rv(returns, window=60, duration_seconds=86400)
        assert daily / hourly == pytest.approx(math.sqrt(365.0 / (365.0 * 24.0)))
        # And sanity: the annualised hourly figure is the larger one.
        assert hourly > daily

    def test_range_volatility(self):
        candles = make_candles(30)
        value = range_volatility(
            [c.high for c in candles], [c.low for c in candles], [c.close for c in candles], window=20
        )
        assert value is not None and value > 0

    def test_percentile_rank(self):
        history = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        # Mid-rank definition: 4.0 sits below 3 of 8 values with no ties → 37.5.
        assert volatility_percentile(history, 4.0) == pytest.approx((3 + 0.5 * 1) / 8 * 100)
        assert volatility_percentile(history, 10.0) == pytest.approx(100.0)
        assert volatility_percentile(history, 0.5) == pytest.approx(0.0)

    def test_regime_classification_uses_own_distribution(self):
        history = [float(i) for i in range(1, 101)]
        percentile = volatility_percentile(history, 96.0)
        assert classify_regime(percentile=percentile) == VolatilityRegime.EXTREME
        assert classify_regime(percentile=50.0) == VolatilityRegime.NORMAL
        assert classify_regime(percentile=5.0) == VolatilityRegime.LOW
        assert classify_regime(percentile=None) == VolatilityRegime.INSUFFICIENT_DATA

    def test_engine_snapshot(self):
        candles = make_candles(200)
        snapshot = volatility_engine.snapshot(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            duration_seconds=3600,
            timeframe="1h",
        )
        assert snapshot.realized_volatility is not None
        assert snapshot.regime in {r for r in VolatilityRegime}
        assert snapshot.sample_size == 200
        assert snapshot.data_status == DataStatus.LIVE

    def test_engine_snapshot_empty(self):
        snapshot = volatility_engine.snapshot(
            highs=[], lows=[], closes=[], duration_seconds=3600, timeframe="1h"
        )
        assert snapshot.data_status == DataStatus.UNAVAILABLE


class TestMicroTrend:
    def test_insufficient_data_is_honest(self):
        result = MicroTrendEngine().analyse(
            highs=[1, 2], lows=[1, 2], closes=[1, 2], volumes=[1, 2],
            timeframe="5m", duration_seconds=300,
        )
        assert result.direction.value == "INSUFFICIENT_DATA"
        assert result.confidence == 0.0

    def test_uptrend_detected(self):
        candles = make_candles(120, drift=0.01, amplitude=0.05)
        result = MicroTrendEngine().analyse(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            volumes=[c.volume for c in candles],
            timeframe="1h",
            duration_seconds=3600,
            realized_volatility=0.001,
        )
        assert result.direction.value == "UP"
        assert 0 < result.strength <= 1
        assert 0 < result.confidence <= 0.9  # capped, never certainty

    def test_downtrend_detected(self):
        candles = make_candles(120, drift=-0.01, amplitude=0.05)
        result = MicroTrendEngine().analyse(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            volumes=[c.volume for c in candles],
            timeframe="1h",
            duration_seconds=3600,
            realized_volatility=0.001,
        )
        assert result.direction.value == "DOWN"

    def test_flat_series_is_sideways(self):
        candles = flat_candles(60)
        result = MicroTrendEngine().analyse(
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            volumes=[c.volume for c in candles],
            timeframe="1h",
            duration_seconds=3600,
            realized_volatility=0.05,
        )
        assert result.direction.value == "SIDEWAYS"

    def test_multi_timeframe_summary_reports_conflicts(self):
        rows = [
            {"timeframe": "5m", "trend": "UP"},
            {"timeframe": "1h", "trend": "UP"},
            {"timeframe": "1d", "trend": "DOWN"},
        ]
        summary = summarize_multi_timeframe(rows)
        assert summary["short_term"] == "UP"
        assert summary["broader"] == "DOWN"
        assert summary["aligned"] is False

    def test_multi_timeframe_summary_empty(self):
        assert summarize_multi_timeframe([])["short_term"] is None


class TestQuality:
    def test_fresh_timestamp_is_live(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        assert freshness_status(now - timedelta(seconds=10)) == DataStatus.LIVE

    def test_old_timestamp_is_stale(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        assert freshness_status(now - timedelta(hours=6)) == DataStatus.STALE

    def test_slow_timeframe_gets_bar_grace(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        # A daily bar that closed 4 hours ago is legitimate, not DELAYED.
        assert (
            freshness_status(now - timedelta(hours=4), bar_seconds=86400) == DataStatus.LIVE
        )

    def test_missing_timestamp_is_unavailable(self):
        assert freshness_status(None) == DataStatus.UNAVAILABLE

    def test_assess_no_data(self):
        result = assess(source_timestamp=None, candle_count=0)
        assert result.label == QualityLabel.UNAVAILABLE

    def test_assess_penalises_gaps(self):
        from datetime import datetime, timedelta, timezone

        from app.crypto.normalization import detect_gaps
        from app.crypto.tests.synthetic import with_gaps

        complete = detect_gaps(
            make_candles(48, step_seconds=3600), interval_seconds=3600, timeframe="1h"
        )
        # Drop interior bars so the covered span genuinely has holes.
        holed = with_gaps(
            make_candles(48, step_seconds=3600), drop_indices=list(range(5, 16)), step_seconds=3600
        )
        gapped = detect_gaps(holed, interval_seconds=3600, timeframe="1h")
        assert gapped.missing_intervals > 0
        stamp = datetime.now(timezone.utc) - timedelta(seconds=30)
        clean = assess(source_timestamp=stamp, gap_report=complete, candle_count=48)
        broken = assess(source_timestamp=stamp, gap_report=gapped, candle_count=len(holed))
        assert clean.label == QualityLabel.HIGH
        assert broken.label in {QualityLabel.MEDIUM, QualityLabel.LOW}

    def test_origin_table(self):
        from app.crypto.quality import origin_of as _origin

        assert _origin("price").value == "SOURCE"
        assert _origin("forecast").value == "MODELLED"
        assert _origin("atr").value == "CALCULATED"
        assert _origin("trend_direction").value == "DERIVED"
        assert _origin("unknown-key").value == "UNAVAILABLE"
