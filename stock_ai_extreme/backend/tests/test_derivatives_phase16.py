from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.derivatives.providers.base import DerivativeDataStatus, DerivativeQuote, MarketDepth, MarketDepthLevel
from app.derivatives.services.microstructure import MarketMicrostructureService
from app.derivatives.services.paper_simulation import PaperSimulationService
from app.derivatives.schemas import HistoricalReplayRequest, PaperSimulationRequest


def test_microstructure_calculates_spread_and_depth_imbalance():
    quote = DerivativeQuote(
        instrument_id="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        last_price=100.0,
        bid=99.0,
        ask=101.0,
        mark_price=100.5,
        source="test-provider",
        status=DerivativeDataStatus.LIVE,
    )
    depth = MarketDepth(
        instrument_id="BTCUSDT",
        timestamp=datetime.now(timezone.utc),
        bids=[MarketDepthLevel(99.0, 4.0, 4.0), MarketDepthLevel(98.0, 2.0, 6.0)],
        asks=[MarketDepthLevel(101.0, 1.0, 1.0), MarketDepthLevel(102.0, 1.0, 2.0)],
        source="test-provider",
        status=DerivativeDataStatus.LIVE,
    )
    result = MarketMicrostructureService.calculate_microstructure(quote, depth)
    assert result.bid_ask_spread == 2.0
    assert result.mid_price == 100.0
    assert result.bid_depth == 6.0
    assert result.ask_depth == 2.0
    assert result.depth_imbalance == 0.5
    assert result.price_to_mark_diff == -0.5


def test_paper_simulation_is_non_monetary_and_calculates_directional_pnl():
    scenario = PaperSimulationService.create_simulation(
        PaperSimulationRequest(
            instrument_id="BTCUSDT",
            scenario_name="test long",
            direction="LONG",
            entry_price=100.0,
            quantity=2.0,
            leverage=3.0,
        )
    )
    result = PaperSimulationService.calculate_pnl(scenario, 110.0)
    assert result["gross_pnl"] == 20.0
    assert result["gross_pnl_percent"] == 10.0
    assert result["leveraged_pnl"] == 60.0
    assert "PAPER SIMULATION" in result["disclaimer"]


def test_historical_replay_uses_actual_supplied_candles():
    request = HistoricalReplayRequest(
        instrument_id="BTCUSDT",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 3, tzinfo=timezone.utc),
        entry_price=100.0,
        direction="SHORT",
        quantity=2.0,
    )
    result = __import__("asyncio").run(PaperSimulationService.historical_replay(request, [
        {"timestamp": "2025-01-01T00:00:00Z", "close": 100.0},
        {"timestamp": "2025-01-02T00:00:00Z", "close": 95.0},
        {"timestamp": "2025-01-03T00:00:00Z", "close": 90.0},
    ]))
    assert result.exit_reference == 90.0
    assert result.price_movement == 10.0
    assert result.hypothetical_result == 20.0
    assert result.data_points == 3


def test_paper_simulation_create_and_close_route_is_not_real_execution():
    from app.main import app
    client = TestClient(app)
    created = client.post("/api/derivatives/simulation", json={
        "instrument_id": "BTCUSDT",
        "scenario_name": "route test",
        "direction": "LONG",
        "entry_price": 100.0,
        "quantity": 1.0,
        "leverage": 1.0,
    })
    assert created.status_code == 200
    payload = created.json()
    assert payload["id"]
    closed = client.post(f"/api/derivatives/simulation/{payload['id']}/close?exit_price=105")
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["gross_pnl"] == 5.0
