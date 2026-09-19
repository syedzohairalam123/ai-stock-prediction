"""Phase 7 — forex center tests.

All network access is mocked at the fx_rates seam, so these run offline and
assert the things that actually matter: what happens to messy real-world input
(inverted quotes, missing sides, stale timestamps, an unreachable source) and
that a source which only publishes daily is never reported as LIVE.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app import forex
from app.providers import fx_rates


def _raw(currency: str, **kwargs) -> fx_rates.RawQuote:
    symbol = fx_rates.PKR_CROSS_SYMBOLS.get(currency, "TEST=X")
    defaults = dict(
        symbol=symbol,
        price=277.27,
        previous_close=277.04,
        bid=277.27,
        ask=277.60,
        timestamp_epoch=fx_rates.utc_now_epoch(),
        currency="PKR",
        granularity=fx_rates.GRANULARITY_REALTIME,
        status="LIVE",
    )
    defaults.update(kwargs)
    return fx_rates.RawQuote(**defaults)


def _all_raw(**overrides) -> dict:
    return {fx_rates.PKR_CROSS_SYMBOLS[c]: _raw(c, **overrides) for c in forex.SUPPORTED_CURRENCIES}


# ---------------------------------------------------------------------------
# bid / ask / mid / spread
# ---------------------------------------------------------------------------


def test_bid_ask_mid_and_spread_are_computed_from_the_published_sides():
    bid, ask, mid, spread, spread_pct, note = forex.normalize_bid_ask(277.27, 277.60)
    assert (bid, ask) == (277.27, 277.60)
    assert mid == pytest.approx(277.435)
    assert spread == pytest.approx(0.33)
    assert spread_pct == pytest.approx(0.11894, rel=1e-4)
    assert note is None


def test_inverted_bid_ask_is_rejected_rather_than_shown_as_a_negative_spread():
    """Yahoo really does return bid > ask for USD-quoted majors (EURUSD, GBPUSD).
    Keeping those levels would render a negative spread as if it were tradable."""
    bid, ask, mid, spread, spread_pct, note = forex.normalize_bid_ask(1.1600928, 1.1594203)
    assert (bid, ask, mid, spread, spread_pct) == (None, None, None, None, None)
    assert note and "inverted" in note


def test_missing_bid_or_ask_is_dropped_individually():
    assert forex.normalize_bid_ask(None, 277.6)[5] == "bid unavailable from source"
    assert forex.normalize_bid_ask(277.27, None)[5] == "ask unavailable from source"


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), "not a number"])
def test_zero_negative_and_non_finite_sides_never_survive(bad):
    bid, ask, mid, spread, _, _ = forex.normalize_bid_ask(bad, 277.6)
    assert bid is None and mid is None and spread is None


def test_quote_falls_back_to_the_sources_own_price_when_bid_ask_are_unusable():
    quote = forex.build_quote("USD", _raw("USD", bid=277.9, ask=277.1, price=277.27))
    assert quote.mid == pytest.approx(277.27)
    assert quote.bid is None and quote.ask is None
    assert quote.data_mode == "LIVE"
    assert quote.change == pytest.approx(0.23)


def test_quote_reports_a_positive_and_a_negative_change_without_flipping_signs():
    up = forex.build_quote("GBP", _raw("GBP", price=374.5, bid=374.5, ask=374.6, previous_close=374.0))
    down = forex.build_quote("JPY", _raw("JPY", price=1.79, bid=1.79, ask=1.80, previous_close=1.82))
    assert up.change is not None and up.change > 0 and up.change_percent > 0
    assert down.change is not None and down.change < 0 and down.change_percent < 0


# ---------------------------------------------------------------------------
# freshness + data mode (spec O / G)
# ---------------------------------------------------------------------------


def test_freshness_uses_configurable_thresholds_against_the_source_timestamp():
    now = 1_800_000_000.0
    assert forex.get_data_freshness(now - 60, now_epoch=now) == "FRESH"
    assert forex.get_data_freshness(now - 7200, now_epoch=now, fresh_seconds=900, aging_seconds=21600) == "AGING"
    assert forex.get_data_freshness(now - 400000, now_epoch=now, fresh_seconds=900, aging_seconds=21600) == "STALE"
    assert forex.get_data_freshness(None, now_epoch=now) == "UNKNOWN"
    # an implausible timestamp is UNKNOWN, never silently "fresh"
    assert forex.get_data_freshness(now + 999999, now_epoch=now) == "UNKNOWN"
    assert forex.get_data_freshness(1, now_epoch=now) == "UNKNOWN"


def test_daily_published_source_is_never_called_live():
    now = 1_800_000_000.0
    mode = forex.classify_data_mode(now - 10, fx_rates.GRANULARITY_DAILY, now_epoch=now)
    assert mode == "DELAYED"


def test_realtime_source_is_live_only_inside_the_live_window():
    now = 1_800_000_000.0
    assert forex.classify_data_mode(now - 30, fx_rates.GRANULARITY_REALTIME, now_epoch=now) == "LIVE"
    assert forex.classify_data_mode(now - 7200, fx_rates.GRANULARITY_REALTIME, now_epoch=now) == "DELAYED"
    assert forex.classify_data_mode(None, fx_rates.GRANULARITY_REALTIME, now_epoch=now, has_value=False) == "UNAVAILABLE"


def test_a_rate_older_than_the_stale_window_is_refused_not_shown_as_current():
    now = 1_800_000_000.0
    ancient = now - (forex.settings.fx_stale_threshold_seconds + 86400)
    assert forex.classify_data_mode(ancient, fx_rates.GRANULARITY_REALTIME, now_epoch=now) == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# currency validation + pair parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["USD", "PKR", "AED", "SAR", "JPY", "eur", " gbp "])
def test_valid_currency_codes_accepted(code):
    assert forex.is_valid_currency(code)


@pytest.mark.parametrize("code", ["", "US", "USDD", "ZZZ", "123", None])
def test_invalid_currency_codes_rejected(code):
    assert not forex.is_valid_currency(code)


def test_parse_pair_accepts_the_shapes_a_user_actually_types():
    assert forex.parse_pair("USD/PKR") == ("USD", "PKR")
    assert forex.parse_pair("usdpkr") == ("USD", "PKR")
    assert forex.parse_pair("EUR-PKR") == ("EUR", "PKR")
    # A well-formed pair with a code we don't quote parses fine — only PKR-quoted
    # pairs exist here, and the route is what rejects the pair with a clear 400.
    assert forex.parse_pair("USD/EUR") == ("USD", "EUR")
    with pytest.raises(ValueError):
        forex.parse_pair("nonsense")
    with pytest.raises(ValueError):
        forex.parse_pair("FOO/BAR")


# ---------------------------------------------------------------------------
# orchestration: primary source, labelled fallback, honest failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_eight_currencies_render_and_a_healthy_run_skips_the_fallback():
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_all_raw())) as quotes, \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock()) as fallback:
        payload = await forex.build_forex_quotes()

    assert quotes.await_count == 1
    assert fallback.await_count == 0, "a healthy live run must not pay for a second source"
    assert payload["count"] == 8
    assert {q["base_currency"] for q in payload["quotes"]} == set(forex.SUPPORTED_CURRENCIES)
    assert all(q["quote_currency"] == "PKR" for q in payload["quotes"])
    assert payload["live_count"] == 8
    assert payload["failed"] == []


@pytest.mark.asyncio
async def test_missing_primary_quote_falls_back_to_the_daily_source_and_says_so():
    partial = _all_raw()
    partial.pop(fx_rates.PKR_CROSS_SYMBOLS["SAR"])
    fallback_payload = {
        "base": "USD",
        "rates": {"PKR": 277.589643, "SAR": 3.75},
        "updated_epoch": fx_rates.utc_now_epoch() - 3600,
        "source": fx_rates.SOURCE_ERAPI,
        "granularity": fx_rates.GRANULARITY_DAILY,
    }
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=partial)), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock(return_value=fallback_payload)):
        payload = await forex.build_forex_quotes()

    sar = next(q for q in payload["quotes"] if q["base_currency"] == "SAR")
    assert sar["source"] == fx_rates.SOURCE_ERAPI
    assert sar["data_mode"] == "DELAYED", "a daily publication is never LIVE"
    assert sar["mid"] == pytest.approx(277.589643 / 3.75, rel=1e-6)
    assert sar["bid"] is None and sar["ask"] is None
    assert payload["fallback_source"] == fx_rates.SOURCE_ERAPI


@pytest.mark.asyncio
async def test_total_source_outage_yields_unavailable_rather_than_a_fabricated_rate():
    dead = {fx_rates.PKR_CROSS_SYMBOLS[c]: _raw(c, price=None, bid=None, ask=None, status="UNAVAILABLE", error="boom")
            for c in forex.SUPPORTED_CURRENCIES}
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=dead)), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock(side_effect=RuntimeError("network down"))):
        payload = await forex.build_forex_quotes()

    assert payload["live_count"] == 0
    assert len(payload["failed"]) == 8
    assert all(q["mid"] is None for q in payload["quotes"])
    assert all(q["data_mode"] == "UNAVAILABLE" for q in payload["quotes"])
    assert payload["fallback_error"] == "network down"


@pytest.mark.asyncio
async def test_unrecognised_requested_currency_is_reported_not_silently_dropped():
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_all_raw())), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock(return_value={"rates": {}, "updated_epoch": None})):
        payload = await forex.build_forex_quotes(["USD", "ZZZ"])
    assert payload["rejected_currencies"] == ["ZZZ"]
    assert [q["base_currency"] for q in payload["quotes"]] == ["USD"]


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_forex_route_returns_eight_pkr_pairs(client):
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_all_raw())), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock()):
        resp = client.get("/api/forex")
    assert resp.status_code == 200
    body = resp.json()
    assert body["base"] == "PKR"
    assert body["count"] == 8
    assert body["data_meta"]["status"] == "LIVE"
    assert body["thresholds"]["live_seconds"] > 0
    assert "not investment advice" in body["disclaimer"].lower() or "not a dealing price" in body["disclaimer"]


def test_forex_route_accepts_a_currency_subset(client):
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_all_raw())), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock()):
        resp = client.get("/api/forex", params={"currencies": "usd, eur"})
    assert resp.status_code == 200
    assert [q["base_currency"] for q in resp.json()["quotes"]] == ["USD", "EUR"]


@pytest.mark.parametrize("path", ["/api/forex/USD/PKR", "/api/forex/USDPKR", "/api/forex/USD-PKR"])
def test_forex_single_route_serves_one_pair(client, path):
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_all_raw())), \
         patch.object(fx_rates, "usd_currency_rates", AsyncMock()):
        resp = client.get(path)
    assert resp.status_code == 200, resp.text
    assert resp.json()["quote"]["symbol"] == "USD/PKR"


def test_forex_single_route_rejects_a_non_pkr_quote_currency(client):
    resp = client.get("/api/forex/USD/EUR")
    assert resp.status_code == 400
    assert "PKR" in resp.json()["detail"]


def test_forex_single_route_rejects_unparsable_pairs(client):
    resp = client.get("/api/forex/notapair")
    assert resp.status_code == 400
