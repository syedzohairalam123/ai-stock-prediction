"""
Phase 21C §19 (spec §50) — esports rate limiting tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.esports import rate_limit
from app.esports.rate_limit import EsportsRateLimitMiddleware, limiter_stats
from app.security import RateLimiter


def _app(limiter: RateLimiter) -> TestClient:
    app = FastAPI()

    @app.get("/api/esports/featured")
    def esports_featured():
        return {"ok": True}

    @app.get("/api/v1/esports/trending/games")
    def analytics_trending():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    app.add_middleware(EsportsRateLimitMiddleware, limiter=limiter)
    return TestClient(app)


def test_middleware_limits_both_esports_prefixes_only():
    client = _app(RateLimiter(max_requests=2, window_seconds=60))

    assert client.get("/api/esports/featured").status_code == 200
    assert client.get("/api/v1/esports/trending/games").status_code == 200
    # Third request across the esports surface is refused.
    blocked = client.get("/api/esports/featured")
    assert blocked.status_code == 429
    assert "rate limit" in blocked.json()["detail"].lower()

    # A non-esports path keeps working — the bucket is scoped, not global.
    assert client.get("/health").status_code == 200


def test_middleware_reports_remaining_budget():
    client = _app(RateLimiter(max_requests=5, window_seconds=60))
    response = client.get("/api/esports/featured")
    assert response.status_code == 200
    assert int(response.headers["X-RateLimit-Remaining"]) == 4


def test_ws_connection_guard_refuses_a_connection_storm(monkeypatch):
    monkeypatch.setattr(rate_limit, "ws_limiter", RateLimiter(max_requests=1, window_seconds=60))
    websocket = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"))

    assert rate_limit.ws_connection_allowed(websocket) is True
    assert rate_limit.ws_connection_allowed(websocket) is False
    # A different client is unaffected.
    other = SimpleNamespace(client=SimpleNamespace(host="203.0.113.10"))
    assert rate_limit.ws_connection_allowed(other) is True


def test_limiter_stats_are_disclosed():
    stats = limiter_stats()
    assert stats["rest_max_requests"] > 0
    assert stats["ws_max_connections"] > 0
    assert stats["rest_window_seconds"] > 0
