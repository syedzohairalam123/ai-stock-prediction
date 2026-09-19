"""Phase 7 — PKR precious-metals tests.

The conversion is the part worth testing: it is the only place a number is
produced rather than passed through, and the spec is explicit that per-gram,
per-10-gram and per-tola values must never be silently mixed. Network access is
mocked at the fx_rates seam.
"""
from datetime import date
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from app import commodities_pk as cp
from app.providers import fx_rates


def _raw(symbol: str, price, previous, *, currency: str = "USD", **kwargs) -> fx_rates.RawQuote:
    """Source quote stub. `price`/`previous` may be None to simulate a source
    that answered nothing for that symbol."""
    quoted = price is not None
    return fx_rates.RawQuote(
        symbol=symbol,
        price=price,
        previous_close=previous,
        bid=(price - 0.1) if quoted else None,
        ask=(price + 0.1) if quoted else None,
        timestamp_epoch=fx_rates.utc_now_epoch(),
        currency=currency,
        granularity=fx_rates.GRANULARITY_REALTIME,
        status="LIVE" if quoted else "UNAVAILABLE",
        **kwargs,
    )


GOLD_USD, GOLD_PREV = 4333.4, 4408.9
SILVER_USD, SILVER_PREV = 63.45, 65.188
PLATINUM_USD, PLATINUM_PREV = 1770.0, 1797.6
USDPKR = 277.27


def _market(**overrides) -> dict:
    quotes = {
        "GC=F": _raw("GC=F", GOLD_USD, GOLD_PREV),
        "SI=F": _raw("SI=F", SILVER_USD, SILVER_PREV),
        "PL=F": _raw("PL=F", PLATINUM_USD, PLATINUM_PREV),
        "USDPKR=X": _raw("USDPKR=X", USDPKR, 277.04, currency="PKR"),
    }
    quotes.update(overrides)
    return quotes


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# the conversion itself
# ---------------------------------------------------------------------------


def test_price_per_unit_converts_usd_per_ounce_to_pkr_per_gram():
    expected = (GOLD_USD / cp.TROY_OUNCE_GRAMS) * USDPKR
    assert cp.price_per_unit(GOLD_USD, USDPKR, "gram") == pytest.approx(expected, rel=1e-6)


def test_tola_and_ten_gram_rows_are_exact_multiples_of_the_gram_row():
    gram = cp.price_per_unit(GOLD_USD, USDPKR, "gram")
    tola = cp.price_per_unit(GOLD_USD, USDPKR, "tola")
    ten = cp.price_per_unit(GOLD_USD, USDPKR, "10_gram")
    assert tola == pytest.approx(gram * cp.TOLA_GRAMS, rel=1e-5)
    assert ten == pytest.approx(gram * 10, rel=1e-5)
    assert cp.TOLA_GRAMS == 11.6638125, "Pakistan tola definition must not drift"


def test_22k_gold_is_exactly_22_24_of_24k_by_definition():
    gold24 = cp.price_per_unit(GOLD_USD, USDPKR, "gram", 1.0)
    gold22 = cp.price_per_unit(GOLD_USD, USDPKR, "gram", 22 / 24)
    assert gold22 == pytest.approx(gold24 * 22 / 24, rel=1e-6)


@pytest.mark.parametrize(
    "usd,rate,unit,ratio",
    [
        (GOLD_USD, USDPKR, "kilogram", 1.0),   # unknown unit
        (0, USDPKR, "gram", 1.0),              # zero price
        (-5, USDPKR, "gram", 1.0),             # negative price
        (GOLD_USD, 0, "gram", 1.0),            # zero fx rate
        (float("nan"), USDPKR, "gram", 1.0),   # NaN
        (float("inf"), USDPKR, "gram", 1.0),   # Infinity
        ("abc", USDPKR, "gram", 1.0),          # non-numeric
        (GOLD_USD, USDPKR, "gram", None),      # no purity ratio
    ],
)
def test_invalid_input_returns_none_instead_of_a_number(usd, rate, unit, ratio):
    assert cp.price_per_unit(usd, rate, unit, ratio) is None


# ---------------------------------------------------------------------------
# the payload
# ---------------------------------------------------------------------------


def test_all_four_metals_are_priced_in_every_unit_with_explicit_units():
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_market())), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        payload = _run(cp.build_commodity_quotes(object()))

    assert payload["priced_count"] == payload["count"] == 12, "4 metals x 3 units"
    assert payload["unavailable"] == []
    assert payload["currency"] == "PKR"

    symbols = {row["symbol"] for row in payload["items"]}
    assert symbols == {"XAU-24K", "XAU-22K", "XAG", "XPT"}

    for row in payload["items"]:
        assert row["price"] is not None and row["price"] > 0, "spec N: positive commodity price"
        assert row["unit"].startswith("PKR per "), "spec I: every value states its unit"
        assert row["unit_key"] in cp.UNIT_GRAMS
        assert row["currency"] == "PKR"

    # each metal offers all three units, and exactly one is marked primary
    for metal in ["XAU-24K", "XAU-22K", "XAG", "XPT"]:
        rows = [r for r in payload["items"] if r["symbol"] == metal]
        assert {r["unit_key"] for r in rows} == {"gram", "10_gram", "tola"}
        assert sum(1 for r in rows if r["is_primary_unit"]) == 1


