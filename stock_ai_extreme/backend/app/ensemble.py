"""
Phase 7 — ensemble forecasting.

Combines RF + Ridge (always available) with LSTM + GRU (only if TensorFlow
is installed — this degrades gracefully instead of failing) via
inverse-RMSE-weighted averaging: a model with lower historical error gets
more say in the combined forecast. The spread between individual models'
forecasts for the same date is reported as `model_disagreement` — high
disagreement is a genuine signal ("the models don't agree, treat this
forecast with extra caution"), not something to average away and hide.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def combine_forecasts(model_outputs: dict[str, tuple[list[dict], dict]]) -> tuple[list[dict], dict]:
    if not model_outputs:
        raise ValueError("No underlying model produced a forecast to ensemble.")

    names = list(model_outputs.keys())
    horizon = len(next(iter(model_outputs.values()))[0])

    weights = {n: 1.0 / max(model_outputs[n][1].get("rmse", 1e-6), 1e-6) for n in names}
    total_w = sum(weights.values())
    weights = {n: w / total_w for n, w in weights.items()}

    combined = []
    for i in range(horizon):
        prices = [model_outputs[n][0][i]["price"] for n in names]
        lowers = [model_outputs[n][0][i]["lower"] for n in names]
        uppers = [model_outputs[n][0][i]["upper"] for n in names]
        date = model_outputs[names[0]][0][i]["date"]
        weighted_price = sum(weights[n] * model_outputs[n][0][i]["price"] for n in names)
        disagreement = float(np.std(prices)) if len(prices) > 1 else 0.0
        combined.append({
            "date": date,
            "price": round(weighted_price, 4),
            # Conservative combined interval: the widest span any single
            # component model considered plausible, not just the average.
            "lower": round(min(lowers), 4),
            "upper": round(max(uppers), 4),
            "model_disagreement": round(disagreement, 4),
        })

    combined_metrics = {
        "model": "ensemble",
        "components": names,
        "weights": {n: round(w, 4) for n, w in weights.items()},
        "mae": round(sum(weights[n] * model_outputs[n][1]["mae"] for n in names), 4),
        "rmse": round(sum(weights[n] * model_outputs[n][1]["rmse"] for n in names), 4),
    }
    return combined, combined_metrics


def run_ensemble(
    df: pd.DataFrame,
    horizon: int,
    tabular_forecaster: Callable[[pd.DataFrame, int, str], tuple[list[dict], dict]],
    lstm_forecaster: Callable[[pd.DataFrame, int], tuple[list[dict], dict]] | None = None,
    gru_forecaster: Callable[[pd.DataFrame, int], tuple[list[dict], dict]] | None = None,
) -> tuple[list[dict], dict]:
    """Orchestrates: always run RF + Ridge; add LSTM/GRU only if a forecaster
    was provided AND it doesn't fail (e.g. TensorFlow missing) — a component
    model being unavailable shrinks the ensemble, it never crashes it."""
    outputs: dict[str, tuple[list[dict], dict]] = {}
    for kind in ("rf", "ridge"):
        outputs[kind] = tabular_forecaster(df, horizon, kind)

    for name, forecaster in (("lstm", lstm_forecaster), ("gru", gru_forecaster)):
        if forecaster is None:
            continue
        try:
            outputs[name] = forecaster(df, horizon)
        except ValueError:
            # TensorFlow missing, or too little data for a recurrent model —
            # skip this component rather than failing the whole ensemble.
            continue

    return combine_forecasts(outputs)
