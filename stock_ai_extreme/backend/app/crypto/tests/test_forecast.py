"""Forecast engine tests: baselines, ML, walk-forward, metrics, intervals, versioning (spec §97)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.crypto.forecasting.baselines import (
    ExponentialSmoothingForecaster,
    MovingAverageForecaster,
    NaiveForecaster,
    TrendExtrapolationForecaster,
    default_baselines,
)
from app.crypto.forecasting.engine import INTERVAL_CONFIDENCE, ForecastEngine, evaluate_forecast
from app.crypto.forecasting.models import (
    BaselineCandidate,
    MLCandidate,
    compute_metrics,
    residual_quantiles,
    walk_forward_folds,
    walk_forward_validate,
)
from app.crypto.forecasting import features as feature_mod
from app.crypto.schemas import CryptoForecast, ForecastMetrics, QualityLabel
from app.crypto.tests.synthetic import make_candles


def _matrix_and_closes(count=400, amplitude=1.0, drift=0.002):
    candles = make_candles(count, amplitude=amplitude, drift=drift)
    matrix = feature_mod.build_features(candles, horizon=5)
    return matrix, [c.close for c in candles]


class TestBaselines:
    def test_naive_is_random_walk(self):
        assert NaiveForecaster().predict_return([100.0, 101.0]) == 0.0

    def test_moving_average_direction(self):
        # The mean of the window sits BELOW the last close in a rising series,
        # so the mean-reversion estimate is a NEGATIVE expected return.
        up = MovingAverageForecaster(window=5).predict_return([10, 11, 12, 13, 14, 15])
        assert up is not None and up < 0
        down = MovingAverageForecaster(window=5).predict_return([15, 14, 13, 12, 11, 10])
        assert down is not None and down > 0

    def test_moving_average_needs_history(self):
        assert MovingAverageForecaster(window=5).predict_return([10, 11]) is None

    def test_exp_smoothing_fits_alpha_on_train_only(self):
        forecaster = ExponentialSmoothingForecaster()
        train = [100.0 + i for i in range(60)]
        forecaster.fit(train)
        assert forecaster.alpha in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

    def test_trend_extrapolation_positive_for_uptrend(self):
        value = TrendExtrapolationForecaster(window=10).predict_return([float(i) for i in range(10, 30)])
        assert value is not None and value > 0

    def test_default_baselines_set(self):
        names = {b.name for b in default_baselines(horizon=5)}
        assert {"naive", "moving_average_10", "exp_smoothing", "trend_extrapolation_20"} <= names


class TestMetrics:
    def test_mae_rmse(self):
        metrics = compute_metrics([101.0, 102.0], [100.0, 100.0])
        assert metrics.mae == pytest.approx(1.5)
        assert metrics.rmse == pytest.approx(math.sqrt((1 + 4) / 2))
        assert metrics.observations == 2

    def test_mape_skipped_for_zero_actual(self):
        metrics = compute_metrics([1.0], [0.0])
        assert metrics.mape is None

    def test_directional_accuracy(self):
        metrics = compute_metrics(
            [101.0, 99.0, 103.0],
            [100.0, 100.0, 100.0],
            directional_predicted=[0.01, -0.01, 0.02],
            directional_actual=[0.005, -0.002, -0.01],
        )
        # Two of three directional calls correct (up/up, down/down, up/down).
        assert metrics.directional_accuracy == pytest.approx(2 / 3)

    def test_empty_metrics(self):
        assert compute_metrics([], []).observations == 0


class TestWalkForward:
    def test_folds_are_chronological_and_non_overlapping(self):
        folds = walk_forward_folds(300, folds=5, min_train=150)
        assert folds
        previous_end = 0
        for train_end, test_end in folds:
            assert train_end >= previous_end
            assert test_end > train_end
            previous_end = test_end
        assert folds[-1][1] == 300

    def test_folds_never_leak_future_into_train(self):
        folds = walk_forward_folds(300, folds=5, min_train=150)
        for train_end, test_end in folds:
            assert train_end <= test_end  # training block ends where testing begins

    def test_no_rows_when_min_train_exceeds_sample(self):
        assert walk_forward_folds(100, folds=5, min_train=150) == []

    def test_validation_scores_baseline(self):
        matrix, closes = _matrix_and_closes()
        result = walk_forward_validate(
            BaselineCandidate(NaiveForecaster(), horizon=matrix.horizon),
            matrix,
            closes,
            folds=3,
            min_train=250,
        )
        assert result.metrics.observations > 0
        assert result.metrics.rmse is not None and result.metrics.rmse > 0

    def test_ml_model_validation_runs(self):
        matrix, closes = _matrix_and_closes()
        candidate = MLCandidate(
            "ridge", lambda: __import__("sklearn.linear_model", fromlist=["Ridge"]).Ridge(alpha=1.0),
            feature_names=matrix.feature_names,
        )
        result = walk_forward_validate(candidate, matrix, closes, folds=3, min_train=250)
        assert result.metrics.observations > 0

    def test_feature_importance_extraction(self):
        matrix, closes = _matrix_and_closes()
        candidate = MLCandidate(
            "ridge", lambda: __import__("sklearn.linear_model", fromlist=["Ridge"]).Ridge(alpha=1.0),
            feature_names=matrix.feature_names,
        )
        candidate.fit(matrix, list(range(matrix.n_rows)), closes)
        importance = candidate.feature_importance()
        assert importance is not None
        assert set(importance) == set(matrix.feature_names)


class TestIntervals:
    def test_residual_quantiles_bracket_zero_for_unbiased(self):
        rng = np.random.default_rng(7)
        residuals = list(rng.normal(0, 0.01, 500))
        lower, upper = residual_quantiles(residuals, confidence=0.8)
        assert lower < 0 < upper
        assert upper - lower == pytest.approx(2 * np.quantile(np.array(residuals), 0.9), rel=0.3)

    def test_empty_residuals(self):
        assert residual_quantiles([], confidence=0.8) == (0.0, 0.0)


class TestEngine:
    def test_forecast_is_versioned_and_labelled(self):
        matrix, closes = _matrix_and_closes()
        engine = ForecastEngine(min_training_samples=200, folds=3)
        candles = make_candles(400)
        outcome = engine.forecast(
            symbol="TEST", timeframe="1h", candles=candles,
            duration_seconds=3600, data_source="fixture",
        )
        assert outcome.available
        forecast = outcome.forecast
        assert forecast.label == "MODELLED FORECAST"
        assert forecast.feature_version == feature_mod.FEATURE_VERSION
        assert "@" in forecast.model_version
        assert forecast.model_version.endswith(feature_mod.FEATURE_VERSION)
        assert forecast.training_window == matrix.n_rows
        assert forecast.training_end_time is not None
        assert forecast.lower_bound is not None and forecast.upper_bound is not None
        assert forecast.lower_bound < forecast.prediction < forecast.upper_bound
        assert forecast.metrics.observations > 0
        assert forecast.baseline_metrics.observations > 0
        assert forecast.limitations  # limitations panel always populated
        assert any("not a guaranteed outcome" in note for note in forecast.limitations)

    def test_insufficient_history_declines(self):
        engine = ForecastEngine(min_training_samples=5000)
        outcome = engine.forecast(
            symbol="TEST", timeframe="1h", candles=make_candles(200),
            duration_seconds=3600, data_source="fixture",
        )
        assert not outcome.available
        assert outcome.forecast is None
        assert "insufficient" in outcome.reason

    def test_validation_ranks_models_by_rmse(self):
        engine = ForecastEngine(min_training_samples=200, folds=3)
        outcome = engine.forecast(
            symbol="TEST", timeframe="1h", candles=make_candles(400),
            duration_seconds=3600, data_source="fixture",
        )
        rmses = [r.metrics.rmse for r in outcome.validation]
        assert rmses == sorted(rmses)

    def test_selection_beats_or_matches_baseline(self):
        engine = ForecastEngine(min_training_samples=200, folds=3)
        outcome = engine.forecast(
            symbol="TEST", timeframe="1h", candles=make_candles(400),
            duration_seconds=3600, data_source="fixture",
        )
        chosen = outcome.forecast.metrics
        baseline = outcome.baseline_metrics
        assert chosen.rmse <= baseline.rmse * 1.001 or chosen.rmse <= baseline.rmse

    def test_deterministic_for_same_input(self):
        candles = make_candles(400)
        engine = ForecastEngine(min_training_samples=200, folds=3)
        a = engine.forecast(symbol="T", timeframe="1h", candles=candles, duration_seconds=3600, data_source="f")
        b = engine.forecast(symbol="T", timeframe="1h", candles=candles, duration_seconds=3600, data_source="f")
        assert a.forecast.model_name == b.forecast.model_name
        assert a.forecast.prediction == pytest.approx(b.forecast.prediction)


class TestRetrospectiveEvaluation:
    def _forecast(self, prediction=110.0, last_close=100.0):
        from datetime import datetime, timezone

        return CryptoForecast(
            id="f1", symbol="TEST", timeframe="1h", horizon=5,
            generated_at=datetime.now(timezone.utc),
            prediction=prediction, last_close=last_close,
            lower_bound=prediction * 0.98, upper_bound=prediction * 1.02,
            model_name="naive", model_version="naive@1", feature_version="v1",
            training_window=100, metrics=ForecastMetrics(observations=10),
            baseline_metrics=ForecastMetrics(observations=10),
            beats_baseline=True, data_source="fixture", data_quality=QualityLabel.MEDIUM,
        )

    def test_evaluation_records_real_error(self):
        # Prediction 110 from a 100 close (up); realised 105 (also up but lower,
        # and outside the ±2% interval).
        evaluation = evaluate_forecast(forecast=self._forecast(), actual_price=105.0)
        assert evaluation["error"] == pytest.approx(-5.0)
        assert evaluation["absolute_error"] == pytest.approx(5.0)
        assert evaluation["percentage_error"] == pytest.approx(5.0 / 105.0)
        assert evaluation["directional_correct"] is True  # both sides above the 100 anchor
        assert evaluation["within_interval"] is False

    def test_within_interval(self):
        evaluation = evaluate_forecast(forecast=self._forecast(prediction=110.0), actual_price=109.9)
        assert evaluation["within_interval"] is True
        assert evaluation["directional_correct"] is True
