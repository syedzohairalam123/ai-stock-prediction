import pandas as pd
import pytest

from app.alerts import evaluate_alerts


def _df(closes, rsi=None):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    data = {"Close": closes}
    if rsi is not None:
        data["rsi_14"] = rsi
    return pd.DataFrame(data, index=idx)


def test_price_above_triggers_when_exceeded():
    df = _df([100.0, 105.0])
    alerts = [{"id": 1, "ticker": "AAPL", "alert_type": "price_above", "threshold": 102.0}]
    triggered = evaluate_alerts(df, alerts)
    assert len(triggered) == 1
    assert triggered[0]["current_value"] == 105.0


def test_price_above_does_not_trigger_when_below_threshold():
    df = _df([100.0, 101.0])
    alerts = [{"id": 1, "ticker": "AAPL", "alert_type": "price_above", "threshold": 200.0}]
    assert evaluate_alerts(df, alerts) == []


def test_price_below_triggers():
    df = _df([100.0, 90.0])
    alerts = [{"id": 2, "ticker": "AAPL", "alert_type": "price_below", "threshold": 95.0}]
    triggered = evaluate_alerts(df, alerts)
    assert len(triggered) == 1 and triggered[0]["current_value"] == 90.0


def test_pct_change_triggers_on_large_move_either_direction():
    df_up = _df([100.0, 110.0])   # +10%
    df_down = _df([100.0, 88.0])  # -12%
    alerts = [{"id": 3, "ticker": "X", "alert_type": "pct_change", "threshold": 5.0}]
    assert len(evaluate_alerts(df_up, alerts)) == 1
    assert len(evaluate_alerts(df_down, alerts)) == 1


def test_rsi_overbought_and_oversold():
    df = _df([100.0, 101.0], rsi=[50.0, 82.0])
    overbought = [{"id": 4, "ticker": "X", "alert_type": "rsi_overbought", "threshold": 70.0}]
    oversold = [{"id": 5, "ticker": "X", "alert_type": "rsi_oversold", "threshold": 30.0}]
    assert len(evaluate_alerts(df, overbought)) == 1
    assert evaluate_alerts(df, oversold) == []  # RSI is high, not low


def test_rsi_alert_silently_skipped_when_rsi_column_missing():
    df = _df([100.0, 101.0])  # no rsi_14 column at all
    alerts = [{"id": 6, "ticker": "X", "alert_type": "rsi_overbought", "threshold": 70.0}]
    assert evaluate_alerts(df, alerts) == []  # doesn't crash, just can't evaluate it


def test_empty_alerts_or_empty_df_returns_empty_list():
    df = _df([100.0, 101.0])
    assert evaluate_alerts(df, []) == []
    assert evaluate_alerts(pd.DataFrame(), [{"id": 1, "alert_type": "price_above", "threshold": 1}]) == []


def test_multiple_alerts_only_triggered_ones_are_returned():
    df = _df([100.0, 150.0])
    alerts = [
        {"id": 7, "ticker": "X", "alert_type": "price_above", "threshold": 120.0},   # should trigger
        {"id": 8, "ticker": "X", "alert_type": "price_above", "threshold": 999.0},   # should not
    ]
    triggered = evaluate_alerts(df, alerts)
    assert [t["id"] for t in triggered] == [7]
