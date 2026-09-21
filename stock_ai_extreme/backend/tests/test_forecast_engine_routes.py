"""Route tests for the Phase 14/15 forecast engines and Phase 11-13 routers.

Network access is blocked at the seams (gamma/CLOB fetch, resolution list) so
these tests are deterministic; the combination endpoint is exercised with
inline histories, which never touch the network at all.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    init_db()
    return TestClient(app)


def _market():
    return {
        "id": "m1",
        "title": "Will the inflation reading decline this month?",
        "clobTokenIds": ["yes-token", "no-token"],
        "yesProbability": 55.0,
        "noProbability": 45.0,
        "sources": [{"url": "https://polymarket.com/market/x"}],
    }


def _raw_rows(count=40, start=1_700_000_000):
    return [{"t": start + i * 86_400, "p": 0.5 + 0.001 * i} for i in range(count)]


def _history_points(count=40):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(count):
        probability = 50.0 + 0.3 * i
        rows.append(
            {
                "timestamp": (start + timedelta(days=i)).isoformat(),
                "yesProbability": probability,
                "noProbability": 100.0 - probability,
            }
        )
    return rows


def test_history_route_returns_real_points(client, monkeypatch):
    from app import forecast_history as fh

    fh.clear_cache()

    async def fake_rows(token_id, interval, fidelity):
        return _raw_rows()

    async def fake_market(market_id):
        return _market()

    monkeypatch.setattr(fh, "_fetch_rows", fake_rows)
    monkeypatch.setattr("app.forecast_routes._market_or_list", fake_market)

    resp = client.get("/api/forecast/markets/m1/history", params={"range": "7D"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["marketId"] == "m1"
    assert body["updateCount"] == 40
    assert body["interval"] == "1w"
    assert body["points"][0]["yesProbability"] == pytest.approx(50.0)
    assert body["dataMode"] == "LIVE"


def test_history_route_validates_range(client):
    resp = client.get("/api/forecast/markets/m1/history", params={"range": "5Y"})
    assert resp.status_code == 400


def test_history_route_404_for_unknown_market(client, monkeypatch):
    from app import forecast_history as fh

    fh.clear_cache()

    async def no_market(market_id):
        return None

    monkeypatch.setattr("app.forecast_routes._market_or_list", no_market)
    resp = client.get("/api/forecast/markets/nope/history")
    assert resp.status_code == 404


def test_simulation_route_returns_simulated_payload(client, monkeypatch):
    from app import forecast_history as fh

    fh.clear_cache()

    async def fake_rows(token_id, interval, fidelity):
        return _raw_rows(60)

    async def fake_market(market_id):
        return _market()

    monkeypatch.setattr(fh, "_fetch_rows", fake_rows)
    monkeypatch.setattr("app.forecast_routes._market_or_list", fake_market)

    resp = client.post(
        "/api/forecast/markets/m1/simulate",
        json={"horizonDays": 30, "paths": 1000, "model": "auto"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dataMode"] == "SIMULATED"
    assert body["paths"] == 1000
    assert "terminal" in body and 0.0 <= body["terminal"]["pYes"] <= 100.0
    assert len(body["path"]["median"]) == body["steps"]


def test_simulation_route_422_without_enough_history(client, monkeypatch):
    from app import forecast_history as fh

    fh.clear_cache()

    async def two_rows(token_id, interval, fidelity):
        return _raw_rows(2)

    async def fake_market(market_id):
        return _market()

    monkeypatch.setattr(fh, "_fetch_rows", two_rows)
    monkeypatch.setattr("app.forecast_routes._market_or_list", fake_market)

    resp = client.post("/api/forecast/markets/m1/simulate", json={"horizonDays": 10})
    assert resp.status_code == 422


def test_combine_route_returns_independence_and_adjusted(client):
    events = [
        {"marketId": "a", "label": "A", "outcome": "YES", "probability": 60.0, "history": _history_points()},
        {"marketId": "b", "label": "B", "outcome": "YES", "probability": 50.0, "history": _history_points()},
    ]
    resp = client.post("/api/forecast/combine", json={"events": events, "draws": 2000, "seed": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 2
    assert body["independenceProbability"] == pytest.approx(30.0, abs=0.01)
    assert "correlationAdjustedProbability" in body
    assert "correlation" in body
    assert len(body["sensitivity"]["tornado"]) == 2


def test_combine_route_rejects_single_event(client):
    resp = client.post(
        "/api/forecast/combine",
        json={"events": [{"marketId": "a", "outcome": "YES", "probability": 60.0}]},
    )
    assert resp.status_code == 400


def test_correlate_route_requires_two_events(client):
    resp = client.post("/api/forecast/correlate", json={"events": [{"marketId": "a", "probability": 60.0}]})
    assert resp.status_code == 422


def test_combination_persistence_roundtrip(client):
    payload = {
        "id": "combo-test-1",
        "name": "Test combination",
        "selections": [{"marketId": "a", "outcome": "YES", "probability": 60.0}],
        "combinedProbability": 60.0,
        "correlationAdjustedProbability": 58.0,
        "correlation": {"applied": True, "matrix": [[1.0]]},
    }
    created = client.post("/api/forecast/combinations", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["id"] == "combo-test-1"

    listing = client.get("/api/forecast/combinations").json()
    assert any(item["id"] == "combo-test-1" for item in listing["combinations"])

    snapshot = client.post(
        "/api/forecast/combinations/combo-test-1/snapshot",
        json={"combinedProbability": 59.0, "correlationAdjustedProbability": 57.0},
    )
    assert snapshot.status_code == 200

    detail = client.get("/api/forecast/combinations/combo-test-1").json()
    assert len(detail["snapshots"]) >= 1

    deleted = client.delete("/api/forecast/combinations/combo-test-1")
    assert deleted.status_code == 200
    assert client.get("/api/forecast/combinations/combo-test-1").status_code == 404


def test_snapshot_route_404_for_unknown_combination(client):
    resp = client.post(
        "/api/forecast/combinations/does-not-exist/snapshot",
        json={"combinedProbability": 10.0},
    )
    assert resp.status_code == 404


def test_resolutions_route_lists_settled_markets(client, monkeypatch):
    async def fake_resolutions(*, force=False, resolved_only=True):
        return [
            {
                "marketId": "m1",
                "conditionId": "c1",
                "title": "Settled market",
                "status": "RESOLVED",
                "resolution": "YES",
                "resolutionDate": "2026-08-01T00:00:00Z",
                "closeTime": "2026-08-01T00:00:00Z",
                "source": {"name": "Polymarket public market data", "url": "https://x", "verifiedAt": None},
            }
        ]

    monkeypatch.setattr("app.forecast_routes.get_resolutions", fake_resolutions)
    resp = client.get("/api/forecast/resolutions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["resolutions"][0]["resolution"] == "YES"


def test_original_forecast_category_route_still_works(client):
    resp = client.get("/api/forecast/categories")
    assert resp.status_code == 200
    assert "Politics" in resp.json()


def test_search_route_finds_symbols(client):
    resp = client.post("/api/search", json={"query": "OGDC", "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    assert any(result["symbol"] == "OGDC" for result in body["results"])


def test_workspace_layouts_roundtrip(client):
    layouts = {"chart-chat": {"version": 1, "widgets": []}}
    saved = client.put("/api/workspace/layouts", json=layouts)
    assert saved.status_code == 200
    fetched = client.get("/api/workspace/layouts")
    assert fetched.status_code == 200
    assert fetched.json()["chart-chat"]["version"] == 1


def test_workspace_saved_roundtrip(client):
    items = [{"id": "ws-1", "name": "My workspace", "layout": {"version": 1}}]
    assert client.put("/api/workspace/saved", json=items).status_code == 200
    fetched = client.get("/api/workspace/saved")
    assert fetched.status_code == 200
    assert fetched.json()[0]["id"] == "ws-1"


def test_chart_workspace_roundtrip(client):
    payload = {"charts": [{"id": "chart-a", "symbol": "OGDC"}]}
    assert client.put("/api/chart-workspace", json=payload).status_code == 200
    fetched = client.get("/api/chart-workspace")
    assert fetched.status_code == 200
    assert fetched.json()["charts"][0]["symbol"] == "OGDC"
