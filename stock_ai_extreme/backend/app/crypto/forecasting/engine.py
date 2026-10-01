"""
Forecast engine (spec §20–§31, §82, §83, §87).

Orchestration, in order:

  1. build the leakage-safe feature matrix (:mod:`features`);
  2. evaluate every baseline and every applicable ML model on the **same**
     expanding-window folds (:mod:`models`);
  3. choose the best baseline and the best ML model, and prefer the ML model
     only when it beats the baseline by a real margin (spec §21);
  4. try a validated two-model ensemble (inverse-RMSE weights learned from the
     validation errors) and use it only if it genuinely improves on the winner
     (spec §82);
  5. refit the winner on every labelled row and predict the newest unlabeled row
     — for an ensemble, refit both members and blend with the learned weights;
  6. derive the prediction interval from the **empirical distribution of the
     winner's own validation residuals** — not from an assumed distribution;
  7. return a fully versioned :class:`~app.crypto.schemas.CryptoForecast` whose
     metrics, baseline metrics, limitations and data quality are all recorded.

If there is not enough history, the engine returns no forecast at all
(``UNAVAILABLE``) rather than training on a toy sample or inventing a number.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.crypto.config import crypto_settings
from app.crypto.forecasting import features as feature_mod
from app.crypto.forecasting.baselines import default_baselines
from app.crypto.forecasting.drift import AnomalyReport, detect_outliers
from app.crypto.forecasting.models import (
    BaselineCandidate,
    Candidate,
    MLCandidate,
    ValidationResult,
    compute_metrics,
    default_ml_candidates,
    residual_quantiles,
    walk_forward_validate,
)
from app.crypto.schemas import (
    Candle,
    CryptoForecast,
    ForecastMetrics,
    QualityLabel,
)

logger = logging.getLogger("neural_market.crypto.forecasting.engine")

#: Semantic version of the forecasting *engine* (not of an individual model).
ENGINE_VERSION = "1.0.0"

#: A model version is stamped as engine + feature schema, so a stored forecast
#: can always be traced back to the exact code and features that produced it.
def model_version(model_name: str) -> str:
    return f"{model_name}@{ENGINE_VERSION}+{feature_mod.FEATURE_VERSION}"


#: ML must beat the best baseline by this relative margin to be preferred,
#: otherwise the simpler model wins (spec §21).
ML_IMPROVEMENT_MARGIN = 0.01

#: Ensemble must beat the winner by this relative margin to be used (spec §82).
ENSEMBLE_IMPROVEMENT_MARGIN = 0.01

#: Confidence level of the reported prediction interval, derived from residuals.
INTERVAL_CONFIDENCE = 0.80


@dataclass
class Selection:
    """The chosen model: its validation evidence and how to refit/blend it."""

    result: ValidationResult
    members: List[Candidate] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def name(self) -> str:
        return self.result.name

    @property
    def kind(self) -> str:
        return self.result.kind

    def predict_live(self, matrix, closes: Sequence[float]) -> float:
        """Blend each member's live forecast with the learned weights."""
        if not self.members:
            raise ValueError("selection has no members to predict with")
        if len(self.members) == 1:
            return float(self.members[0].predict(matrix, [0], closes)[0])
        total_weight = sum(self.weights) or 1.0
        blended = 0.0
        for member, weight in zip(self.members, self.weights):
            blended += (weight / total_weight) * float(member.predict(matrix, [0], closes)[0])
        return blended


@dataclass
class ForecastOutcome:
    """Everything the service layer needs, including the audit trail."""

    forecast: Optional[CryptoForecast]
    validation: List[ValidationResult] = field(default_factory=list)
    baseline_metrics: Optional[ForecastMetrics] = None
    residual_std: Optional[float] = None
    feature_names: List[str] = field(default_factory=list)
    reference_features: Dict[str, List[float]] = field(default_factory=dict)
    recent_features: Dict[str, List[float]] = field(default_factory=dict)
    anomaly: Optional[AnomalyReport] = None
    limitations: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    diagnostics: Dict[str, float] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.forecast is not None


