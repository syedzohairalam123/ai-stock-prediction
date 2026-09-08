from datetime import date, timedelta

import pytest

from app.monitoring import compute_drift_report, resolve_predictions


def test_resolve_predictions_skips_future_dates():
    future = (date.today() + timedelta(days=5)).isoformat()
    records = [{"id": 1, "ticker": "AAPL", "model": "rf", "predictions": [{"date": future, "price": 100.0}]}]
    resolved = resolve_predictions(records, actual_price_lookup=lambda t, d: 105.0)
    assert resolved == []


def test_resolve_predictions_resolves_past_dates_with_a_lookup_hit():
    past = (date.today() - timedelta(days=5)).isoformat()
    records = [{"id": 1, "ticker": "AAPL", "model": "rf", "predictions": [{"date": past, "price": 100.0}]}]
    resolved = resolve_predictions(records, actual_price_lookup=lambda t, d: 103.5)
    assert len(resolved) == 1
    assert resolved[0]["predicted_price"] == 100.0
    assert resolved[0]["actual_price"] == 103.5


def test_resolve_predictions_skips_when_lookup_returns_none():
    past = (date.today() - timedelta(days=2)).isoformat()
    records = [{"id": 1, "ticker": "AAPL", "model": "rf", "predictions": [{"date": past, "price": 100.0}]}]
    resolved = resolve_predictions(records, actual_price_lookup=lambda t, d: None)
    assert resolved == []


def test_resolve_predictions_skips_empty_predictions_list():
    records = [{"id": 1, "ticker": "AAPL", "model": "rf", "predictions": []}]
    assert resolve_predictions(records, actual_price_lookup=lambda t, d: 100.0) == []


def test_drift_report_insufficient_data():
    report = compute_drift_report([{"predicted_price": 100, "actual_price": 101}] * 3)
    assert report["status"] == "insufficient_data"


def test_drift_report_no_drift_when_errors_are_stable():
    records = [{"predicted_price": 100.0, "actual_price": 100.0 + (i % 3)} for i in range(60)]
    report = compute_drift_report(records, window=20)
    assert report["status"] == "ok"
    assert report["drift_detected"] is False


def test_drift_report_detects_a_clear_recent_error_spike():
    stable = [{"predicted_price": 100.0, "actual_price": 100.5} for _ in range(40)]   # error = 0.5
    spiking = [{"predicted_price": 100.0, "actual_price": 110.0} for _ in range(20)]  # error = 10.0
    report = compute_drift_report(stable + spiking, window=20)
    assert report["status"] == "ok"
    assert report["drift_detected"] is True
    assert report["recent_mae"] > report["overall_mae"]
