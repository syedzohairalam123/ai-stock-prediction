import pytest
from sqlalchemy import delete

from app.db import init_db, session_scope
from app.models import Alert, PredictionRecord, WatchlistItem
from app import repository as repo


@pytest.fixture(autouse=True)
def clean_tables():
    init_db()
    with session_scope() as db:
        db.execute(delete(PredictionRecord))
        db.execute(delete(WatchlistItem))
        db.execute(delete(Alert))
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


def test_create_and_list_alerts():
    repo.create_alert("aapl", "price_above", 250.0)
    alerts = repo.list_alerts(ticker="AAPL")
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "price_above"
    assert alerts[0]["active"] is True
    assert alerts[0]["triggered_at"] is None


def test_list_alerts_active_only_filter():
    a = repo.create_alert("MSFT", "price_below", 300.0)
    repo.mark_alert_triggered(a["id"], value=295.0)
    assert repo.list_alerts(ticker="MSFT", active_only=True) == []
    all_alerts = repo.list_alerts(ticker="MSFT")
    assert len(all_alerts) == 1
    assert all_alerts[0]["active"] is False
    assert all_alerts[0]["triggered_value"] == 295.0


def test_delete_alert():
    a = repo.create_alert("NVDA", "pct_change", 5.0)
    assert repo.delete_alert(a["id"]) is True
    assert repo.list_alerts(ticker="NVDA") == []
    assert repo.delete_alert(a["id"]) is False  # already gone


def test_unresolved_predictions_and_resolution_roundtrip():
    pid = repo.save_prediction("AAPL", "rf", 3, "yfinance", "LIVE",
                                [{"date": "2024-01-02", "price": 101.0}], {"mae": 1, "rmse": 1})
    unresolved = repo.get_unresolved_predictions()
    assert any(r["id"] == pid for r in unresolved)

    repo.set_actual_price(pid, 103.25)
    still_unresolved = repo.get_unresolved_predictions()
    assert not any(r["id"] == pid for r in still_unresolved)

    resolved = repo.get_resolved_predictions(ticker="AAPL")
    match = [r for r in resolved if r["id"] == pid][0]
    assert match["actual_price"] == 103.25
    assert match["predicted_price"] == 101.0
