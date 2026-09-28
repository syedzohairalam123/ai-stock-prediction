"""
Phase 20 — Quick Order / Paper Trading Ticket tests.

Coverage mirrors the acceptance list in the phase brief:

  * instrument classification (stock / crypto / commodity / forex / index / forecast)
  * input validation — invalid number, negative, zero, excessive precision,
    missing price, missing symbol, NaN/Infinity
  * paper P&L arithmetic (BUY/SELL, event-probability mode)
  * limit-order condition evaluation against real observations
  * idempotency (same request id twice → one simulation)
  * stale-quote protection
  * the API surface end to end, with the provider manager faked at its seam

No test anywhere contacts a real market-data provider.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.paper import instruments as inst
from app.paper import pnl as paper_pnl
from app.paper import repository as paper_repo
from app.paper.instruments import InstrumentKind, QuoteMode, classify_symbol, resolve_instrument
from app.paper.quotes import historical_volatility_percent
from app.paper.simulation import (
    STATUS_CANCELLED,
    STATUS_SIMULATED,
    SimulationEngine,
    SimulationInput,
    explain_order_type,
)
from app.paper.validation import validate_simulation_request
from app.providers.base import DataStatus, Quote


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeManager:
    """A provider manager stub — real shapes, no network."""

    def __init__(self, *, price=123.45, prev=120.0, status=DataStatus.LIVE, frame=None, fail=False):
        self.price = price
        self.prev = prev
        self.status = status
        self.frame = frame
        self.fail = fail
        self.quote_calls = 0
        self.history_calls = 0

    async def quote(self, ticker: str) -> Quote:
        self.quote_calls += 1
        if self.fail:
            return Quote(ticker=ticker.upper(), price=float("nan"), source="none", status=DataStatus.UNAVAILABLE)
        return Quote(
            ticker=ticker.upper(),
            price=self.price,
            source="yfinance",
            status=self.status,
            timestamp=datetime.now(timezone.utc),
            previous_close=self.prev,
            change_percent=((self.price - self.prev) / self.prev * 100.0) if self.prev else None,
        )

    async def history(self, ticker, start, end, interval="1d"):
        self.history_calls += 1
        if self.frame is None:
            raise RuntimeError("no history in this fake")
        return self.frame, "yfinance", DataStatus.LIVE


def _frame(days: int = 30, last_close: float = 130.0, low: float = 118.0, high: float = 131.0) -> pd.DataFrame:
    idx = pd.date_range(end=date.today(), periods=days, freq="B")
    closes = [120.0 + (i % 5) for i in range(days - 1)] + [last_close]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [max(h, c) for h, c in zip([high] * days, closes)],
            "Low": [min(l, c) for l, c in zip([low] * days, closes)],
            "Close": closes,
            "Volume": [1_000_000] * days,
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _init_db():
    from app.db import init_db

    init_db()


@pytest.fixture(autouse=True)
def _no_network_bid_ask():
    """Never let the bid/ask enrichment reach Yahoo in a test."""
    with patch("app.providers.fx_rates.yahoo_quotes", new=AsyncMock(return_value={})):
        yield


@pytest.fixture(autouse=True)
def _restore_manager():
    """Always hand the real provider manager back after a test, so a test that
    installs a fake cannot leak into the next one."""
    from app import paper as paper_pkg
    from app.main import manager as real_manager

    try:
        yield
    finally:
        paper_pkg.configure(real_manager)


@pytest.fixture
def manager():
    from app import paper as paper_pkg

    fake = FakeManager(frame=_frame())
    paper_pkg.configure(fake)
    yield fake


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app

    init_db()
    return TestClient(app)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Instrument classification (spec §2, §14)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("OGDC", InstrumentKind.STOCK),
        ("AAPL", InstrumentKind.STOCK),
        ("BTC-USD", InstrumentKind.CRYPTO),
        ("ETH-USD", InstrumentKind.CRYPTO),
        ("GC=F", InstrumentKind.COMMODITY),
        ("SI=F", InstrumentKind.COMMODITY),
        ("EURUSD=X", InstrumentKind.FOREX),
        ("USDPKR=X", InstrumentKind.FOREX),
        ("^GSPC", InstrumentKind.INDEX),
        ("^VIX", InstrumentKind.INDEX),
    ],
)
def test_classify_symbol_by_shape(symbol, expected):
    assert classify_symbol(symbol) == expected


def test_resolve_rejects_malformed_symbol():
    with pytest.raises(ValueError):
        resolve_instrument("   ")
    with pytest.raises(ValueError):
        resolve_instrument("A" * 40)  # far outside the ticker pattern


def test_forecast_instrument_uses_probability_mode():
    instrument = resolve_instrument("FORECAST:abc123")
    assert instrument.kind is InstrumentKind.FORECAST
    assert instrument.quote_mode is QuoteMode.PROBABILITY
    assert instrument.market_id == "abc123"
    # A forecast event is never "bought" or "sold".
    assert instrument.sides == ("YES", "NO")
    assert instrument.is_forecast is True


def test_client_kind_hint_cannot_downgrade_a_forecast_or_override_shape():
    # A hint may refine a plain stock into an index, but never turn a crypto
    # pair into a stock.
    assert resolve_instrument("KSE100", "INDEX").kind is InstrumentKind.INDEX
    assert resolve_instrument("BTC-USD", "STOCK").kind is InstrumentKind.CRYPTO
    assert resolve_instrument("FORECAST:x", "STOCK").kind is InstrumentKind.FORECAST


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        resolve_instrument("AAPL", "BOND")


# --------------------------------------------------------------------------- #
# Validation (spec §7)
# --------------------------------------------------------------------------- #

def _validate(**overrides):
    base = dict(
        instrument=resolve_instrument("AAPL"),
        instrument_error=None,
        side="BUY",
        order_type="MARKET",
        amount=10.0,
        amount_mode="NOTIONAL",
        limit_price=None,
        reference_price=100.0,
        client_timestamp=None,
        symbol="AAPL",
    )
    base.update(overrides)
    return validate_simulation_request(**base)


def _codes(result):
    return {issue.code for issue in result.issues}


def test_validation_accepts_a_sane_request():
    assert _validate().ok is True


def test_validation_rejects_missing_symbol():
    assert "missing_symbol" in _codes(_validate(symbol=""))


def test_validation_rejects_unknown_instrument():
    result = _validate(instrument=None, instrument_error="nope")
    assert "unknown_instrument" in _codes(result)


def test_validation_rejects_zero_and_negative_amount():
    assert "zero_amount" in _codes(_validate(amount=0))
    assert "negative_amount" in _codes(_validate(amount=-5))


def test_validation_rejects_nan_and_infinity():
    assert "invalid_number" in _codes(_validate(amount=float("nan")))
    assert "invalid_number" in _codes(_validate(amount=float("inf")))


def test_validation_rejects_excessive_precision():
    assert "excessive_precision" in _codes(_validate(amount=10.123456))


def test_validation_rejects_missing_limit_price():
    codes = _codes(_validate(order_type="LIMIT", limit_price=None))
    assert "missing_price" in codes


def test_validation_rejects_order_type_and_side_vocabularies():
    assert "invalid_order_type" in _codes(_validate(order_type="STOP"))
    assert "invalid_side" in _codes(_validate(side="HOLD"))
    forecast = resolve_instrument("FORECAST:m1")
    assert "invalid_side" in _codes(_validate(instrument=forecast, side="BUY"))


def test_validation_rejects_missing_reference_price():
    assert "missing_reference_price" in _codes(_validate(reference_price=None))


def test_validation_rejects_far_future_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    assert "timestamp_in_future" in _codes(_validate(client_timestamp=future))


def test_validation_rejects_above_maximum_notional():
    from app.paper.config import paper_settings

    assert "above_maximum" in _codes(_validate(amount=paper_settings.paper_max_notional + 1))


# --------------------------------------------------------------------------- #
# Paper P&L (spec §13)
# --------------------------------------------------------------------------- #

def test_pnl_long_wins_when_price_rises():
    result = paper_pnl.compute_pnl("BUY", 100.0, 110.0, 10)
    assert result is not None
    assert result.hypothetical_pnl == pytest.approx(100.0)
    assert result.hypothetical_pnl_percent == pytest.approx(10.0)
    assert result.unit == "PRICE"


def test_pnl_short_wins_when_price_falls():
    result = paper_pnl.compute_pnl("SELL", 100.0, 90.0, 10)
    assert result is not None
    assert result.hypothetical_pnl == pytest.approx(100.0)


def test_pnl_short_loses_when_price_rises():
    result = paper_pnl.compute_pnl("SELL", 100.0, 110.0, 10)
    assert result.hypothetical_pnl == pytest.approx(-100.0)


def test_pnl_probability_mode_reports_percentage_points_not_a_payout():
    result = paper_pnl.compute_pnl("YES", 40.0, 55.0, 100.0, QuoteMode.PROBABILITY)
    assert result is not None
    assert result.unit == "PERCENTAGE_POINTS"
    assert result.price_difference == pytest.approx(15.0)
    # No monetary return is invented for a forecast selection.
    assert result.hypothetical_pnl_percent is None


def test_pnl_never_fabricates_a_result_from_bad_numbers():
    assert paper_pnl.compute_pnl("BUY", float("nan"), 110.0, 10) is None
    assert paper_pnl.compute_pnl("BUY", 100.0, float("inf"), 10) is None
    assert paper_pnl.compute_pnl("BUY", 100.0, 110.0, 0) is None
    assert paper_pnl.compute_pnl("HOLD", 100.0, 110.0, 10) is None


def test_quantity_and_notional_helpers():
    assert paper_pnl.quantity_from_notional(100.0, 25.0) == pytest.approx(4.0)
    assert paper_pnl.quantity_from_notional(100.0, 0) is None
    assert paper_pnl.position_notional(4.0, 25.0) == pytest.approx(100.0)
    assert paper_pnl.position_notional(float("inf"), 25.0) is None


# --------------------------------------------------------------------------- #
# Limit-order condition (spec §12)
# --------------------------------------------------------------------------- #

def test_limit_buy_fills_when_low_reaches_the_limit():
    assert paper_pnl.limit_condition_met("BUY", 95.0, observed_low=94.5) is True
    assert paper_pnl.limit_condition_met("BUY", 95.0, observed_low=99.0) is False


def test_limit_sell_fills_when_high_reaches_the_limit():
    assert paper_pnl.limit_condition_met("SELL", 105.0, observed_high=105.5) is True
    assert paper_pnl.limit_condition_met("SELL", 105.0, observed_high=101.0) is False


def test_limit_condition_is_unknown_without_an_observation():
    # Unknown must never be coerced to "did not fill".
    assert paper_pnl.limit_condition_met("BUY", 95.0) is None
    assert paper_pnl.limit_condition_met("BUY", 0) is None


def test_evaluate_limit_fill_returns_the_first_matching_observation():
    bars = [
        {"timestamp": "2026-01-02T00:00:00+00:00", "low": 99.0, "high": 101.0, "close": 100.0},
        {"timestamp": "2026-01-03T00:00:00+00:00", "low": 94.0, "high": 102.0, "close": 96.0},
    ]
    fill = paper_pnl.evaluate_limit_fill("BUY", 95.0, bars)
    assert fill is not None
    assert fill["timestamp"] == "2026-01-03T00:00:00+00:00"
    assert fill["fillReference"] == 95.0

    assert paper_pnl.evaluate_limit_fill("BUY", 50.0, bars) is None


def test_summarize_activity_ignores_non_finite_pnl():
    summary = paper_pnl.summarize_paper_activity(
        [
            {"status": "SIMULATED", "pnl": 10.0},
            {"status": "SIMULATED", "pnl": float("nan")},
            {"status": "CANCELLED"},
        ]
    )
    assert summary["total"] == 3
    assert summary["simulated"] == 2
    assert summary["cancelled"] == 1
    assert summary["resolved"] == 1
    assert summary["hypotheticalTotalPnl"] == pytest.approx(10.0)


def test_order_type_explanation_is_honest_about_simulation():
    text = explain_order_type("MARKET")
    assert "No exchange is contacted" in text
    assert "LIMIT" in explain_order_type("LIMIT")


# --------------------------------------------------------------------------- #
# Volatility (spec §20)
# --------------------------------------------------------------------------- #

def test_historical_volatility_needs_real_observations():
    assert historical_volatility_percent([]) is None
    assert historical_volatility_percent([1.0, 2.0, 3.0]) is None
    series = [100.0 + (i % 7) for i in range(80)]
    value = historical_volatility_percent(series)
    assert value is not None and value >= 0


# --------------------------------------------------------------------------- #
# Quote layer (spec §8, §17)
# --------------------------------------------------------------------------- #

def test_quote_is_unavailable_rather_than_zero(manager):
    from app.paper.quotes import build_quote

    manager.fail = True
    quote = run(build_quote(resolve_instrument("AAPL")))
    assert quote.price is None
    assert quote.data_mode == "UNAVAILABLE"
    assert quote.stale is True


def test_quote_carries_price_change_and_source(manager):
    from app.paper.quotes import build_quote

    quote = run(build_quote(resolve_instrument("AAPL")))
    assert quote.price == pytest.approx(123.45)
    assert quote.change_percent == pytest.approx((123.45 - 120.0) / 120.0 * 100.0)
    assert quote.source == "yfinance"
    assert quote.volatility_percent is not None


def test_stale_provider_status_marks_the_quote_stale(manager):
    from app.paper.quotes import build_quote

    manager.status = DataStatus.STALE
    quote = run(build_quote(resolve_instrument("AAPL")))
    assert quote.stale is True
    assert quote.data_mode == "STALE"


def test_forecast_quote_uses_probability_not_price(manager):
    from app.paper.quotes import build_quote

    market = {
        "id": "m1",
        "title": "Will X happen?",
        "yesProbability": 62.5,
        "noProbability": 37.5,
        "status": "OPEN",
        "closeTime": "2026-12-31T00:00:00+00:00",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": [{"name": "Polymarket public market data", "url": "https://example.com"}],
    }
    with patch("app.forecast_markets.fetch_market_by_id", new=AsyncMock(return_value=market)):
        quote = run(build_quote(resolve_instrument("FORECAST:m1")))
    assert quote.quote_mode == QuoteMode.PROBABILITY.value
    assert quote.probability_yes == pytest.approx(62.5)
    assert quote.probability_no == pytest.approx(37.5)
    assert quote.price is None  # never a price for a forecast event
    assert quote.data_mode == "LIVE"


# --------------------------------------------------------------------------- #
# Simulation engine (spec §10, §11)
# --------------------------------------------------------------------------- #

def test_market_order_is_anchored_to_the_observed_price(manager):
    from app.paper.quotes import build_quote

    instrument = resolve_instrument("AAPL")
    quote = run(build_quote(instrument))
    record = SimulationEngine.build_order(
        instrument,
        quote,
        SimulationInput(side="BUY", order_type="MARKET", amount=1000.0, amount_mode="NOTIONAL"),
        opened_snapshot={},
    )
    assert record["reference_price"] == pytest.approx(123.45)
    assert record["quantity"] == pytest.approx(1000.0 / 123.45)
    assert record["status"] == STATUS_SIMULATED
    assert record["condition_met"] is True


def test_limit_order_is_not_assumed_to_have_filled(manager):
    from app.paper.quotes import build_quote

    instrument = resolve_instrument("AAPL")
    quote = run(build_quote(instrument))
    record = SimulationEngine.build_order(
        instrument,
        quote,
        SimulationInput(side="BUY", order_type="LIMIT", amount=1000.0, amount_mode="NOTIONAL", limit_price=100.0),
        opened_snapshot={},
    )
    # Undecided — not False, because nothing has been observed yet.
    assert record["condition_met"] is None
    assert record["reference_price"] == pytest.approx(100.0)
    assert record["expires_at"] is not None


def test_preview_flags_a_stale_reference(manager):
    from app.paper.quotes import build_quote

    manager.status = DataStatus.STALE
    instrument = resolve_instrument("AAPL")
    quote = run(build_quote(instrument))
    preview = SimulationEngine.preview(
        instrument, quote, SimulationInput(side="BUY", order_type="MARKET", amount=100.0, amount_mode="NOTIONAL")
    )
    assert preview["stale"] is True
    assert any("STALE DATA" in w for w in preview["warnings"])
    assert preview["banner"].startswith("PAPER SIMULATION")


def test_engine_evaluate_never_fabricates_an_exit_price(manager):
    from app.paper.quotes import build_quote

    instrument = resolve_instrument("AAPL")
    quote = run(build_quote(instrument))
    order = SimulationEngine.build_order(
        instrument,
        quote,
        SimulationInput(side="BUY", order_type="MARKET", amount=100.0, amount_mode="NOTIONAL"),
        opened_snapshot={},
    )
    order["id"] = "test"
    result = SimulationEngine.evaluate(order, instrument, bars=[])
    assert result["updates"].get("exit_reference") is None
    assert "pnl" not in result
    assert "No newer real observation" in result["message"]


def test_engine_evaluate_computes_pnl_from_real_bars(manager):
    from app.paper.quotes import build_quote

    instrument = resolve_instrument("AAPL")
    quote = run(build_quote(instrument))
    order = SimulationEngine.build_order(
        instrument,
        quote,
        SimulationInput(side="BUY", order_type="MARKET", amount=1000.0, amount_mode="NOTIONAL"),
        opened_snapshot={},
    )
    order["id"] = "test"
    bars = [{"timestamp": "2026-01-05T00:00:00+00:00", "low": 118.0, "high": 140.0, "close": 140.0}]
    result = SimulationEngine.evaluate(order, instrument, bars=bars)
    assert result["updates"]["exit_reference"] == pytest.approx(140.0)
    assert result["updates"]["pnl"] > 0


# --------------------------------------------------------------------------- #
# HTTP surface (spec §23, §24, §25, §27)
# --------------------------------------------------------------------------- #

def _submit_body(**overrides):
    body = {
        "symbol": "AAPL",
        "kind": "STOCK",
        "side": "BUY",
        "orderType": "MARKET",
        "amount": 100.0,
        "amountMode": "NOTIONAL",
        "clientRequestId": "req-1",
        "userId": "tester",
    }
    body.update(overrides)
    return body


def test_market_instrument_route_returns_instrument_and_quote(client, manager):
    resp = client.get("/api/market/instrument/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["instrument"]["kind"] == "STOCK"
    assert body["quote"]["price"] == pytest.approx(123.45)
    assert body["paper"] is True
    assert body["banner"].startswith("PAPER SIMULATION")


def test_market_quote_route_classifies_crypto(client, manager):
    resp = client.get("/api/market/quote/BTC-USD")
    assert resp.status_code == 200
    assert resp.json()["instrument"]["kind"] == "CRYPTO"


def test_market_config_route_publishes_limits(client):
    body = client.get("/api/market/config").json()
    assert body["maxNotional"] > 0
    assert "SIMULATED" in body["statuses"]
    assert body["paper"] is True


def test_preview_route_writes_nothing(client, manager):
    before = client.get("/api/paper/orders", params={"userId": "tester"}).json()["count"]
    resp = client.post("/api/paper/preview", json=_submit_body())
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["preview"]["banner"].startswith("PAPER SIMULATION")
    after = client.get("/api/paper/orders", params={"userId": "tester"}).json()["count"]
    assert after == before


def test_submit_creates_a_simulation_and_is_idempotent(client, manager):
    first = client.post("/api/paper/orders", json=_submit_body(clientRequestId="dup-1"))
    assert first.status_code == 200
    body = first.json()
    assert body["order"]["status"] == STATUS_SIMULATED
    assert body["duplicate"] is False

    second = client.post("/api/paper/orders", json=_submit_body(clientRequestId="dup-1"))
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["order"]["id"] == body["order"]["id"]

    listed = client.get("/api/paper/orders", params={"userId": "tester", "symbol": "AAPL"}).json()
    assert listed["count"] == 1


def test_submit_rejects_invalid_amounts(client, manager):
    # JSON cannot carry NaN, so the wire-level cases are zero, negative and
    # over-precise; NaN/Infinity are covered directly on the validator above.
    for bad in (0, -1, 10.999, None):
        resp = client.post(
            "/api/paper/orders",
            json=_submit_body(userId="invalid-only", amount=bad, clientRequestId=f"bad-{bad}"),
        )
        assert resp.status_code in (400, 422), (bad, resp.status_code)
    # Nothing was recorded for that user: a rejected simulation leaves no row.
    assert client.get("/api/paper/orders", params={"userId": "invalid-only"}).json()["count"] == 0


def test_submit_rejects_limit_without_price(client, manager):
    resp = client.post(
        "/api/paper/orders",
        json=_submit_body(orderType="LIMIT", limitPrice=None, clientRequestId="limit-missing"),
    )
    assert resp.status_code == 422
    issues = resp.json()["detail"]["issues"]
    assert any(i["code"] == "missing_price" for i in issues)


def test_submit_refuses_unavailable_quote(client):
    from app import paper as paper_pkg

    paper_pkg.configure(FakeManager(fail=True))
    resp = client.post("/api/paper/orders", json=_submit_body(clientRequestId="unavailable"))
    assert resp.status_code == 422
    resp2 = client.get("/api/market/quote/AAPL")
    assert resp2.json()["quote"]["price"] is None


def test_stale_quote_requires_explicit_acknowledgement(client):
    from app import paper as paper_pkg

    paper_pkg.configure(FakeManager(status=DataStatus.STALE, frame=_frame()))
    blocked = client.post("/api/paper/orders", json=_submit_body(clientRequestId="stale-1"))
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["issues"][0]["code"] == "stale_quote"

    allowed = client.post(
        "/api/paper/orders",
        json=_submit_body(clientRequestId="stale-2", acknowledgeStale=True),
    )
    assert allowed.status_code == 200
    assert allowed.json()["order"]["dataMode"] == "STALE"


def test_history_is_scoped_per_user(client, manager):
    client.post("/api/paper/orders", json=_submit_body(userId="alice", clientRequestId="alice-1"))
    client.post("/api/paper/orders", json=_submit_body(userId="bob", clientRequestId="bob-1"))
    alice = client.get("/api/paper/orders", params={"userId": "alice"}).json()
    assert alice["count"] == 1
    assert alice["separateFromPortfolio"] is True


def test_get_one_order_and_audit_trail(client, manager):
    order_id = client.post("/api/paper/orders", json=_submit_body(clientRequestId="audit-1")).json()["order"]["id"]
    detail = client.get(f"/api/paper/orders/{order_id}")
    assert detail.status_code == 200
    assert detail.json()["order"]["id"] == order_id

    audit = client.get(f"/api/paper/orders/{order_id}/audit").json()
    assert audit["count"] >= 1
    assert any(e["event"] == "SUBMITTED" for e in audit["entries"])


def test_get_missing_order_is_a_404(client, manager):
    assert client.get("/api/paper/orders/does-not-exist").status_code == 404


def test_cancel_marks_the_simulation_cancelled(client, manager):
    order_id = client.post("/api/paper/orders", json=_submit_body(clientRequestId="cancel-1")).json()["order"]["id"]
    resp = client.post(f"/api/paper/orders/{order_id}/cancel", json={"reason": "changed my mind"})
    assert resp.status_code == 200
    assert resp.json()["order"]["status"] == STATUS_CANCELLED


def test_evaluate_returns_pnl_from_real_subsequent_bars(client, manager):
    order_id = client.post(
        "/api/paper/orders",
        json=_submit_body(clientRequestId="eval-1", amount=1000.0),
    ).json()["order"]["id"]

    async def _bars(symbol, after, **kwargs):
        return [{"timestamp": datetime.now(timezone.utc).isoformat(), "low": 118.0, "high": 140.0, "close": 140.0}]

    with patch("app.paper.service.observed_bars_after", new=_bars):
        resp = client.post(f"/api/paper/orders/{order_id}/evaluate")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["order"]["exitReference"] == pytest.approx(140.0)
    assert payload["order"]["pnl"] > 0
    assert payload["result"]["paper"] is True


def test_evaluate_without_new_data_reports_no_pnl(client):
    """When neither newer bars nor a live quote are real, the evaluation must
    report that honestly instead of inventing an exit price."""
    from app import paper as paper_pkg

    paper_pkg.configure(FakeManager(frame=_frame()))
    order_id = client.post("/api/paper/orders", json=_submit_body(clientRequestId="eval-2")).json()["order"]["id"]

    # The provider itself goes away for the evaluation pass.
    paper_pkg.configure(FakeManager(fail=True))

    async def _no_bars(symbol, after, **kwargs):
        return []

    with patch("app.paper.service.observed_bars_after", new=_no_bars):
        resp = client.post(f"/api/paper/orders/{order_id}/evaluate")
    assert resp.status_code == 200
    assert resp.json()["order"]["pnl"] is None
    assert "No newer real observation" in resp.json()["result"]["message"]


def test_summary_route_reports_paper_activity(client, manager):
    client.post("/api/paper/orders", json=_submit_body(clientRequestId="sum-1"))
    body = client.get("/api/paper/summary", params={"userId": "tester"}).json()
    assert body["summary"]["total"] >= 1
    assert body["separateFromPortfolio"] is True


def test_list_rejects_an_unknown_status_filter(client):
    resp = client.get("/api/paper/orders", params={"status": "EXECUTED"})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Portfolio separation + expiry (spec §19, §11)
# --------------------------------------------------------------------------- #

def test_paper_orders_never_reach_the_real_portfolio_tables(client, manager):
    client.post("/api/paper/orders", json=_submit_body(clientRequestId="sep-1"))
    holdings = client.get("/api/portfolio").json()
    tickers = [h["ticker"] for h in holdings.get("holdings", [])]
    assert "AAPL" not in tickers


def test_expire_due_marks_only_overdue_limit_simulations(manager):
    from app.paper.service import service

    created = run(
        service.submit(
            symbol="AAPL",
            kind="STOCK",
            side="BUY",
            order_type="LIMIT",
            amount=100.0,
            amount_mode="NOTIONAL",
            limit_price=50.0,
            user_id="expiry-user",
            client_request_id="expire-1",
        )
    )
    order_id = created["order"]["id"]

    # Pull the expiry forward so the row is genuinely overdue.
    paper_repo.update_order(order_id, expires_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    changed = service.expire_due()
    assert changed >= 1
    assert paper_repo.get_order(order_id)["status"] == "EXPIRED"


def test_repository_round_trip_preserves_simulation_only_flags(manager):
    from app.paper.service import service

    created = run(
        service.submit(
            symbol="EURUSD=X",
            kind="FOREX",
            side="SELL",
            order_type="MARKET",
            amount=500.0,
            amount_mode="NOTIONAL",
            user_id="fx-user",
            client_request_id="fx-1",
        )
    )
    order = created["order"]
    assert order["paper"] is True
    assert order["simulationOnly"] is True
    assert order["instrumentKind"] == "FOREX"
    assert order["status"].startswith("SIMULATED")
