"""End-to-end route tests for the new pages' endpoints — same seam-mocking
approach as test_main_app.py (yfinance mocked at the provider seam)."""
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _fake_frame(n_days: int = 300, base: float = 100.0, drift: float = 0.05) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    closes = [base * (1 + drift) ** i for i in range(n_days)]
    return pd.DataFrame({
        "Open": closes, "High": [c * 1.005 for c in closes], "Low": [c * 0.995 for c in closes],
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    return TestClient(app)


def test_macro_route_yfinance_source(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.get("/api/macro", params={"source": "yfinance"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "yfinance"
    assert body["status"] == "OK"
    assert any(r["key"] == "vix" for r in body["indicators"])
    assert "yield_curve" in body and "regime" in body


def test_macro_route_rejects_bad_source(client):
    resp = client.get("/api/macro", params={"source": "nope"})
    assert resp.status_code == 400


def test_macro_route_fred_without_key_is_unavailable(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.get("/api/macro", params={"source": "fred"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UNAVAILABLE"


def test_event_study_route(client):
    idx = _fake_frame().index
    past_dates = [pd.Timestamp(idx[i]).date().isoformat() for i in (100, 160, 220)]
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame()):
        resp = client.post("/api/stocks/AAPL/events/study", json={"event_dates": past_dates, "label": "Test events"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_study"]["sample_size"] >= 1
    assert "reliability" in body["event_study"]
    assert "not a prediction" in body["disclaimer"]


def test_event_study_route_requires_dates(client):
    resp = client.post("/api/stocks/AAPL/events/study", json={"event_dates": []})
    assert resp.status_code == 400


def test_market_stress_route(client):
    fake_news = [
        {"title": "Markets rally on strong earnings"},
        {"title": "Company X announces new product"},
        {"title": "Sanctions talks continue amid conflict"},
    ]
    with patch("app.providers.yfinance_provider.yf.Ticker") as MockTicker:
        MockTicker.return_value.news = [{"title": n["title"], "providerPublishTime": 1700000000} for n in fake_news]
        resp = client.get("/api/market-stress", params={"ticker": "^GSPC"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["headline_count"] == 3
    assert body["level"] in ("low", "elevated", "high", "severe")


def test_fundamentals_route(client):
    fake_info = {
        "longName": "Apple Inc.", "sector": "Technology",
        "trailingEps": 6.2, "marketCap": 2_900_000_000_000,
        "returnOnEquity": 0.55, "profitMargins": 0.26,
    }
    with patch("app.providers.yfinance_provider.yf.Ticker") as MockTicker, \
         patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame(30)):
        MockTicker.return_value.info = fake_info
        MockTicker.return_value.news = []
        resp = client.get("/api/stocks/AAPL/fundamentals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profitability"]["grade"] == "strong"
    assert "valuation" in body and "dividends" in body


def test_regime_route(client):
    with patch("app.providers.yfinance_provider.yf.download", return_value=_fake_frame(300, drift=0.3)):
        resp = client.get("/api/stocks/AAPL/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["rule_based"]["regime"] in ("trending_up", "trending_down", "range_bound", "high_volatility")


def test_crypto_route_coingecko_mocked(client):
    fake = [{
        "id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 65000.0,
        "price_change_percentage_24h_in_currency": 1.0, "price_change_percentage_7d_in_currency": 2.0,
        "price_change_percentage_30d_in_currency": 3.0, "market_cap": 1_280_000_000_000,
        "market_cap_rank": 1, "total_volume": 3e10, "circulating_supply": 19_700_000,
        "ath": 73000.0, "ath_change_percentage": -10.0,
    }]
    with patch("app.crypto_pro._fetch_coingecko_markets", return_value=fake):
        resp = client.post("/api/crypto/overview", json={"source": "coingecko"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "OK"
    assert body["coins"][0]["symbol"] == "BTC-USD"


def test_crypto_route_rejects_bad_source(client):
    resp = client.post("/api/crypto/overview", json={"source": "nope"})
    assert resp.status_code == 400


def test_screener_route(client):
    def fake_download(ticker, **kwargs):
        return _fake_frame(300, drift=0.2)
    with patch("app.providers.yfinance_provider.yf.download", side_effect=fake_download):
        resp = client.post("/api/screener", json={"tickers": ["AAPL", "MSFT"], "lookback_days": 365})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scanned"] == 2
    assert len(body["ranked"]) == 2
    assert body["ranked"][0]["rank"] == 1
    assert "not investment advice" in body["methodology"]["note"].lower()


def test_screener_defaults_route(client):
    body = client.get("/api/screener/defaults").json()
    assert isinstance(body["tickers"], list) and len(body["tickers"]) > 0
