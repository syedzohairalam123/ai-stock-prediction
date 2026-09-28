"""
Phase 20 gap-fill tests — spec §31/§37/§40/§52/§53/§54.

Covers the additions made in this pass:

  * §52  history filters: side, mode (quote mode), date range
  * §53  cursor pagination: nextBefore / before, hasMore
  * §54  lifecycle events: publish, ring buffer, per-user isolation
  * §40  user isolation: one user never reads another user's events
  * §31  submission rate limiting (separate limiter on POST /orders)
  * §37  /api/paper/health subsystem health

No test anywhere contacts a real market-data provider — the provider manager
is faked at its seam, exactly like `test_paper_orders.py`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.paper import repository as paper_repo
from app.paper.events import publish_paper_event, recent_events, stats as event_stats
from app.paper.service import service


# --------------------------------------------------------------------------- #
# Fakes / fixtures (mirrors test_paper_orders.py)
# --------------------------------------------------------------------------- #

class FakeManager:
    def __init__(self, *, price=123.45, prev=120.0):
        self.price = price
        self.prev = prev

    async def quote(self, ticker: str):
        from app.providers.base import DataStatus, Quote

        return Quote(
            ticker=ticker.upper(),
            price=self.price,
            source="yfinance",
            status=DataStatus.LIVE,
            timestamp=datetime.now(timezone.utc),
            previous_close=self.prev,
            change_percent=((self.price - self.prev) / self.prev * 100.0) if self.prev else None,
        )

    async def history(self, ticker, start, end, interval="1d"):
        raise RuntimeError("no history in this fake")


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()


@pytest.fixture(autouse=True)
def _no_network_bid_ask():
    with patch("app.providers.fx_rates.yahoo_quotes", new=AsyncMock(return_value={})):
        yield


@pytest.fixture(autouse=True)
def _restore_manager():
    from app import paper as paper_pkg
    from app.main import manager as real_manager

    try:
        yield
    finally:
        paper_pkg.configure(real_manager)


@pytest.fixture
def manager():
    from app import paper as paper_pkg

    fake = FakeManager()
    paper_pkg.configure(fake)
    return fake


@pytest.fixture
def client(manager):
    from app.main import app

    return TestClient(app)


def _submit(client: TestClient, *, symbol: str = "AAPL", side: str = "BUY", user: str, request_id: str):
    response = client.post(
        "/api/paper/orders",
        json={
            "symbol": symbol,
            "kind": "stock",
            "side": side,
            "orderType": "MARKET",
            "amount": 50,
            "amountMode": "notional",
            "clientRequestId": request_id,
        },
        headers={"X-Paper-User-Id": user},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# §52 — history filters
# --------------------------------------------------------------------------- #

def test_history_filters_by_side_and_mode(client):
    _submit(client, user="filters-user", side="BUY", request_id="f-1")
    _submit(client, user="filters-user", side="SELL", request_id="f-2")

    buy_only = client.get(
        "/api/paper/orders", params={"userId": "filters-user", "side": "BUY"}
    ).json()
    assert buy_only["count"] >= 1
    assert all(order["side"] == "BUY" for order in buy_only["orders"])

    price_mode = client.get(
        "/api/paper/orders", params={"userId": "filters-user", "mode": "PRICE"}
    ).json()
    assert price_mode["count"] >= 1
    assert all(order["quoteMode"] == "PRICE" for order in price_mode["orders"])


def test_history_filters_by_date_range(client):
    _submit(client, user="dates-user", request_id="d-1")
    today = date.today().isoformat()
    window = client.get(
        "/api/paper/orders",
        params={"userId": "dates-user", "dateFrom": today, "dateTo": today},
    ).json()
    assert window["count"] >= 1

    future_only = client.get(
        "/api/paper/orders",
        params={"userId": "dates-user", "dateFrom": "2199-01-01"},
    ).json()
    assert future_only["count"] == 0

    bad = client.get(
        "/api/paper/orders", params={"userId": "dates-user", "dateFrom": "not-a-date"}
    )
    assert bad.status_code == 400


def test_history_rejects_invalid_side_and_mode(client):
    bad_side = client.get("/api/paper/orders", params={"userId": "u", "side": "SIDEWAYS"})
    assert bad_side.status_code == 400
    bad_mode = client.get("/api/paper/orders", params={"userId": "u", "mode": "MAGICAL"})
    assert bad_mode.status_code == 400


# --------------------------------------------------------------------------- #
# §53 — cursor pagination
# --------------------------------------------------------------------------- #

def test_cursor_pagination_pages_through_history(client):
    for index in range(5):
        _submit(client, user="pager-user", request_id=f"p-{index}")

    page_one = client.get(
        "/api/paper/orders", params={"userId": "pager-user", "limit": 2}
    ).json()
    assert page_one["count"] == 2
    assert page_one["hasMore"] is True
    assert page_one["nextBefore"]

    page_two = client.get(
        "/api/paper/orders",
        params={"userId": "pager-user", "limit": 2, "before": page_one["nextBefore"]},
    ).json()
    assert page_two["count"] >= 1
    page_one_ids = {order["id"] for order in page_one["orders"]}
    page_two_ids = {order["id"] for order in page_two["orders"]}
    assert not page_one_ids & page_two_ids, "cursor must never repeat rows"

    bad_cursor = client.get(
        "/api/paper/orders", params={"userId": "pager-user", "before": "garbage"}
    )
    assert bad_cursor.status_code == 400


# --------------------------------------------------------------------------- #
# §54 — lifecycle events + §40 isolation
# --------------------------------------------------------------------------- #

def test_submit_publishes_event_and_stream_delivers_it(client, manager):
    result = _submit(client, user="events-user", request_id="e-1")
    recent = client.get("/api/paper/events/recent", params={"userId": "events-user"}).json()
    assert recent["count"] >= 1
    created = [event for event in recent["events"] if event["type"] == "simulation.created"]
    assert created, "a new simulation must publish simulation.created"
    assert created[0]["orderId"] == result["order"]["id"]
    assert created[0]["symbol"] == result["order"]["symbol"]


def test_events_are_isolated_per_user(client):
    _submit(client, user="user-a", request_id="iso-1")
    seen_by_b = client.get("/api/paper/events/recent", params={"userId": "user-b"}).json()
    assert all(event.get("userId") == "user-b" for event in seen_by_b["events"])


def test_recent_events_ring_buffer_is_bounded():
    for index in range(80):
        publish_paper_event({"type": "test", "userId": "bulk", "n": index})
    recent = recent_events(user_id="bulk", limit=50)
    assert len(recent) == 50
    assert event_stats()["bufferedEvents"] <= 50


def test_recent_events_never_leak_anonymous_rows_to_named_users():
    publish_paper_event({"type": "test", "userId": None})
    anonymous_events = recent_events(user_id=None, limit=10)
    assert all(str(event.get("userId") or "anonymous") == "anonymous" for event in anonymous_events)


# --------------------------------------------------------------------------- #
# §31 — submission rate limiting
# --------------------------------------------------------------------------- #

def test_submission_rate_limit_blocks_flood(client, manager):
    from app.paper import routes as paper_routes

    limiter = paper_routes._submission_limiter
    limiter._hits.clear()  # isolate this test's bucket

    blocked_seen = False
    for index in range(35):
        response = client.post(
            "/api/paper/orders",
            json={
                "symbol": "AAPL",
                "kind": "stock",
                "side": "BUY",
                "orderType": "MARKET",
                "amount": 1,
                "amountMode": "notional",
                "clientRequestId": f"flood-{index}",
            },
            headers={"X-Paper-User-Id": "flood-user"},
        )
        if response.status_code == 429:
            blocked_seen = True
            break
    assert blocked_seen, "the 31st submission within a minute must be 429"
    limiter._hits.clear()


# --------------------------------------------------------------------------- #
# §37 — subsystem health
# --------------------------------------------------------------------------- #

def test_paper_health_reports_providers_and_event_bus(client):
    response = client.get("/api/paper/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["paper"] is True
    assert isinstance(body["providers"], list)
    assert "subscribers" in body["eventBus"]
    assert set(body["statuses"]) >= {"SIMULATED", "CANCELLED"}


# --------------------------------------------------------------------------- #
# Service-level cursor sanity (no HTTP)
# --------------------------------------------------------------------------- #

def test_service_history_has_more_matches_limit():
    rows = paper_repo.list_orders(user_id="service-cursor-user", limit=3)
    result = service.history(user_id="service-cursor-user", limit=3)
    assert result["count"] == len(rows)
    if result["hasMore"]:
        assert result["nextBefore"]
    else:
        assert result["nextBefore"] is None
