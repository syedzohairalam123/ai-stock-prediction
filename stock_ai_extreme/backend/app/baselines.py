"""
Phase 6 — baseline models.

Rule (carried over from the project's own spec): every "advanced" model must
be shown next to a trivial baseline, and a model that loses to the baseline
must not be hidden or dressed up as if it won. These two baselines are
deliberately dumb on purpose — that's what makes them a fair yardstick.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error


def _evaluate_1step(y_true: pd.Series, y_pred: pd.Series) -> dict:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(mean_squared_error(y_true, y_pred) ** 0.5)
    direction_true = np.sign(y_true.values - y_true.shift(1).bfill().values)
    direction_pred = np.sign(y_pred.values - y_true.shift(1).bfill().values)
    directional_accuracy = float(np.mean(direction_true == direction_pred))
    return {"mae": round(mae, 4), "rmse": round(rmse, 4), "directional_accuracy": round(directional_accuracy, 4)}


def evaluate_naive_persistence(df: pd.DataFrame) -> dict:
    """Baseline #1: tomorrow's close = today's close. The single most common
    baseline in forecasting — surprisingly hard for many models to beat."""
    z = df[["Close"]].copy()
    z["target"] = z.Close.shift(-1)
    z = z.dropna()
    metrics = _evaluate_1step(z["target"], z["Close"])
    metrics["name"] = "naive_persistence"
    return metrics


def evaluate_moving_average(df: pd.DataFrame, window: int = 10) -> dict:
    """Baseline #2: tomorrow's close = the trailing N-day average close."""
    z = df[["Close"]].copy()
    z["ma"] = z.Close.rolling(window).mean()
    z["target"] = z.Close.shift(-1)
    z = z.dropna()
    metrics = _evaluate_1step(z["target"], z["ma"])
    metrics["name"] = f"moving_average_{window}"
    return metrics


def forecast_naive_persistence(df: pd.DataFrame, horizon: int) -> list[float]:
    last = float(df.Close.iloc[-1])
    return [last] * horizon


def forecast_moving_average(df: pd.DataFrame, horizon: int, window: int = 10) -> list[float]:
    ma = float(df.Close.tail(window).mean())
    return [ma] * horizon


def baseline_report(df: pd.DataFrame) -> dict:
    """Both baselines' historical 1-step-ahead performance, for comparison
    against whatever ML model the caller is presenting."""
    return {
        "naive_persistence": evaluate_naive_persistence(df),
        "moving_average_10": evaluate_moving_average(df, window=10),
    }
