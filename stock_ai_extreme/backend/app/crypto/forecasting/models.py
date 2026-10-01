"""
Model candidates + walk-forward validation (spec §22, §23, §26, §80).

Validation is **strictly chronological**: an expanding training window is
extended forward and each fold predicts the block that immediately follows it,
so a model is only ever scored on data that came after everything it was
trained on. Random train/test splitting is never used for a time series — the
only place randomness appears at all is inside an estimator's own internals
(``random_state`` is fixed so a run is reproducible).

Everything is scored on the same rows and with the same metrics, so an ML model
is only preferred over a baseline when it genuinely wins on held-out data
(spec §21, §82).

scikit-learn is used because it is already a dependency of this project.
XGBoost is deliberately absent: it is not installed here, and spec §22 says not
to add a library merely for complexity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.crypto.forecasting.baselines import BaselineForecaster
from app.crypto.forecasting.features import FeatureMatrix
from app.crypto.schemas import ForecastMetrics

#: Reproducibility: every estimator that accepts a seed is given this one.
RANDOM_STATE = 42


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def compute_metrics(
    predicted: Sequence[float],
    actual: Sequence[float],
    *,
    directional_predicted: Optional[Sequence[float]] = None,
    directional_actual: Optional[Sequence[float]] = None,
) -> ForecastMetrics:
    """
    MAE, RMSE, MAPE and directional accuracy (spec §26).

    MAPE is only reported when every actual price is non-zero; a percentage error
    against a zero price is undefined, not infinite.
    """
    if not predicted or not actual or len(predicted) != len(actual):
        return ForecastMetrics(observations=0)

    errors = [float(p) - float(a) for p, a in zip(predicted, actual)]
    mae = float(np.mean(np.abs(errors)))
    rmse = float(math.sqrt(float(np.mean([e * e for e in errors]))))

    mape: Optional[float] = None
    if all(abs(float(a)) > 0 for a in actual):
        mape = float(np.mean([abs(e) / abs(float(a)) for e, a in zip(errors, actual)]))
    else:
        mape = None

    directional_accuracy: Optional[float] = None
    pred_dir = directional_predicted if directional_predicted is not None else predicted
    actual_dir = directional_actual if directional_actual is not None else actual
    if pred_dir and actual_dir and len(pred_dir) == len(actual_dir):
        correct = 0
        counted = 0
        for p, a in zip(pred_dir, actual_dir):
            if p == 0 or a == 0:
                continue  # a flat prediction has no direction to be right about
            counted += 1
            if (p > 0) == (a > 0):
                correct += 1
        directional_accuracy = (correct / counted) if counted else None

    return ForecastMetrics(
        mae=mae,
        rmse=rmse,
        mape=mape,
        directional_accuracy=directional_accuracy,
        observations=len(predicted),
    )


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------
class Candidate:
    """
    One forecastable candidate: fit on training rows, predict test rows.

    Both baselines and ML estimators are wrapped in this shape so validation is
    a single loop over candidates — which is what makes the comparison fair.
    """

    kind = "baseline"

    def __init__(self, name: str, *, description: str = "") -> None:
        self.name = name
        self.description = description

    def fit(self, matrix: FeatureMatrix, train_idx: Sequence[int], closes: Sequence[float]) -> None:
        raise NotImplementedError

    def predict(self, matrix: FeatureMatrix, test_idx: Sequence[int], closes: Sequence[float]) -> List[float]:
        """Predicted future **price** for each test row."""
        raise NotImplementedError

    def feature_importance(self) -> Optional[Dict[str, float]]:
        return None


class BaselineCandidate(Candidate):
    """Adapts a :class:`BaselineForecaster` to the shared candidate interface."""

    kind = "baseline"

    def __init__(self, forecaster: BaselineForecaster, *, horizon: int) -> None:
        super().__init__(forecaster.name, description=f"Baseline: {forecaster.name}")
        self.forecaster = forecaster
        self.horizon = max(1, horizon)

    def fit(self, matrix: FeatureMatrix, train_idx: Sequence[int], closes: Sequence[float]) -> None:
        # Fit on the training slice only — never on the test block.
        if not train_idx:
            return
        last_candle_index = matrix.candle_indices[train_idx[-1]]
        self.forecaster.fit(list(closes[: last_candle_index + 1]))

    def predict(self, matrix: FeatureMatrix, test_idx: Sequence[int], closes: Sequence[float]) -> List[float]:
        out: List[float] = []
        for row in test_idx:
            candle_index = matrix.candle_indices[row]
            history = list(closes[: candle_index + 1])
            predicted_return = self.forecaster.predict_return(history)
            last_close = matrix.base_close[row]
            if predicted_return is None:
                # No usable estimate -> fall back to the last real close, which
                # is the random-walk answer rather than a fabricated move.
                out.append(last_close)
                continue
            out.append(last_close * math.exp(predicted_return))
        return out


class MLCandidate(Candidate):
    """A scikit-learn estimator wrapped to predict price levels from returns."""

    kind = "ml"

    def __init__(
        self,
        name: str,
        factory: Callable[[], object],
        *,
        description: str = "",
        feature_names: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(name, description=description)
        self._factory = factory
        self._model: Optional[object] = None
        self._feature_names = list(feature_names or [])

    def fit(self, matrix: FeatureMatrix, train_idx: Sequence[int], closes: Sequence[float]) -> None:
        X, y = matrix.as_arrays()
        self._model = self._factory()
        self._model.fit(X[list(train_idx)], y[list(train_idx)])  # type: ignore[attr-defined]

    def predict(self, matrix: FeatureMatrix, test_idx: Sequence[int], closes: Sequence[float]) -> List[float]:
        if self._model is None:
            return [matrix.base_close[row] for row in test_idx]
        X, _ = matrix.as_arrays()
        predicted_returns = self._model.predict(X[list(test_idx)])  # type: ignore[attr-defined]
        return [
            matrix.base_close[row] * math.exp(float(value))
            for row, value in zip(test_idx, predicted_returns)
        ]

    def feature_importance(self) -> Optional[Dict[str, float]]:
        model = self._model
        if model is None or not self._feature_names:
            return None
        importances = getattr(model, "feature_importances_", None)
        if importances is None:
            coefficients = getattr(model, "coef_", None)
            if coefficients is None:
                return None
            importances = np.abs(np.asarray(coefficients, dtype=float).ravel())
        values = np.asarray(importances, dtype=float).ravel()
        if len(values) != len(self._feature_names):
            return None
        return {
            name: float(value)
            for name, value in sorted(
                zip(self._feature_names, values), key=lambda pair: pair[1], reverse=True
            )
        }


def default_ml_candidates(*, feature_names: Sequence[str], sample_size: int) -> List[MLCandidate]:
    """
    The classical models worth evaluating for this dataset size (spec §22).

    Model selection depends on the number of rows: a small sample gets the
    regularised linear model only, because a forest on 150 rows is noise. Newer
    candidates are appended as the dataset grows — never forced in.
    """
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge

    candidates: List[MLCandidate] = [
        MLCandidate(
            "ridge",
            lambda: Ridge(alpha=1.0),
            description="L2-regularised linear regression on the engineered features.",
            feature_names=feature_names,
        )
    ]
    if sample_size >= 120:
        candidates.append(
            MLCandidate(
                "random_forest",
                lambda: RandomForestRegressor(
                    n_estimators=200,
                    max_depth=6,
                    min_samples_leaf=3,
                    random_state=RANDOM_STATE,
                    n_jobs=1,
                ),
                description="Random Forest regressor over the causal feature vector.",
                feature_names=feature_names,
            )
        )
    if sample_size >= 200:
        candidates.append(
            MLCandidate(
                "gradient_boosting",
                lambda: GradientBoostingRegressor(
                    n_estimators=150,
                    learning_rate=0.05,
                    max_depth=3,
                    random_state=RANDOM_STATE,
                ),
                description="Gradient-boosted regression trees over the causal feature vector.",
                feature_names=feature_names,
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# walk-forward validation
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    name: str
    kind: str
    metrics: ForecastMetrics
    predicted_prices: List[float] = field(default_factory=list)
    actual_prices: List[float] = field(default_factory=list)
    predicted_returns: List[float] = field(default_factory=list)
    actual_returns: List[float] = field(default_factory=list)
    row_indices: List[int] = field(default_factory=list)
    folds: int = 0
    feature_importance: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "model": self.name,
            "kind": self.kind,
            "metrics": self.metrics.model_dump(),
            "folds": self.folds,
            "observations": self.metrics.observations,
            "feature_importance": self.feature_importance,
        }


def walk_forward_folds(n_rows: int, *, folds: int, min_train: int) -> List[Tuple[int, int]]:
    """
    Expanding-window fold boundaries as ``(train_end, test_end)`` pairs.

    ``train_end`` is exclusive; fold ``i`` trains on ``[0, train_end)`` and tests
    on ``[train_end, test_end)``. Boundaries only ever move forward, which is the
    property that makes this leakage-free (spec §23).
    """
    if n_rows <= 0:
        return []
    if min_train >= n_rows:
        return []
    remaining = n_rows - min_train
    effective_folds = max(1, min(folds, remaining))
    step = max(1, remaining // effective_folds)
    boundaries: List[Tuple[int, int]] = []
    train_end = min_train
    for _ in range(effective_folds):
        test_end = min(n_rows, train_end + step)
        if train_end >= test_end:
            break
        boundaries.append((train_end, test_end))
        train_end = test_end
    # A trailing block shorter than `step` is still real data; include it rather
    # than silently discarding observations.
    if boundaries and boundaries[-1][1] < n_rows:
        boundaries.append((boundaries[-1][1], n_rows))
    return boundaries


def walk_forward_validate(
    candidate: Candidate,
    matrix: FeatureMatrix,
    closes: Sequence[float],
    *,
    folds: int,
    min_train: int,
) -> ValidationResult:
    """Score one candidate with expanding-window walk-forward validation."""
    boundaries = walk_forward_folds(matrix.n_rows, folds=folds, min_train=min_train)
    if not boundaries:
        return ValidationResult(
            name=candidate.name,
            kind=candidate.kind,
            metrics=ForecastMetrics(observations=0),
        )

    predicted_prices: List[float] = []
    actual_prices: List[float] = []
    predicted_returns: List[float] = []
    actual_returns: List[float] = []
    row_indices: List[int] = []

    for train_end, test_end in boundaries:
        train_idx = list(range(0, train_end))
        test_idx = list(range(train_end, test_end))
        if not train_idx or not test_idx:
            continue
        candidate.fit(matrix, train_idx, closes)
        predictions = candidate.predict(matrix, test_idx, closes)
        for row, prediction in zip(test_idx, predictions):
            base = matrix.base_close[row]
            actual_price = base * math.exp(matrix.y[row])
            predicted_prices.append(prediction)
            actual_prices.append(actual_price)
            predicted_returns.append(math.log(prediction / base) if prediction > 0 and base > 0 else 0.0)
            actual_returns.append(matrix.y[row])
            row_indices.append(row)

    metrics = compute_metrics(
        predicted_prices,
        actual_prices,
        directional_predicted=predicted_returns,
        directional_actual=actual_returns,
    )
    return ValidationResult(
        name=candidate.name,
        kind=candidate.kind,
        metrics=metrics,
        predicted_prices=predicted_prices,
        actual_prices=actual_prices,
        predicted_returns=predicted_returns,
        actual_returns=actual_returns,
        row_indices=row_indices,
        folds=len(boundaries),
        feature_importance=candidate.feature_importance(),
    )


def residual_quantiles(residuals: Sequence[float], *, confidence: float = 0.8) -> Tuple[float, float]:
    """
    Empirical prediction-interval bounds from real validation residuals.

    The interval is the asset's own observed error spread — not a normal-theory
    assumption dressed up as certainty (spec §27).
    """
    if not residuals:
        return (0.0, 0.0)
    alpha = max(0.0, min(1.0, (1.0 - confidence) / 2.0))
    lower = float(np.quantile(np.asarray(residuals, dtype=float), alpha))
    upper = float(np.quantile(np.asarray(residuals, dtype=float), 1.0 - alpha))
    return (lower, upper)
