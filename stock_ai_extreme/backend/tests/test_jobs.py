"""
Tests for the background maintenance loop's individual jobs. The loop
itself runs forever by design, so these test the two real pieces of logic
(check_all_alerts, resolve_all_predictions) in isolation with the provider
manager mocked at the same seam as the route tests.
"""
import asyncio
from collections import deque
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

import pandas as pd


def _run(coro):
    return asyncio.run(coro)

from app import jobs, repository as repo
from app.security import RateLimiter


@pytest.fixture(autouse=True)
def _init_db():
    """These tests touch the database (alerts/predictions) directly — unlike
    route tests there is no TestClient fixture here to do it, so create the
    tables explicitly."""
    from app.db import init_db
    init_db()


def _fake_frame(n_days=70, end=None, last_close=107.25):
    idx = pd.date_range(end=end or pd.Timestamp(date.today()), periods=n_days, freq="B")
    closes = [100.0 + (i % 5) for i in range(n_days - 1)] + [last_close]
    return pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


def test_check_all_alerts_marks_and_notifies_triggered():
    alert = repo.create_alert("AAPL", "price_above", 1.0)  # trivially exceeded
    try:
        manager = AsyncMock()
        manager.history.return_value = (_fake_frame(), "yfinance", type("S", (), {"value": "LIVE"})())
        with patch("app.jobs.notify") as mock_notify:
            triggered = _run(jobs.check_all_alerts(manager))
        assert len(triggered) == 1
        assert triggered[0]["id"] == alert["id"]
        # no longer active after being triggered
        active = repo.list_alerts(active_only=True)
        assert all(a["id"] != alert["id"] for a in active)
        mock_notify.assert_called_once()
        subject = mock_notify.call_args[0][0]
        assert "AAPL" in subject
    finally:
        repo.delete_alert(alert["id"])


def test_check_all_alerts_skips_when_none_active():
    assert repo.list_alerts(active_only=True) == []
    with patch("app.jobs.notify") as mock_notify:
        triggered = _run(jobs.check_all_alerts(AsyncMock()))
    assert triggered == []
    mock_notify.assert_not_called()


def test_check_all_alerts_isolates_single_ticker_failure():
    a1 = repo.create_alert("AAPL", "price_above", 1.0)
    a2 = repo.create_alert("MSFT", "price_above", 1.0)
    try:
        manager = AsyncMock()
        async def side_effect(ticker, start, end):
            if ticker == "MSFT":
                raise ConnectionError("down")
            return _fake_frame(), "yfinance", type("S", (), {"value": "LIVE"})()
        manager.history.side_effect = side_effect
        with patch("app.jobs.notify"):
            triggered = _run(jobs.check_all_alerts(manager))
        assert {t["ticker"] for t in triggered} == {"AAPL"}  # MSFT failure did not abort the run
    finally:
        repo.delete_alert(a1["id"]); repo.delete_alert(a2["id"])


def test_resolve_all_predictions_resolves_past_forecasts():
    past_target = pd.bdate_range(end=pd.Timestamp(date.today() - timedelta(days=3)), periods=1)[0].date().isoformat()
    record_id = repo.save_prediction(
        ticker="JOBSTEST", model="ridge", horizon=1, data_source="yfinance", data_status="LIVE",
        predictions=[{"date": past_target, "price": 100.0}], metrics={"mae": 1.0},
    )
    try:
        manager = AsyncMock()
        # frame whose last row is exactly the target date with a known close
        manager.history.return_value = (_fake_frame(end=pd.Timestamp(past_target), last_close=107.25), "yfinance", None)
        resolved_count = _run(jobs.resolve_all_predictions(manager))
        assert resolved_count >= 1
        updated = repo.get_prediction_history("JOBSTEST")[0]
        assert updated["actual_price"] == 107.25
    finally:
        pass  # prediction records are deliberately never deleted in tests


def test_resolve_all_predictions_skips_future_forecasts():
    future_target = pd.bdate_range(start=pd.Timestamp(date.today() + timedelta(days=3)), periods=1)[0].date().isoformat()
    repo.save_prediction(
        ticker="FUTURETEST", model="ridge", horizon=1, data_source="yfinance", data_status="LIVE",
        predictions=[{"date": future_target, "price": 100.0}], metrics={},
    )
    manager = AsyncMock()
    resolved_count = _run(jobs.resolve_all_predictions(manager))
    # the future forecast must stay unresolved; other (past) records from
    # other tests may or may not be present, so only FUTURETEST is checked
    fut = repo.get_prediction_history("FUTURETEST")[0]
    assert fut["actual_price"] is None
    assert resolved_count >= 0


def test_rate_limiter_cleanup_drops_idle_buckets():
    limiter = RateLimiter(max_requests=10, window_seconds=60)
    limiter.allow("active")
    # simulate an old bucket by injecting one with a stale timestamp
    limiter._hits["stale"] = deque([1.0])  # 1.0 is long before now
    assert "stale" in limiter._hits
    dropped = limiter.cleanup()
    assert dropped >= 1
    assert "stale" not in limiter._hits
    assert "active" in limiter._hits  # recently-touched bucket survives