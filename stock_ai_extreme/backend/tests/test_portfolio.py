"""
Tests for Phase 10 portfolio tracker:
  - the pure P&L summary math (no network)
  - repository CRUD against the test DB
  - the routes end-to-end with quotes mocked at the manager seam
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app import repository as repo
from app.portfolio import portfolio_summary

from app.providers.base import DataStatus, Quote


# ---------- pure summary math ----------

def _holding(ticker="AAPL", shares=10.0, avg_cost=100.0, **overrides):
    h = {"id": 1, "ticker": ticker, "shares": shares, "avg_cost": avg_cost, "note": None}
    h.update(overrides)
    return h


def test_portfolio_summary_computes_pnl():
    holdings = [_holding(shares=10.0, avg_cost=100.0)]
    result = portfolio_summary(holdings, {"AAPL": 120.0})
    row = result["holdings"][0]
    assert row["cost_basis"] == 1000.0
    assert row["market_value"] == 1200.0
    assert row["pnl"] == 200.0
    assert row["pnl_pct"] == 20.0
    assert result["summary"]["total_pnl"] == 200.0
    assert result["summary"]["total_pnl_pct"] == 20.0
    assert result["summary"]["priced_positions"] == 1


def test_portfolio_summary_missing_quote_is_null_not_fabricated():
    result = portfolio_summary([_holding()], {})  # no quote for AAPL
    row = result["holdings"][0]
    assert row["current_price"] is None
    assert row["market_value"] is None and row["pnl"] is None
    # total value excludes the unpriced holding; reported as such
    assert result["summary"]["priced_positions"] == 0
    assert result["summary"]["total_market_value"] == 0.0


def test_portfolio_summary_mixed_priced_and_unpriced():
    holdings = [_holding(ticker="AAPL", shares=1, avg_cost=100), _holding(ticker="MSFT", shares=2, avg_cost=50)]
    result = portfolio_summary(holdings, {"AAPL": 110.0})
    assert result["summary"]["total_cost_basis"] == 200.0
    assert result["summary"]["total_market_value"] == 110.0
    assert result["summary"]["priced_positions"] == 1
    assert result["summary"]["positions"] == 2


def test_portfolio_summary_empty_holdings():
    result = portfolio_summary([], {})
    assert result["holdings"] == []
    assert result["summary"]["total_pnl"] == 0.0
    assert "disclaimer" in result


def test_portfolio_summary_losing_position_shows_negative_pnl():
    result = portfolio_summary([_holding(shares=5, avg_cost=100)], {"AAPL": 80.0})
    row = result["holdings"][0]
    assert row["pnl"] == -100.0
    assert row["pnl_pct"] == -20.0


# ---------- repository CRUD ----------

@pytest.fixture
def db():
    from app.db import init_db
    init_db()
    yield
    for h in repo.list_holdings():
        repo.delete_holding(h["id"])


def test_holding_repository_roundtrip(db):
    created = repo.add_holding("aapl", 10.0, 150.0, "long-term")
    assert created["ticker"] == "AAPL"  # uppercased
    assert created["shares"] == 10.0 and created["avg_cost"] == 150.0

    listed = repo.list_holdings()
    assert any(h["id"] == created["id"] for h in listed)

    updated = repo.update_holding(created["id"], shares=20.0)
    assert updated["shares"] == 20.0 and updated["avg_cost"] == 150.0

    assert repo.delete_holding(created["id"]) is True
    assert repo.delete_holding(created["id"]) is False  # already gone
    assert repo.get_holding(created["id"]) is None


def test_update_holding_nonexistent_returns_none(db):
    assert repo.update_holding(99999, shares=1.0) is None


# ---------- routes ----------

@pytest.fixture
def client(db):
    from app.main import app
    return TestClient(app)


def test_portfolio_route_crud_and_live_pnl(client):
    # add two positions
    assert client.post("/api/portfolio", json={"ticker": "aapl", "shares": 10, "avg_cost": 100}).status_code == 200
    second = client.post("/api/portfolio", json={"ticker": "MSFT", "shares": 5, "avg_cost": 200}).json()
    assert second["ticker"] == "MSFT"

    # GET quotes both live through the provider manager (yfinance mocked)
    async def fake_quote(ticker: str):
        price = 120.0 if ticker == "AAPL" else 250.0
        return Quote(ticker=ticker, price=price, source="yfinance", status=DataStatus.LIVE)
    with patch("app.main.manager.quote", new=AsyncMock(side_effect=fake_quote)) as mock_quote:
        body = client.get("/api/portfolio").json()
    assert mock_quote.await_count == 2  # one quote per distinct ticker
    aapl = next(h for h in body["holdings"] if h["ticker"] == "AAPL")
    assert aapl["current_price"] == 120.0
    assert aapl["pnl"] == 200.0
    assert body["summary"]["total_pnl"] == 450.0  # AAPL +200, MSFT +250

    # PATCH shares
    assert client.patch(f"/api/portfolio/{second['id']}", json={"shares": 10}).json()["shares"] == 10
    # PATCH with nothing to update is a 400
    assert client.patch(f"/api/portfolio/{second['id']}", json={}).status_code == 400
    # PATCH unknown id is a 404
    assert client.patch("/api/portfolio/99999", json={"shares": 1}).status_code == 404

    # DELETE
    assert client.delete(f"/api/portfolio/{second['id']}").status_code == 200
    assert client.delete(f"/api/portfolio/{second['id']}").status_code == 404


def test_portfolio_add_validates_input(client):
    # Pydantic field constraints (shares > 0, avg_cost >= 0) reject with 422
    assert client.post("/api/portfolio", json={"ticker": "AAPL", "shares": -5, "avg_cost": 100}).status_code == 422
    assert client.post("/api/portfolio", json={"ticker": "AAPL", "shares": 5, "avg_cost": -1}).status_code == 422
    # ticker format validation rejects with 400 (business rule, not schema)
    assert client.post("/api/portfolio", json={"ticker": "bad ticker!!", "shares": 5, "avg_cost": 10}).status_code == 400


def test_portfolio_quote_failure_reported_not_fabricated(client):
    client.post("/api/portfolio", json={"ticker": "AAPL", "shares": 10, "avg_cost": 100})
    from app.providers.base import ProviderError
    with patch("app.main.manager.quote", new=AsyncMock(side_effect=ProviderError("yfinance", "down"))):
        body = client.get("/api/portfolio").json()
    row = body["holdings"][0]
    assert row["current_price"] is None and row["pnl"] is None
    assert body["summary"]["priced_positions"] == 0