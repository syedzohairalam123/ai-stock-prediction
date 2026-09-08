"""
Phase 17 — smart alert evaluation.

This module only answers "did this alert's condition become true right
now?" — sending an email/push notification is a separate, later concern
(the `channels` field in the original spec). Checking against real fetched
data (never a random/simulated trigger) is the part that matters here.
"""
from __future__ import annotations

import pandas as pd

SUPPORTED_TYPES = {"price_above", "price_below", "pct_change", "rsi_overbought", "rsi_oversold"}


def evaluate_alerts(df: pd.DataFrame, alerts: list[dict]) -> list[dict]:
    if df.empty or not alerts:
        return []

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    price = float(last["Close"])
    prev_close = float(prev["Close"])
    pct_change = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
    rsi = float(last["rsi_14"]) if "rsi_14" in df.columns and pd.notna(last["rsi_14"]) else None

    triggered = []
    for alert in alerts:
        kind, threshold = alert["alert_type"], alert["threshold"]
        hit, value = False, None
        if kind == "price_above":
            hit, value = price > threshold, price
        elif kind == "price_below":
            hit, value = price < threshold, price
        elif kind == "pct_change":
            hit, value = abs(pct_change) > threshold, pct_change
        elif kind == "rsi_overbought" and rsi is not None:
            hit, value = rsi > threshold, rsi
        elif kind == "rsi_oversold" and rsi is not None:
            hit, value = rsi < threshold, rsi
        if hit:
            triggered.append({**alert, "current_value": round(value, 4)})
    return triggered
