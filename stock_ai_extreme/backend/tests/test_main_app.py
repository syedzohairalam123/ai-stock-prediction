"""
End-to-end route tests. yfinance is mocked at the same seam the provider
tests use, so this verifies the whole wire-up (routes -> agents -> manager ->
provider) without needing real network access.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _fake_frame(n_days: int = 150) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0 + (i % 10) for i in range(n_days)],
            "High": [101.0 + (i % 10) for i in range(n_days)],
            "Low": [99.0 + (i % 10) for i in range(n_days)],
            "Close": [100.5 + (i % 10) for i in range(n_days)],
            "Volume": [1_000_000] * n_days,
        },
        index=idx,
    )


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


def test_system_health_reports_providers(client):
    body = client.get("/api/system/health").json()
    assert body["status"] == "ok"
    names = [p["name"] for p in body["providers"]]
    assert "yfinance" in names
    # no FINNHUB_API_KEY set in this test env -> finnhub must not appear as configured
    assert "finnhub" not in names


def test_history_route_returns_rows_and_meta(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            f"/api/stocks/AAPL/history",
            json={"start": str(date.today() - timedelta(days=200)), "end": str(date.today())},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "rows" in body and "meta" in body
    assert body["meta"]["source"] == "yfinance"
    assert len(body["rows"]) > 0


def test_predict_route_returns_predictions_and_data_meta(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            f"/api/stocks/AAPL/predict",
            json={
                "start": str(date.today() - timedelta(days=200)),
                "end": str(date.today()),
                "horizon": 3,
                "model": "ridge",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["predictions"]) == 3
    assert body["data_meta"]["source"] == "yfinance"
    assert "disclaimer" in body


def test_predict_route_random_forest_model(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            "/api/stocks/AAPL/predict",
            json={
                "start": str(date.today() - timedelta(days=200)),
                "end": str(date.today()),
                "horizon": 5,
                "model": "rf",
            },
        )
    assert resp.status_code == 200
    assert len(resp.json()["predictions"]) == 5


def test_predict_route_lstm_fails_gracefully_without_tensorflow(client):
    """TensorFlow isn't installed in this test environment on purpose (it's a
    heavy optional dependency, lazily imported). This confirms that missing it
    produces a clean 400 with a helpful message, not an unhandled crash."""
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            "/api/stocks/AAPL/predict",
            json={
                "start": str(date.today() - timedelta(days=200)),
                "end": str(date.today()),
                "horizon": 3,
                "model": "lstm",
            },
        )
    assert resp.status_code == 400
    assert "tensorflow" in resp.json()["detail"].lower()


def test_profile_route(client):
    fake_info = {
        "longName": "Apple Inc.",
        "sector": "Technology",
        "country": "United States",
        "website": "http://www.apple.com",
        "longBusinessSummary": "Apple designs and sells consumer electronics...",
    }
    with patch("app.providers.yfinance_provider.yf.Ticker") as MockTicker:
        MockTicker.return_value.info = fake_info
        resp = client.get("/api/stocks/AAPL/profile")
    assert resp.status_code == 200
    assert resp.json()["sector"] == "Technology"


def test_history_route_returns_400_when_provider_unavailable(client):
    with patch("app.providers.yfinance_provider.yf.download", side_effect=ConnectionError("down")):
        resp = client.post(
            "/api/stocks/AAPL/history",
            json={"start": str(date.today() - timedelta(days=10)), "end": str(date.today())},
        )
    assert resp.status_code == 400


def test_predict_route_includes_baseline_comparison(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            "/api/stocks/AAPL/predict",
            json={"start": str(date.today() - timedelta(days=200)), "end": str(date.today()), "horizon": 3, "model": "ridge"},
        )
    body = resp.json()
    assert "naive_persistence" in body["baseline_comparison"]
    assert "moving_average_10" in body["baseline_comparison"]
    assert isinstance(body["beats_naive_baseline"], bool)
    assert body["model_metrics"]["interval_method"] in ("conformal_90pct", "gaussian_rmse")


def test_predict_route_ensemble_model(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post(
            "/api/stocks/AAPL/predict",
            json={"start": str(date.today() - timedelta(days=200)), "end": str(date.today()), "horizon": 4, "model": "ensemble"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model_metrics"]["model"] == "ensemble"
    assert set(body["model_metrics"]["components"]) == {"rf", "ridge"}  # TF unavailable in this test env -> degrades gracefully
    assert len(body["predictions"]) == 4


def test_predict_route_is_persisted_and_readable_from_history_endpoint(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        client.post(
            "/api/stocks/XYZTEST/predict",
            json={"start": str(date.today() - timedelta(days=200)), "end": str(date.today()), "horizon": 2, "model": "ridge"},
        )
    history_resp = client.get("/api/stocks/XYZTEST/predictions/history")
    assert history_resp.status_code == 200
    records = history_resp.json()
    assert len(records) >= 1
    assert records[0]["ticker"] == "XYZTEST"


def test_backtest_route(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame(220)):
        resp = client.post(
            "/api/stocks/AAPL/backtest",
            json={"start": str(date.today() - timedelta(days=400)), "end": str(date.today()), "model": "ridge", "test_days": 30, "refit_every": 10},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["daily"]) == 30
    assert "total_return_pct" in body and "max_drawdown_pct" in body
    assert "disclaimer" in body


def test_watchlist_crud_roundtrip(client):
    assert client.post("/api/watchlist", json={"ticker": "nflx", "note": "streaming pick"}).status_code == 200
    listing = client.get("/api/watchlist").json()
    assert any(i["ticker"] == "NFLX" for i in listing)
    assert client.post("/api/watchlist", json={"ticker": "nflx"}).status_code == 409  # duplicate
    assert client.delete("/api/watchlist/nflx").status_code == 200
    assert client.delete("/api/watchlist/nflx").status_code == 404  # already gone
