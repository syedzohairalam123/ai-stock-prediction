import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security import RateLimitMiddleware, RateLimiter, validate_ticker


def test_valid_tickers_pass():
    assert validate_ticker("aapl") == "AAPL"
    assert validate_ticker("BRK.B") == "BRK.B"
    assert validate_ticker("eurusd=x") == "EURUSD=X"
    assert validate_ticker("^GSPC") == "^GSPC"
    assert validate_ticker("GC=F") == "GC=F"


def test_invalid_tickers_are_rejected():
    for bad in ["", "  ", "a" * 30, "AAPL; DROP TABLE users;", "<script>alert(1)</script>", "AAPL/../etc"]:
        with pytest.raises(ValueError):
            validate_ticker(bad)


def test_rate_limiter_allows_up_to_the_limit_then_blocks():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    results = [limiter.allow("client-a")[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_rate_limiter_tracks_clients_independently():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("client-a") == (True, 1)
    assert limiter.allow("client-a") == (True, 0)
    assert limiter.allow("client-a")[0] is False
    assert limiter.allow("client-b")[0] is True  # a different client isn't affected


def test_rate_limiter_window_expires_old_hits():
    limiter = RateLimiter(max_requests=1, window_seconds=0.05)
    assert limiter.allow("client-a")[0] is True
    assert limiter.allow("client-a")[0] is False
    time.sleep(0.1)
    assert limiter.allow("client-a")[0] is True  # window has slid past the old hit


def test_rate_limit_middleware_returns_429_once_limit_exceeded():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(max_requests=2, window_seconds=60))

    @app.get("/api/thing")
    def thing():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/api/thing").status_code == 200
    assert client.get("/api/thing").status_code == 200
    third = client.get("/api/thing")
    assert third.status_code == 429


def test_rate_limit_middleware_exempts_health_and_docs():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(max_requests=1, window_seconds=60))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(app)
    for _ in range(5):
        assert client.get("/health").status_code == 200  # exempt path never gets limited