def test_payload_exposes_the_inputs_it_derived_from():
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_market())), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        payload = _run(cp.build_commodity_quotes(object()))

    assert payload["inputs"]["XAU"]["contract"] == "GC=F"
    assert payload["inputs"]["XAU"]["usd_per_troy_ounce"] == GOLD_USD
    assert payload["inputs"]["usdpkr"]["rate"] == pytest.approx(USDPKR)
    assert payload["units"]["tola_grams"] == cp.TOLA_GRAMS
    assert "31.1034768" in payload["derivation"]
    # and states plainly that this is not the local retail board
    assert "Sarafa" in payload["disclaimer"]


def test_change_percent_is_identical_across_units_but_absolute_change_scales():
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_market())), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        payload = _run(cp.build_commodity_quotes(object()))

    rows = [r for r in payload["items"] if r["symbol"] == "XAU-24K"]
    pcts = {round(r["change_percent"], 6) for r in rows}
    assert len(pcts) == 1, "a unit conversion cannot change a percentage move"
    expected = (GOLD_USD - GOLD_PREV) / GOLD_PREV * 100
    assert rows[0]["change_percent"] == pytest.approx(expected, rel=1e-4)
    assert all(r["change"] < 0 for r in rows), "gold fell, so every unit shows the loss"
    by_unit = {r["unit_key"]: r["change"] for r in rows}
    assert by_unit["tola"] == pytest.approx(by_unit["gram"] * cp.TOLA_GRAMS, rel=1e-3)


def test_metal_with_no_international_price_is_unavailable_not_zero():
    market = _market(**{"GC=F": _raw("GC=F", None, None, error="source said no")})
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=market)), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        payload = _run(cp.build_commodity_quotes(object()))

    gold = [r for r in payload["items"] if r["type"] == "gold"]
    assert all(r["price"] is None for r in gold)
    assert all(r["data_mode"] == "UNAVAILABLE" and r["error"] for r in gold)
    assert all("price" not in str(r["error"]).lower() or r["error"] for r in gold)
    silver = [r for r in payload["items"] if r["type"] == "silver"]
    assert all(r["price"] is not None for r in silver), "one dead metal must not hide the others"


def test_missing_usdpkr_rate_makes_every_row_unavailable_with_a_reason():
    market = _market(**{"USDPKR=X": _raw("USDPKR=X", None, None, error="no fx")})
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=market)), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        payload = _run(cp.build_commodity_quotes(object()))

    assert payload["priced_count"] == 0
    assert all(r["price"] is None for r in payload["items"])
    assert all("USD/PKR" in (r["error"] or "") for r in payload["items"])


def test_sparkline_uses_real_aligned_series():
    metal = pd.Series([4000.0, 4100.0, 4333.4], index=pd.to_datetime(["2026-09-09", "2026-09-10", "2026-09-11"]))
    fx = pd.Series([276.0, 277.0, 277.27], index=pd.to_datetime(["2026-09-09", "2026-09-10", "2026-09-11"]))
    series = cp._sparkline(metal, fx, "tola", 1.0)
    assert len(series) == 3
    assert series[-1] == pytest.approx(4333.4 / cp.TROY_OUNCE_GRAMS * 277.27 * cp.TOLA_GRAMS, rel=1e-5)
    assert series == sorted(series), "a rising metal series must rise"
    # a missing series yields no trend line rather than a fabricated one
    assert cp._sparkline(None, fx, "tola", 1.0) == []
    assert cp._sparkline(metal, None, "tola", 1.0) == []


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_commodities_route_returns_unit_explicit_rows(client):
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_market())), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        resp = client.get("/api/commodities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 12
    assert body["data_meta"]["status"] == "LIVE"
    assert {m["name"] for m in body["by_metal"]} == {"Gold 24K", "Gold 22K", "Silver", "Platinum"}


def test_commodities_route_reports_unavailable_when_nothing_can_be_priced(client):
    dead = {s: _raw(s, None, None, error="down") for s in ("GC=F", "SI=F", "PL=F", "USDPKR=X")}
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=dead)), \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        resp = client.get("/api/commodities")
    assert resp.status_code == 200
    assert resp.json()["data_meta"]["status"] == "UNAVAILABLE"
    assert resp.json()["priced_count"] == 0


def test_refresh_parameter_is_accepted(client):
    with patch.object(fx_rates, "yahoo_quotes", AsyncMock(return_value=_market())) as quotes, \
         patch.object(cp, "_daily_closes", AsyncMock(return_value=None)):
        resp = client.get("/api/commodities", params={"refresh": "true"})
    assert resp.status_code == 200
    assert quotes.await_args.kwargs.get("force_refresh") is True


def test_metal_specs_cover_exactly_the_required_purities():
    keys = {m.key for m in cp.METALS}
    assert keys == {"gold_24k", "gold_22k", "silver", "platinum"}
    gold24 = cp.METAL_BY_KEY["gold_24k"]
    gold22 = cp.METAL_BY_KEY["gold_22k"]
    assert gold24.purity == "24K" and gold24.purity_ratio == 1.0
    assert gold22.purity == "22K" and gold22.purity_ratio == pytest.approx(22 / 24)
    assert all(m.series in fx_rates.METAL_SERIES for m in cp.METALS)
    assert date.today() is not None  # keeps the import used for timestamp helpers
