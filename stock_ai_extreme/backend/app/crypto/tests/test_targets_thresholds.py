"""Target + threshold engine tests (spec §95)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.crypto import thresholds as thresholds_mod
from app.crypto import targets as targets_mod
from app.crypto.schemas import TargetStatus
from app.crypto.tests.synthetic import EPOCH, make_candles

UTC = timezone.utc


class TestTargetValidation:
    def test_rejects_nan_infinity_negative(self):
        for bad in (float("nan"), float("inf"), 0, -5):
            with pytest.raises(targets_mod.TargetError):
                targets_mod.validate_target_inputs(target_price=bad, direction="above")

    def test_rejects_bad_direction(self):
        with pytest.raises(targets_mod.TargetError):
            targets_mod.validate_target_inputs(target_price=100, direction="sideways")

    def test_rejects_malformed_date(self):
        with pytest.raises(targets_mod.TargetError):
            targets_mod.validate_target_inputs(target_price=100, direction="above", target_date="not-a-date")

    def test_accepts_valid_definition(self):
        price, direction, date = targets_mod.validate_target_inputs(
            target_price="100.5", direction="ABOVE", target_date="2026-12-31"
        )
        assert price == 100.5
        assert direction == "above"
        assert date is not None and date.tzinfo is not None


class TestReachDetection:
    @staticmethod
    def _series_with_single_touch(indices, *, count=100):
        """A series whose natural highs stay below the threshold, with the given
        bars bumped above it — so touches are exactly the bars we injected."""
        candles = make_candles(count, start=100.0, step_seconds=3600, amplitude=0.5)
        natural_max = max(c.high for c in candles)
        threshold = natural_max + 5.0
        bumped = list(candles)
        for index in indices:
            bumped[index] = bumped[index].model_copy(
                update={"high": threshold + 1.0, "close": threshold + 0.5}
            )
        return bumped, threshold

    def test_first_reached_uses_real_timestamp(self):
        bumped, threshold = self._series_with_single_touch([50])
        analysis = targets_mod.analyse_target(bumped, target_price=threshold, direction="above")
        assert analysis.reached
        assert analysis.first_reached_at == bumped[50].timestamp
        assert analysis.crossing_count == 1
        assert analysis.touch_count == 1
        assert analysis.last_touched_at == bumped[50].timestamp

    def test_multiple_touches_counted(self):
        bumped, threshold = self._series_with_single_touch([20, 40, 60])
        analysis = targets_mod.analyse_target(bumped, target_price=threshold, direction="above")
        assert analysis.touch_count == 3
        assert analysis.crossing_count == 3
        assert analysis.last_touched_at == bumped[60].timestamp

    def test_never_reached(self):
        candles = make_candles(100, start=100.0)
        analysis = targets_mod.analyse_target(candles, target_price=1000.0, direction="above")
        assert not analysis.reached
        assert analysis.first_reached_at is None
        assert analysis.touch_count == 0

    def test_below_condition_uses_lows(self):
        candles = make_candles(100, start=100.0, step_seconds=3600)
        bumped = list(candles)
        bumped[30] = bumped[30].model_copy(update={"low": 90.0, "close": 92.0})
        analysis = targets_mod.analyse_target(bumped, target_price=95.0, direction="below")
        assert analysis.reached
        assert analysis.first_reached_at == bumped[30].timestamp


class TestStatusResolution:
    def _target(self, *, target_date=None, status=TargetStatus.ACTIVE):
        return targets_mod.build_target(
            symbol="TEST", target_price=105.0, direction="above",
            target_date=target_date, target_id="t1",
            created_at=EPOCH,
        ).model_copy(update={"status": status})

    def test_reached_wins(self):
        bumped, threshold = TestReachDetection._series_with_single_touch([50])
        analysis = targets_mod.analyse_target(bumped, target_price=threshold, direction="above")
        assert targets_mod.resolve_status(target=self._target(), analysis=analysis) == TargetStatus.REACHED

    def test_active_before_due_date(self):
        candles = make_candles(100, start=100.0)
        analysis = targets_mod.analyse_target(candles, target_price=1000.0, direction="above")
        future = datetime.now(UTC) + timedelta(days=10)
        assert targets_mod.resolve_status(target=self._target(target_date=future), analysis=analysis) == TargetStatus.ACTIVE

    def test_missed_when_history_covers_due_date(self):
        candles = make_candles(100, start=100.0, step_seconds=3600)
        analysis = targets_mod.analyse_target(candles, target_price=1000.0, direction="above")
        # Due date inside the covered range but in the past.
        past = datetime.now(UTC) - timedelta(hours=24)
        assert targets_mod.resolve_status(target=self._target(target_date=past), analysis=analysis) == TargetStatus.MISSED

    def test_invalidated_stays_invalidated(self):
        bumped, threshold = TestReachDetection._series_with_single_touch([50])
        analysis = targets_mod.analyse_target(bumped, target_price=threshold, direction="above")
        assert (
            targets_mod.resolve_status(
                target=self._target(status=TargetStatus.INVALIDATED), analysis=analysis
            )
            == TargetStatus.INVALIDATED
        )


class TestProximity:
    def test_distance_and_percent(self):
        result = targets_mod.proximity(110.0, 100.0)
        assert result["distance"] == pytest.approx(10.0)
        assert result["distance_percent"] == pytest.approx(10.0)

    def test_zero_current_price_is_safe(self):
        assert targets_mod.proximity(110.0, 0.0)["distance"] is None
        assert targets_mod.proximity(110.0, None)["distance_percent"] is None


class TestDerivedLadder:
    def test_ladder_from_real_swing_structure(self):
        candles = make_candles(300, start=100.0, amplitude=2.0)
        ladder = targets_mod.derive_reference_ladder(candles, count=3)
        assert ladder
        levels = [entry["target_price"] for entry in ladder]
        assert all(level > 0 for level in levels)
        assert any(entry["direction"] == "above" for entry in ladder)
        assert all(entry["origin"] == "DERIVED" for entry in ladder)
        assert all(entry.get("observed_at") for entry in ladder)

    def test_ladder_needs_history(self):
        assert targets_mod.derive_reference_ladder(make_candles(10), count=3) == []


class TestDateQueries:
    def test_price_on_date_observed(self):
        candles = make_candles(100, step_seconds=86400)
        stamp = candles[50].timestamp + timedelta(hours=2)
        result = targets_mod.price_on_date(candles, date=stamp)
        assert result["status"] == "OBSERVED"
        assert result["close"] == candles[50].close

    def test_price_on_date_unavailable_when_uncovered(self):
        candles = make_candles(10, step_seconds=86400)
        result = targets_mod.price_on_date(candles, date=EPOCH + timedelta(days=500))
        assert result["status"] == "UNAVAILABLE"

    def test_threshold_on_date_answered(self):
        candles = make_candles(100, start=100.0, step_seconds=86400)
        stamp = candles[50].timestamp + timedelta(hours=1)
        result = targets_mod.evaluate_threshold_on_date(
            candles, date=stamp, threshold=candles[50].low - 1, direction="above"
        )
        assert result["status"] == "ANSWERED"
        assert result["answer"] is True  # the bar's high is above the low-1 threshold

    def test_threshold_on_date_uncovered(self):
        candles = make_candles(10, step_seconds=86400)
        result = targets_mod.evaluate_threshold_on_date(
            candles, date=EPOCH + timedelta(days=500), threshold=50.0
        )
        assert result["status"] == "UNAVAILABLE"
        assert result["answer"] is None


class TestThresholdProbability:
    def test_empirical_needs_samples(self):
        assert thresholds_mod.empirical_probability_above(
            closes=[100.0] * 10, threshold=110.0, horizon=2
        ) is None

    def test_gbm_between_zero_and_one(self):
        candles = make_candles(500, amplitude=1.0)
        probability = thresholds_mod.gbm_probability_above(
            closes=[c.close for c in candles], threshold=candles[-1].close * 1.02, horizon=5
        )
        assert 0.0 < probability < 0.5  # 2% up-move within 5 bars of low-vol series

    def test_gbm_invalid_threshold(self):
        assert thresholds_mod.gbm_probability_above(closes=[100.0] * 100, threshold=-1, horizon=5) is None

    def test_threshold_analysis_labels_modelled(self):
        candles = make_candles(500, amplitude=1.0)
        result = thresholds_mod.threshold_analysis(
            symbol="TEST", timeframe="1h", candles=candles,
            threshold=candles[-1].close * 1.01, horizon=5,
        )
        assert result["label"] == "MODELLED PROBABILITY"
        assert result["probabilities"]["empirical"] is not None
        assert 0.0 <= result["probabilities"]["empirical"] <= 1.0
        assert result["calibration"]["status"] in {"OK", "INSUFFICIENT_DATA"}

    def test_threshold_analysis_unavailable_without_data(self):
        result = thresholds_mod.threshold_analysis(
            symbol="TEST", timeframe="1h", candles=[], threshold=100.0, horizon=5
        )
        assert result["probabilities"] is None
        assert result["status"] == "UNAVAILABLE"

    def test_calibration_report_structure(self):
        candles = make_candles(2000, amplitude=1.0)
        report = thresholds_mod.calibrate_threshold(
            closes=[c.close for c in candles],
            threshold=candles[-1].close * 1.005,
            horizon=5,
        )
        assert report.status in {"OK", "INSUFFICIENT_DATA"}
        if report.status == "OK":
            assert 0 <= report.brier_score <= 1
            assert len(report.bins) == thresholds_mod.RELIABILITY_BINS
            assert report.samples >= thresholds_mod.MIN_CALIBRATION_SAMPLES
