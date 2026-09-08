"""
Phase 18 — model monitoring & drift detection.

Built entirely on Phase 3's `prediction_history` table: once a forecast's
target date has actually passed, this compares what was predicted against
the real close that happened. This is genuine accuracy tracking — it only
ever measures predictions the app actually made, never a simulated
backtest — which is the whole point of persisting predictions in the first
place.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

import numpy as np


def resolve_predictions(unresolved: list[dict], actual_price_lookup: Callable[[str, date], Optional[float]]) -> list[dict]:
    """`unresolved`: prediction_history records with actual_price still None.
    `actual_price_lookup(ticker, date) -> float | None`: real close for that
    date, or None if it can't be found (e.g. market holiday, bad ticker).
    Uses the FIRST forecasted day of each record as the tracked target — the
    simplest, most horizon-comparable choice."""
    resolved = []
    today = date.today()
    for record in unresolved:
        preds = record.get("predictions") or []
        if not preds:
            continue
        target_date = date.fromisoformat(preds[0]["date"])
        if target_date > today:
            continue  # hasn't happened yet — nothing to compare against
        actual = actual_price_lookup(record["ticker"], target_date)
        if actual is not None:
            resolved.append({
                "id": record["id"], "ticker": record["ticker"], "model": record["model"],
                "predicted_price": preds[0]["price"], "actual_price": round(float(actual), 4),
                "target_date": target_date.isoformat(),
            })
    return resolved


def compute_drift_report(resolved_records: list[dict], window: int = 20) -> dict:
    """`resolved_records` should be in chronological order (oldest first).
    Compares the error over the most recent `window` predictions against
    the full historical average — a rising recent error relative to
    history is the drift signal, not an absolute error threshold (what
    counts as "high error" varies enormously by ticker and price level)."""
    if len(resolved_records) < 5:
        return {"status": "insufficient_data", "sample_size": len(resolved_records),
                "message": "Need at least 5 resolved predictions to say anything meaningful about drift."}

    errors = np.array([abs(r["predicted_price"] - r["actual_price"]) for r in resolved_records])
    overall_mae = float(errors.mean())
    recent = errors[-window:] if len(errors) >= window else errors
    recent_mae = float(recent.mean())
    drift_ratio = round(recent_mae / overall_mae, 4) if overall_mae else 1.0
    # Only call it "detected" once there's enough history on both sides of the
    # comparison to trust it — a ratio computed from 6 total points is noise.
    enough_history = len(errors) >= window * 2
    drift_detected = bool(enough_history and drift_ratio > 1.5)

    return {
        "status": "ok",
        "sample_size": int(len(errors)),
        "overall_mae": round(overall_mae, 4),
        "recent_mae": round(recent_mae, 4),
        "drift_ratio": drift_ratio,
        "drift_detected": drift_detected,
        "message": (
            "Recent prediction error is notably higher than the historical average — model may need retraining."
            if drift_detected else "No significant drift detected."
        ),
    }
