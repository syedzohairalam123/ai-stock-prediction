from datetime import datetime, timezone

from app.forecast_markets import normalize_market


def test_normalizes_live_public_market_payload():
    market = normalize_market(
        {
            "id": "market-123",
            "question": "Will the inflation reading decline this month?",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.73", "0.27"]',
            "slug": "inflation-reading",
            "updatedAt": "2026-09-19T10:00:00Z",
            "endDate": "2026-09-30T00:00:00Z",
        },
        datetime(2026, 9, 19, 10, 1, tzinfo=timezone.utc),
    )

    assert market is not None
    assert market["dataMode"] == "LIVE"
    assert market["yesProbability"] == 73.0
    assert market["noProbability"] == 27.0
    assert market["category"] == "Economy"
    assert market["sources"][0]["url"] == "https://polymarket.com/market/inflation-reading"


def test_rejects_non_binary_or_invalid_probability_payload():
    assert normalize_market({"id": "missing-outcomes", "question": "Incomplete"}) is None
    assert normalize_market(
        {
            "id": "invalid-probability",
            "question": "Invalid",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["1.5", "-0.5"],
        }
    ) is None