"""
Phase 22B — model monitoring, anomaly detection and calibration tests
(spec §27 model drift, §28 outlier detection, §29 calibration, §32 required tests).

These are the components the API smoke tests only exercised indirectly. Here the
properties that matter are asserted directly:

  * PSI / KS behave as their definitions require (identical → stable, shifted →
    moved) and return ``None`` rather than a number when the input is degenerate;
  * the drift monitor's status semantics (STABLE / WATCH /
    ``MODEL PERFORMANCE DEGRADED`` / UNKNOWN) are driven by real statistics;
  * outlier detection flags an abnormal observation and can never emit a
    directional market claim;
  * threshold calibration is genuinely **walk-forward** — a spy proves each
    probability is rebuilt from a strict prefix of the series, so no future close
    can leak into it.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.crypto import thresholds as thresholds_mod
from app.crypto.forecasting.drift import (
    PSI_SHIFTED,
    PSI_STABLE,
    AnomalyReport,
    ModelDriftMonitor,
    detect_outliers,
    ks_test,
    population_stability_index,
    robust_z_scores,
    training_age_status,
)
from app.crypto.tests.synthetic import make_candles

# ---------------------------------------------------------------------------
# §27 — drift statistics
# ---------------------------------------------------------------------------


class TestPopulationStabilityIndex:
    def test_identical_distribution_is_stable(self):
        reference = [float(i) for i in range(100)]
        psi = population_stability_index(reference, list(reference))
        assert psi is not None
        assert psi < PSI_STABLE

    def test_shifted_distribution_exceeds_threshold(self):
        reference = [float(i) for i in range(100)]
        shifted = [value + 100.0 for value in reference]
        psi = population_stability_index(reference, shifted)
        assert psi is not None
        assert psi > PSI_SHIFTED

    def test_empty_input_is_none(self):
        assert population_stability_index([], [1.0, 2.0]) is None
        assert population_stability_index([1.0, 2.0], []) is None

    def test_constant_reference_has_no_distribution_to_shift(self):
        # A constant feature carries no distribution; returning a number here
        # would be an invented statistic.
        assert population_stability_index([5.0] * 40, [5.0] * 40) is None


class TestKolmogorovSmirnov:
    def test_same_sample_is_indistinguishable(self):
        sample = [float(i) for i in range(80)]
        statistic, pvalue = ks_test(sample, list(sample))
        assert statistic is not None and pvalue is not None
        assert statistic == pytest.approx(0.0, abs=1e-9)
        assert pvalue > 0.05

    def test_separated_distributions_are_flagged(self):
        reference = [float(i) for i in range(80)]
        shifted = [value + 200.0 for value in reference]
        _, pvalue = ks_test(reference, shifted)
        assert pvalue is not None
        assert pvalue < 0.05

    def test_tiny_samples_return_none(self):
        assert ks_test([1.0], [1.0, 2.0]) == (None, None)


class TestDriftMonitor:
    def test_stable_when_distribution_matches(self):
        reference = {"feature_a": [float(i) for i in range(100)]}
        recent = {"feature_a": [float(i) for i in range(100)]}
        report = ModelDriftMonitor().compare(reference=reference, recent=recent)
        assert report.status == "STABLE"
        assert report.degraded_share == 0.0
        assert report.features[0].status == "STABLE"

    def test_degraded_when_most_features_shift(self):
        reference = {
            "feature_a": [float(i) for i in range(100)],
            "feature_b": [float(i) * 2 for i in range(100)],
        }
        recent = {
            "feature_a": [float(i) + 500.0 for i in range(100)],
            "feature_b": [float(i) * 2 + 500.0 for i in range(100)],
        }
        report = ModelDriftMonitor().compare(reference=reference, recent=recent)
        # Every feature shifted → the model is labelled degraded, not hidden.
        assert report.status == "MODEL PERFORMANCE DEGRADED"
        assert report.degraded_share == pytest.approx(1.0)
        assert all(f.status == "SHIFTED" for f in report.features)

    def test_missing_reference_is_unknown(self):
        report = ModelDriftMonitor().compare(reference={}, recent={"a": [1.0, 2.0]})
        assert report.status == "UNKNOWN"
        assert report.reference_size == 0

    def test_training_age_is_measured_from_real_timestamp(self):
        training_time = datetime.now(timezone.utc) - timedelta(days=3, hours=1)
        report = ModelDriftMonitor().compare(
            reference={"a": [float(i) for i in range(50)]},
            recent={"a": [float(i) for i in range(50)]},
            training_time=training_time,
        )
        assert report.training_age_days is not None
        assert 2.9 < report.training_age_days < 3.2

    def test_to_dict_is_json_safe(self):
        report = ModelDriftMonitor().compare(
            reference={"a": [float(i) for i in range(30)]},
            recent={"a": [float(i) for i in range(30)]},
        )
        payload = report.to_dict()
        assert isinstance(payload["compared_at"], str)
        assert payload["features"][0]["feature"] == "a"


class TestTrainingAgeStatus:
    def test_unknown_without_timestamp(self):
        assert training_age_status(None) == "UNKNOWN"

    def test_fresh_then_stale(self):
        assert training_age_status(datetime.now(timezone.utc)) == "FRESH"
        assert training_age_status(datetime.now(timezone.utc) - timedelta(days=30)) == "STALE"

    def test_naive_timestamp_is_treated_as_utc(self):
        naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert training_age_status(naive) == "FRESH"


# ---------------------------------------------------------------------------
# §28 — outlier / anomaly detection
# ---------------------------------------------------------------------------


class TestRobustZScores:
    def test_degenerate_window_returns_none(self):
        # MAD == 0: the score is undefined, not zero.
        assert robust_z_scores([1.0, 1.0, 1.0, 1.0]) == [None, None, None, None]

    def test_short_series_is_none(self):
        assert robust_z_scores([1.0, 2.0]) == [None, None]

    def test_outlier_gets_a_large_score(self):
        # A spread series (MAD > 0) with a single extreme observation appended.
        scores = robust_z_scores([0.001 * ((-1) ** i) for i in range(30)] + [0.5])
        assert scores[-1] is not None
        assert abs(scores[-1]) > 3.5
        assert all(score is None or abs(score) < 3.5 for score in scores[:-1])


class TestDetectOutliers:
    def test_insufficient_data_is_reported(self):
        report = detect_outliers(
            returns=[0.001] * 5, highs=[1.0] * 5, lows=[1.0] * 5, closes=[1.0] * 5
        )
        assert report.status == "INSUFFICIENT_DATA"
        assert report.sample_size == 5

    def test_normal_series_is_not_flagged(self):
        returns = [0.001 * ((-1) ** i) for i in range(60)]
        report = detect_outliers(
            returns=returns,
            highs=[100.5] * 60,
            lows=[99.5] * 60,
            closes=[100.0] * 60,
        )
        assert report.status == "NORMAL"
        assert report.flags == []

    def test_extreme_return_is_flagged_as_anomaly(self):
        returns = [0.001 * ((-1) ** i) for i in range(59)] + [0.9]
        report = detect_outliers(
            returns=returns,
            highs=[100.5] * 60,
            lows=[99.5] * 60,
            closes=[100.0] * 60,
        )
        assert report.status == "DATA ANOMALY"
        assert report.flags

    def test_output_never_makes_a_directional_claim(self):
        report = detect_outliers(
            returns=[0.001] * 30 + [1.5],
            highs=[100.5] * 31,
            lows=[99.5] * 31,
            closes=[100.0] * 31,
        )
        payload = report.to_dict()
        assert payload["status"] in {"DATA ANOMALY", "NORMAL", "INSUFFICIENT_DATA"}
        assert "not a price prediction" in payload["note"]
        # No field may smuggle in a buy/sell/up/down claim.
        assert not any(key in payload for key in ("direction", "prediction", "signal", "action"))

    def test_report_dataclass_default_is_safe(self):
        assert AnomalyReport(status="NORMAL").flags == []


# ---------------------------------------------------------------------------
# §29 — calibration (Brier score / reliability), walk-forward & leakage-free
# ---------------------------------------------------------------------------


class TestCalibrationMaths:
    def test_insufficient_history_is_explicit(self):
        closes = [100.0 + i * 0.1 for i in range(50)]
        report = thresholds_mod.calibrate_threshold(closes=closes, threshold=120.0, horizon=5)
        assert report.status == "INSUFFICIENT_DATA"
        assert report.brier_score is None

    def test_reliability_table_and_brier_are_well_formed(self):
        candles = make_candles(2500, amplitude=1.0)
        closes = [c.close for c in candles]
        report = thresholds_mod.calibrate_threshold(
            closes=closes, threshold=closes[-1] * 1.005, horizon=5
        )
        assert report.status == "OK"
        assert 0.0 <= report.brier_score <= 1.0
        assert len(report.bins) == thresholds_mod.RELIABILITY_BINS
        assert report.samples >= thresholds_mod.MIN_CALIBRATION_SAMPLES
        # Every populated bin reports a real observed frequency.
        for bucket in report.bins:
            if bucket.count:
                assert 0.0 <= bucket.observed_frequency <= 1.0
                assert bucket.mean_predicted is not None

    def test_brier_skill_score_definition(self):
        candles = make_candles(2500, amplitude=1.0)
        closes = [c.close for c in candles]
        report = thresholds_mod.calibrate_threshold(
            closes=closes, threshold=closes[-1] * 1.005, horizon=5
        )
        assert report.status == "OK"
        # BSS = 1 - Brier / Brier(base-rate). Both terms are in [0, 1].
        if report.brier_skill_score is not None:
            assert report.brier_skill_score <= 1.0 + 1e-9
            assert report.base_rate is not None and 0.0 <= report.base_rate <= 1.0


class TestCalibrationLeakage:
    def test_probability_uses_only_a_strict_past_prefix(self, monkeypatch):
        """
        Spec §29/§25: the calibration must be walk-forward. We spy on the
        probability builder and assert every call receives a strict prefix of the
        series whose length never exceeds the evaluation index + 1 — i.e. no
        future close is ever visible when the probability is formed.
        """
        closes = [c.close for c in make_candles(1200, amplitude=1.0)]
        total = len(closes)
        observed_lengths: list[int] = []

        original = thresholds_mod.gbm_probability_above

        def spy(*, closes, threshold, horizon):  # noqa: A002 - mirror real signature
            observed_lengths.append(len(closes))
            return original(closes=closes, threshold=threshold, horizon=horizon)

        monkeypatch.setattr(thresholds_mod, "gbm_probability_above", spy)
        report = thresholds_mod.calibrate_threshold(
            closes=closes, threshold=closes[-1] * 1.005, horizon=5
        )
        assert observed_lengths, "calibration never built a probability"
        assert report.status == "OK"
        # Each prefix must leave room for the realised outcome (index + horizon).
        assert max(observed_lengths) <= total - 5
        # And the prefixes must grow only forward (expanding window).
        assert observed_lengths == sorted(observed_lengths)

    def test_empirical_probability_monotonic_in_threshold(self):
        candles = make_candles(2000, amplitude=1.0)
        closes = [c.close for c in candles]
        low = thresholds_mod.empirical_probability_above(closes=closes, threshold=closes[-1] * 1.001, horizon=5)
        high = thresholds_mod.empirical_probability_above(closes=closes, threshold=closes[-1] * 1.20, horizon=5)
        assert low is not None and high is not None
        # Asking for a higher price can only be rarer.
        assert low >= high

    def test_h_step_returns_are_realised_future_returns(self):
        closes = [100.0, 110.0, 121.0, 133.1]
        returns = thresholds_mod.h_step_returns(closes, horizon=1)
        assert len(returns) == 3
        assert returns[0] == pytest.approx(math.log(110.0 / 100.0))
        assert returns[-1] == pytest.approx(math.log(133.1 / 121.0))
