"""Forecasting: leakage-safe features, baselines, classical ML, walk-forward validation."""

from __future__ import annotations

from app.crypto.forecasting.baselines import BASELINE_FAMILY
from app.crypto.forecasting.drift import AnomalyReport, DriftReport, detect_outliers, drift_monitor
from app.crypto.forecasting.engine import (
    ENGINE_VERSION,
    ForecastOutcome,
    evaluate_forecast,
    forecast_engine,
    model_version,
)
from app.crypto.forecasting.features import FEATURE_VERSION, FeatureMatrix, build_features

__all__ = [
    "BASELINE_FAMILY",
    "ENGINE_VERSION",
    "FEATURE_VERSION",
    "AnomalyReport",
    "DriftReport",
    "FeatureMatrix",
    "ForecastOutcome",
    "build_features",
    "detect_outliers",
    "drift_monitor",
    "evaluate_forecast",
    "forecast_engine",
    "model_version",
]
