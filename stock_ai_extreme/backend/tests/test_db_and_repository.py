import pytest
from sqlalchemy import delete

from app.db import init_db, session_scope
from app.models import PredictionRecord, WatchlistItem
from app import repository as repo


@pytest.fixture(autouse=True)
def clean_tables():
    init_db()
    with session_scope() as db:
        db.execute(delete(PredictionRecord))
        db.execute(delete(WatchlistItem))
    yield


def test_save_and_retrieve_prediction_history():
    repo.save_prediction(
        ticker="aapl", model="rf", horizon=3, data_source="yfinance", data_status="LIVE",
        predictions=[{"date": "2024-01-02", "price": 101.0, "lower": 99.0, "upper": 103.0}],
        metrics={"mae": 1.2, "rmse": 1.8},
    )
    history = repo.get_prediction_history("AAPL")
    assert len(history) == 1
    assert history[0]["ticker"] == "AAPL"
    assert history[0]["model"] == "rf"
    assert history[0]["metrics"]["rmse"] == 1.8
    assert history[0]["actual_price"] is None  # not resolved yet


def test_prediction_history_is_ordered_most_recent_first():
    for i in range(3):
        repo.save_prediction("MSFT", "ridge", 2, "yfinance", "LIVE", [{"date": f"2024-01-0{i+1}", "price": 100 + i}], {"mae": 1, "rmse": 1})
    history = repo.get_prediction_history("MSFT")
    assert len(history) == 3
    # most recently inserted row should come first
    assert history[0]["predictions"][0]["price"] == 102


def test_watchlist_add_list_remove_roundtrip():
    added = repo.add_to_watchlist("tsla", note="watching for earnings")
    assert added["ticker"] == "TSLA"
    items = repo.list_watchlist()
    assert any(i["ticker"] == "TSLA" for i in items)
    removed = repo.remove_from_watchlist("TSLA")
    assert removed is True
    assert not any(i["ticker"] == "TSLA" for i in repo.list_watchlist())


def test_watchlist_rejects_duplicate_ticker():
    repo.add_to_watchlist("NVDA")
    with pytest.raises(ValueError, match="already on the watchlist"):
        repo.add_to_watchlist("nvda")


def test_removing_nonexistent_ticker_returns_false():
    assert repo.remove_from_watchlist("NOPE") is False
