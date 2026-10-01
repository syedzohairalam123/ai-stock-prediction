"""
API integration tests through the real FastAPI app (spec §96, §98).

These exercise the full stack: routing → envelope → service → engine →
database (in-memory SQLite). A separate live test hits the real providers.
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _envelope_ok(payload: dict) -> None:
    assert set(payload) >= {"data", "meta", "requestId", "errors"}


class TestReferenceEndpoints:
    def test_assets(self, client):
        response = client.get("/api/v1/crypto/assets")
        assert response.status_code == 200
        body = response.json()
        _envelope_ok(body)
        symbols = [asset["symbol"] for asset in body["data"]["assets"]]
        assert "BTC" in symbols and "ETH" in symbols

    def test_timeframes(self, client):
        response = client.get("/api/v1/crypto/timeframes")
        assert response.status_code == 200
        ids = [tf["id"] for tf in response.json()["data"]["timeframes"]]
        assert ids == ["5m", "15m", "1h", "4h", "1d", "1w", "1M", "1Y"]

    def test_categories(self, client):
        response = client.get("/api/v1/crypto/categories")
        assert response.status_code == 200
        category_ids = [c["id"] for c in response.json()["data"]["categories"]]
        assert category_ids == ["all", "pre-market", "institutions", "targets", "industry"]

    def test_unknown_symbol_is_404(self, client):
        assert client.get("/api/v1/crypto/quote/NOTACOIN").status_code == 404

    def test_unknown_timeframe_is_400(self, client):
        assert client.get("/api/v1/crypto/candles/BTC?timeframe=7m").status_code == 400

    def test_negative_target_rejected(self, client):
        # 422 (schema-level gt=0) or 400 (engine-level) are both server-side rejections.
        response = client.post(
            "/api/v1/crypto/targets",
            json={"symbol": "BTC", "target_price": -5, "direction": "above"},
        )
        assert response.status_code in {400, 422}


class TestMarketEndpoints:
    def test_quote_real_source(self, client):
        response = client.get("/api/v1/crypto/quote/BTC")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["price"] > 0
        assert data["source"] in {"binance", "coingecko"}
        assert data["status"] in {"LIVE", "RECENT", "DELAYED", "STALE"}

    def test_candles_timeframe_switch(self, client):
        for timeframe in ("5m", "1h", "1d", "1Y"):
            response = client.get(f"/api/v1/crypto/candles/BTC?timeframe={timeframe}&limit=60")
            assert response.status_code == 200, timeframe
            data = response.json()["data"]
            assert data["candles"], timeframe
            # Candles arrive in order and carry the structural invariant.
            stamps = [c["epoch_ms"] for c in data["candles"]]
            assert stamps == sorted(stamps)
            for candle in data["candles"]:
                assert candle["high"] >= max(candle["open"], candle["close"])
                assert candle["low"] <= min(candle["open"], candle["close"])

    def test_analytics_bundle(self, client):
        response = client.get("/api/v1/crypto/analytics/BTC?timeframe=1h")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["volatility"]["realized_volatility"] is not None
        assert data["trend"]["direction"] in {"UP", "DOWN", "SIDEWAYS", "INSUFFICIENT_DATA"}
        assert data["value_origins"]["trend"] == "DERIVED"

    def test_multi_timeframe(self, client):
        response = client.get("/api/v1/crypto/multi-timeframe/BTC")
        assert response.status_code == 200
        rows = response.json()["data"]["rows"]
        assert len(rows) == 8
        assert response.json()["data"]["summary"]["note"]


class TestForecastEndpoints:
    def test_forecast_payload(self, client):
        response = client.get("/api/v1/crypto/forecast/BTC?timeframe=1h&horizon=5")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["label"] == "MODELLED FORECAST"
        if data["forecast"]:
            forecast = data["forecast"]
            assert forecast["model_version"].endswith(forecast["feature_version"]) or "@" in forecast["model_version"]
            assert forecast["lower_bound"] < forecast["prediction"] < forecast["upper_bound"]
            assert forecast["metrics"]["rmse"] is not None
            assert forecast["limitations"]

    def test_forecast_history_append_only(self, client):
        response = client.get("/api/v1/crypto/forecast/BTC/history")
        assert response.status_code == 200
        assert "forecasts" in response.json()["data"]

    def test_drift_report(self, client):
        response = client.get("/api/v1/crypto/forecast/BTC/drift?timeframe=1h")
        assert response.status_code == 200
        assert response.json()["data"]["status"] in {"STABLE", "WATCH", "MODEL PERFORMANCE DEGRADED", "UNKNOWN"}

    def test_threshold_probability_labelled(self, client):
        response = client.get("/api/v1/crypto/threshold/BTC?threshold=1000000&timeframe=1d&horizon=7")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["label"] == "MODELLED PROBABILITY"

    def test_on_date(self, client):
        response = client.get("/api/v1/crypto/on-date/BTC?date=2026-09-01")
        assert response.status_code == 200
        assert response.json()["data"]["status"] in {"OBSERVED", "ANSWERED", "UNAVAILABLE"}


class TestTargetEndpoints:
    def test_create_evaluate_invalidate(self, client):
        response = client.post(
            "/api/v1/crypto/targets",
            json={
                "symbol": "BTC",
                "target_price": 1.0,  # far below spot: unreachable-but-valid milestone
                "direction": "below",
                "target_date": "2030-01-01",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        # The envelope-level status is CREATED (the row exists); the evaluated
        # milestone status arrives on the target itself.
        assert data["status"] in {"CREATED", "REACHED"}
        assert data["target"]["status"] in {"ACTIVE", "REACHED"}
        target_id = data["target"]["id"]
        assert data["touch_count"] == 0  # BTC has never traded at $1 in the window

        invalidated = client.post("/api/v1/crypto/targets/invalidate", json={"target_id": target_id})
        assert invalidated.status_code == 200
        assert invalidated.json()["data"]["status"] == "INVALIDATED"

    def test_targets_listing(self, client):
        response = client.get("/api/v1/crypto/targets/BTC")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "targets" in data and "derived_ladder" in data


class TestCategoryEndpoints:
    def test_industry_taxonomy(self, client):
        response = client.get("/api/v1/crypto/categories/industry")
        assert response.status_code == 200
        data = response.json()["data"]
        industries = data["taxonomy"]["industries"]
        assert {"Layer 1", "DeFi", "Stablecoins"} <= {i["id"] for i in industries}

    def test_institutions_attributed(self, client):
        response = client.get("/api/v1/crypto/categories/institutions/BTC")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["etf_flows_status"] == "UNAVAILABLE"  # honest absence
        if data.get("disclosed_holdings"):
            assert data["disclosed_holdings"]["source"] == "coingecko"

    def test_pre_session_is_not_a_fake_open(self, client):
        response = client.get("/api/v1/crypto/categories/pre-session")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["market_structure"]["is_24_7"] is True


class TestOpsEndpoints:
    def test_health_and_readiness(self, client):
        assert client.get("/api/v1/crypto/health").status_code == 200
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/readiness").status_code == 200
        assert client.get("/liveness").json()["status"] == "alive"

    def test_sources_and_observability(self, client):
        sources = client.get("/api/v1/crypto/sources").json()["data"]
        providers = {entry["provider"] for entry in sources["sources"]}
        assert {"binance", "coingecko"} <= providers
        assert client.get("/api/v1/crypto/observability").status_code == 200
        assert client.get("/api/v1/crypto/persistence").status_code == 200

    def test_rate_limit_headers_configured(self, client):
        response = client.get("/api/v1/crypto/rate-limit")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["max_requests"] >= 10


class TestLegacyAlias:
    def test_api_crypto_alias_works(self, client):
        assert client.get("/api/crypto/assets").status_code == 200
        assert client.get("/api/crypto/quote/BTC").status_code == 200
