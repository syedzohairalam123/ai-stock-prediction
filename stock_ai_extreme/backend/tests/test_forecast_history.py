"""Phase 14.1 — real probability history engine."""
import asyncio
from datetime import datetime

import pytest

from app import forecast_history as fh


def test_build_points_marks_up_and_down_as_complementary():
    rows = [{"t": 1_700_000_000 + i * 3600, "p": 0.40 + i * 0.01} for i in range(10)]
    points = fh.build_points(rows, max_points=5)

    assert len(points) == 5
    assert points[0]["yesProbability"] == pytest.approx(40.0)
    assert points[-1]["yesProbability"] == pytest.approx(49.0)
    for point in points:
        assert point["yesProbability"] + point["noProbability"] == pytest.approx(100.0)
        # Every timestamp is a real, parseable ISO instant.
        datetime.fromisoformat(point["timestamp"])


def test_build_points_empty_input_is_empty_not_fabricated():
    assert fh.build_points([]) == []


def test_clob_token_ids_parses_json_string_and_arrays():
    assert fh.clob_token_ids({"clobTokenIds": '["111", "222"]'}) == ["111", "222"]
    assert fh.clob_token_ids({"clobTokenIds": ["111", "222"]}) == ["111", "222"]
    assert fh.clob_token_ids({"clobTokenIds": "not-json"}) == []
    assert fh.yes_token_id({"clobTokenIds": ["yes-token", "no-token"]}) == "yes-token"
    assert fh.yes_token_id({"clobTokenIds": []}) is None


def test_range_spec_clamps_fidelity_and_maps_intervals():
    interval, fidelity = fh._range_spec("1D", None)
    assert interval == "1d"
    assert 1 <= fidelity <= 30

    interval, _ = fh._range_spec("7D", None)
    assert interval == "1w"

    interval, fidelity = fh._range_spec("MAX", None)
    assert interval == "max"

    # An explicit override always wins (clamped).
    interval, fidelity = fh._range_spec("anything", 15)
    assert interval == "max"
    assert fidelity == 15


def test_fetch_market_history_uses_the_yes_token(monkeypatch):
    fh.clear_cache()
    seen: dict[str, str] = {}

    async def fake_fetch_rows(token_id, interval, fidelity):
        seen["token"] = token_id
        seen["interval"] = interval
        return [{"t": 1_700_000_000 + i * 3600, "p": 0.5} for i in range(4)]

    monkeypatch.setattr(fh, "_fetch_rows", fake_fetch_rows)
    market = {"id": "m1", "clobTokenIds": ["yes-token", "no-token"], "sources": [{"url": "https://x"}]}

    payload = asyncio.run(fh.fetch_market_history(market, range_key="7D"))

    assert payload is not None
    assert seen["token"] == "yes-token"
    assert seen["interval"] == "1w"
    assert payload["tokenId"] == "yes-token"
    assert payload["updateCount"] == 4
    assert payload["dataMode"] == "LIVE"
    assert payload["source"]["url"].startswith("https://")


def test_fetch_market_history_without_token_is_none():
    fh.clear_cache()
    assert asyncio.run(fh.fetch_market_history({"id": "m", "clobTokenIds": []})) is None


def test_fetch_market_history_source_failure_is_none(monkeypatch):
    fh.clear_cache()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("source down")

    monkeypatch.setattr(fh, "_fetch_rows", boom)
    market = {"id": "m", "clobTokenIds": ["t"]}
    assert asyncio.run(fh.fetch_market_history(market)) is None


def test_fetch_market_history_empty_history_is_unavailable_not_fabricated(monkeypatch):
    fh.clear_cache()

    async def empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(fh, "_fetch_rows", empty)
    market = {"id": "m", "clobTokenIds": ["t"]}
    payload = asyncio.run(fh.fetch_market_history(market))
    assert payload is not None
    assert payload["points"] == []
    assert payload["dataMode"] == "UNAVAILABLE"