class ForecastEngine:
    """Serialisable, reproducible forecasting over real candle history."""

    def __init__(
        self,
        *,
        folds: Optional[int] = None,
        min_training_samples: Optional[int] = None,
        horizon: Optional[int] = None,
    ) -> None:
        self.folds = folds or crypto_settings.walk_forward_folds
        self.min_training_samples = min_training_samples or crypto_settings.min_training_samples
        self.horizon = horizon or crypto_settings.default_horizon

    # ------------------------------------------------------------------ public
    def forecast(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[Candle],
        duration_seconds: int,
        data_source: str,
        quality: QualityLabel = QualityLabel.MEDIUM,
        horizon: Optional[int] = None,
    ) -> ForecastOutcome:
        """Generate (or decline to generate) a versioned forecast."""
        resolved_horizon = horizon or self.horizon
        matrix = feature_mod.build_features(candles, horizon=resolved_horizon)

        if matrix.n_rows < self.min_training_samples:
            return ForecastOutcome(
                forecast=None,
                feature_names=matrix.feature_names,
                reason=(
                    f"insufficient labelled history: {matrix.n_rows} rows < required "
                    f"{self.min_training_samples}"
                ),
                diagnostics=matrix.diagnostics,
            )

        closes = [c.close for c in candles]
        candidates = self._candidates(matrix)
        results = [
            walk_forward_validate(
                candidate, matrix, closes, folds=self.folds, min_train=self._min_train(matrix.n_rows)
            )
            for candidate in candidates
        ]
        results = [r for r in results if r.metrics.observations > 0]
        if not results:
            return ForecastOutcome(
                forecast=None,
                feature_names=matrix.feature_names,
                reason="walk-forward validation produced no usable folds",
                diagnostics=matrix.diagnostics,
            )

        baselines = [r for r in results if r.kind == "baseline"]
        ml_results = [r for r in results if r.kind == "ml"]
        best_baseline = min(baselines, key=_rmse, default=None)
        best_ml = min(ml_results, key=_rmse, default=None)

        selection = self._select(results, candidates, best_baseline, best_ml)

        # Refit the winner on every labelled row, then predict the live row.
        live = feature_mod.latest_matrix(matrix)
        if live is None:
            return ForecastOutcome(
                forecast=None,
                feature_names=matrix.feature_names,
                reason="no computable feature row for the newest candle",
            )
        for member in selection.members:
            member.fit(matrix, list(range(matrix.n_rows)), closes)
        try:
            predicted_price = selection.predict_live(live, closes)
        except Exception as exc:  # a failed re-fit must not produce a number
            logger.warning("refit/predict failed for %s: %s", selection.name, exc)
            return ForecastOutcome(
                forecast=None,
                feature_names=matrix.feature_names,
                reason=f"model refit failed: {type(exc).__name__}",
            )
        last_close = live.base_close[0]
        if not math.isfinite(predicted_price) or predicted_price <= 0:
            return ForecastOutcome(
                forecast=None,
                feature_names=matrix.feature_names,
                reason="model produced a non-finite price; forecast withheld",
            )

        # Prediction interval from the winner's real validation residuals.
        residuals = [
            math.log(p / a) if (p > 0 and a > 0) else 0.0
            for p, a in zip(selection.result.predicted_prices, selection.result.actual_prices)
        ]
        lower_res, upper_res = residual_quantiles(residuals, confidence=INTERVAL_CONFIDENCE)
        lower_bound = predicted_price * math.exp(lower_res)
        upper_bound = predicted_price * math.exp(upper_res)
        residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else None

        limitations = self._limitations(
            matrix=matrix,
            selection=selection,
            best_baseline=best_baseline,
            data_source=data_source,
            horizon=resolved_horizon,
        )
        reference, recent = self._drift_slices(matrix)

        beats_baseline = True
        if best_baseline is not None and best_baseline.metrics.rmse not in (None, 0):
            chosen_rmse = selection.result.metrics.rmse
            beats_baseline = bool(
                chosen_rmse is not None
                and chosen_rmse <= best_baseline.metrics.rmse  # type: ignore[operator]
            )
        else:
            beats_baseline = False

        forecast = CryptoForecast(
            id=str(uuid.uuid4()),
            symbol=symbol,
            timeframe=timeframe,
            horizon=resolved_horizon,
            generated_at=datetime.now(timezone.utc),
            prediction=predicted_price,
            last_close=last_close,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            model_name=selection.name,
            model_version=model_version(selection.name),
            feature_version=feature_mod.FEATURE_VERSION,
            training_window=matrix.n_rows,
            training_end_time=matrix.feature_timestamps[-1] if matrix.feature_timestamps else None,
            metrics=selection.result.metrics,
            baseline_metrics=best_baseline.metrics if best_baseline else ForecastMetrics(observations=0),
            beats_baseline=beats_baseline,
            data_source=data_source,
            data_quality=quality,
            limitations=limitations,
        )

        return ForecastOutcome(
            forecast=forecast,
            validation=sorted(results, key=_rmse),
            baseline_metrics=best_baseline.metrics if best_baseline else None,
            residual_std=residual_std,
            feature_names=matrix.feature_names,
            reference_features=reference,
            recent_features=recent,
            anomaly=self._anomaly(candles, duration_seconds),
            limitations=limitations,
            diagnostics=matrix.diagnostics,
        )

    # ----------------------------------------------------------------- internal
    def _min_train(self, n_rows: int) -> int:
        """Train at least the configured minimum, and at least half the sample."""
        return max(self.min_training_samples, n_rows // 2)

    def _candidates(self, matrix) -> List[Candidate]:
        baselines: List[Candidate] = [
            BaselineCandidate(forecaster, horizon=matrix.horizon)
            for forecaster in default_baselines(horizon=matrix.horizon)
        ]
        ml: List[Candidate] = list(
            default_ml_candidates(feature_names=matrix.feature_names, sample_size=matrix.n_rows)
        )
        return baselines + ml

    def _select(
        self,
        results: Sequence[ValidationResult],
        candidates: Sequence[Candidate],
        best_baseline: Optional[ValidationResult],
        best_ml: Optional[ValidationResult],
    ) -> Selection:
        """
        Pick the winner: ML only if it genuinely beats the baseline; then try an
        ensemble and use it only if it genuinely beats the winner.
        """
        by_name = {c.name: c for c in candidates}

        if best_ml is not None and best_baseline is not None:
            ml_rmse, baseline_rmse = _rmse(best_ml), _rmse(best_baseline)
            if (
                ml_rmse != float("inf")
                and baseline_rmse != float("inf")
                and ml_rmse <= baseline_rmse * (1 - ML_IMPROVEMENT_MARGIN)
            ):
                winner = best_ml
            else:
                winner = best_baseline
        else:
            winner = best_ml or best_baseline or results[0]

        winner_candidate = by_name.get(winner.name)
        if winner_candidate is None:
            return Selection(result=winner, members=[])

        ensemble = self._try_ensemble(results, winner, by_name)
        if ensemble is not None:
            return ensemble
        return Selection(result=winner, members=[winner_candidate], weights=[1.0])

    def _try_ensemble(
        self,
        results: Sequence[ValidationResult],
        winner: ValidationResult,
        by_name: Dict[str, Candidate],
    ) -> Optional[Selection]:
        """Validate a two-model weighted average; adopt it only if it improves."""
        ranked = sorted(results, key=_rmse)
        if len(ranked) < 2 or ranked[0].name != winner.name:
            return None
        first, second = ranked[0], ranked[1]
        if len(first.predicted_prices) != len(second.predicted_prices):
            return None
        first_candidate, second_candidate = by_name.get(first.name), by_name.get(second.name)
        if first_candidate is None or second_candidate is None:
            return None

        first_rmse, second_rmse = _rmse(first), _rmse(second)
        if first_rmse == float("inf") or second_rmse == float("inf"):
            return None
        weight_a = 1.0 / first_rmse
        weight_b = 1.0 / second_rmse
        total = weight_a + weight_b
        if total <= 0:
            return None
        weight_a, weight_b = weight_a / total, weight_b / total

        blended = [
            weight_a * pa + weight_b * pb
            for pa, pb in zip(first.predicted_prices, second.predicted_prices)
        ]
        blended_metrics = compute_metrics(
            blended,
            first.actual_prices,
            directional_predicted=first.predicted_returns,
            directional_actual=first.actual_returns,
        )
        if (
            blended_metrics.rmse is None
            or first.metrics.rmse is None
            or blended_metrics.rmse > first.metrics.rmse * (1 - ENSEMBLE_IMPROVEMENT_MARGIN)
        ):
            return None

        ensemble_result = ValidationResult(
            name=f"ensemble[{first.name}+{second.name}]",
            kind="ensemble",
            metrics=blended_metrics,
            predicted_prices=blended,
            actual_prices=list(first.actual_prices),
            predicted_returns=list(first.predicted_returns),
            actual_returns=list(first.actual_returns),
            row_indices=list(first.row_indices),
            folds=first.folds,
        )
        note = (
            f"validated ensemble: weights {first.name}={weight_a:.3f}, "
            f"{second.name}={weight_b:.3f} (inverse-RMSE, learned on the validation folds); "
            f"RMSE {first.metrics.rmse:.4f} → {blended_metrics.rmse:.4f}"
        )
        return Selection(
            result=ensemble_result,
            members=[first_candidate, second_candidate],
            weights=[weight_a, weight_b],
            note=note,
        )

    def _limitations(
        self,
        *,
        matrix,
        selection: Selection,
        best_baseline: Optional[ValidationResult],
        data_source: str,
        horizon: int,
    ) -> List[str]:
        chosen = selection.result
        notes = [
            f"Modelled forecast, not a guaranteed outcome. Horizon = {horizon} bars.",
            f"Trained on {matrix.n_rows} labelled observations from real {data_source} candles.",
            f"Validated with expanding-window walk-forward ({self.folds} folds); no random split is used.",
            f"Prediction interval is the {int(INTERVAL_CONFIDENCE * 100)}% empirical residual band of the selected model.",
        ]
        if best_baseline is not None and best_baseline.metrics.rmse not in (None, 0) and chosen.metrics.rmse is not None:
            improvement = (
                best_baseline.metrics.rmse - chosen.metrics.rmse  # type: ignore[operator]
            ) / best_baseline.metrics.rmse  # type: ignore[operator]
            notes.append(
                f"Best baseline ({best_baseline.name}) RMSE {best_baseline.metrics.rmse:.4f} vs "
                f"selected {chosen.name} RMSE {chosen.metrics.rmse:.4f} "
                f"({improvement * 100:+.2f}% relative)."
            )
        if chosen.kind == "baseline":
            notes.append(
                "No ML model beat the baseline on held-out data, so a simpler, more "
                "transparent model was kept (spec §21)."
            )
        if selection.note:
            notes.append(selection.note)
        if matrix.dropped_rows:
            notes.append(
                f"{matrix.dropped_rows} rows were dropped for missing features/targets rather than imputed."
            )
        notes.append("Crypto trades continuously; there is no session open/close to anchor on.")
        return notes

    def _drift_slices(self, matrix) -> tuple[Dict[str, List[float]], Dict[str, List[float]]]:
        """Reference vs recent per-feature distributions for the drift monitor."""
        if matrix.n_rows < 20:
            return ({}, {})
        array = np.asarray(matrix.X, dtype=float)
        split = int(matrix.n_rows * 0.7)
        reference = {
            name: array[:split, index].tolist() for index, name in enumerate(matrix.feature_names)
        }
        recent = {
            name: array[split:, index].tolist() for index, name in enumerate(matrix.feature_names)
        }
        return (reference, recent)

    def _anomaly(self, candles: Sequence[Candle], duration_seconds: int) -> Optional[AnomalyReport]:
        if len(candles) < 20:
            return None
        from app.crypto.indicators import log_returns

        closes = [c.close for c in candles]
        return detect_outliers(
            returns=[r for r in log_returns(closes) if r is not None],
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=closes,
            window=crypto_settings.realized_vol_window,
        )


def _rmse(result: ValidationResult) -> float:
    value = result.metrics.rmse
    return float(value) if value is not None else float("inf")


# ---------------------------------------------------------------------------
# retrospective evaluation (spec §30)
# ---------------------------------------------------------------------------
def evaluate_forecast(
    *,
    forecast: CryptoForecast,
    actual_price: float,
    actual_timestamp: Optional[datetime] = None,
) -> Dict[str, object]:
    """
    Score a *stored* forecast against the price that actually happened.

    Failed forecasts are never deleted or hidden (spec §30) — this returns the
    real error so it can be persisted alongside the prediction.
    """
    predicted = forecast.prediction
    error = actual_price - predicted
    absolute = abs(error)
    realized_return = (
        math.log(actual_price / forecast.last_close)
        if (actual_price > 0 and forecast.last_close > 0)
        else None
    )
    predicted_return = (
        math.log(predicted / forecast.last_close)
        if (predicted > 0 and forecast.last_close > 0)
        else None
    )
    directional_correct = None
    if realized_return is not None and predicted_return is not None:
        directional_correct = (realized_return > 0) == (predicted_return > 0)

    return {
        "forecast_id": forecast.id,
        "symbol": forecast.symbol,
        "timeframe": forecast.timeframe,
        "predicted": predicted,
        "actual": actual_price,
        "error": error,
        "absolute_error": absolute,
        "percentage_error": (absolute / actual_price) if actual_price else None,
        "realized_return": realized_return,
        "predicted_return": predicted_return,
        "directional_correct": directional_correct,
        "model_name": forecast.model_name,
        "model_version": forecast.model_version,
        "within_interval": (
            forecast.lower_bound is not None
            and forecast.upper_bound is not None
            and forecast.lower_bound <= actual_price <= forecast.upper_bound
        ),
        "evaluated_at": (actual_timestamp or datetime.now(timezone.utc)).isoformat(),
    }


#: Process-wide singleton.
forecast_engine = ForecastEngine()
