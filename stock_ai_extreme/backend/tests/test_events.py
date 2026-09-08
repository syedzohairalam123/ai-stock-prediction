"""Tests for events.py — event studies and the geopolitical stress score."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.events import affected_assets, event_study, event_study_to_dict, geopolitical_score


def _frame_with_shocks(n_days: int = 260) -> pd.DataFrame:
    """Business-day frame where every 60th day is followed by a +5% jump —
    gives the event study an unambiguous, deterministic signal to find."""
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    closes = []
    for i in range(n_days):
        base = 100.0 + (i % 10)
        if i > 0 and i % 60 == 0:
            base = closes[-1] * 1.05
        closes.append(base)
    return pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * n_days,
    }, index=idx)


def test_event_study_measures_real_windows():
    df = _frame_with_shocks()
    # Event dates = the days just before each +5% shock (every ~60 bars).
    idx = df.index
    event_dates = [pd.Timestamp(idx[i - 1]).date().isoformat() for i in range(60, len(df), 60)]
    result = event_study(df, event_dates, "Synthetic shock")
    d = event_study_to_dict(result)
    assert d["sample_size"] >= 2
    assert d["avg_move_1d_pct"] == pytest.approx(5.0, abs=1.0)
    assert d["positive_1d_rate"] == pytest.approx(1.0)
    assert d["reliability"] in ("anecdotal", "suggestive", "meaningful_sample")


def test_event_study_raises_when_no_events_in_range():
    df = _frame_with_shocks()
    with pytest.raises(ValueError, match="No usable event dates"):
        event_study(df, ["1950-01-01"], "Impossible event")


def test_event_study_reliability_labels():
    df = _frame_with_shocks()
    idx = df.index
    one_date = [pd.Timestamp(idx[60]).date().isoformat()]
    result = event_study(df, one_date, "Single event")
    assert event_study_to_dict(result)["reliability"] == "anecdotal"


def test_geopolitical_score_empty_feed_is_unavailable_not_zero():
    score = geopolitical_score([])
    assert score["score"] is None
    assert score["level"] == "unavailable"


def test_geopolitical_score_high_on_conflict_headlines():
    headlines = [
        {"title": "Military strikes escalate amid war escalation"},
        {"title": "Sanctions trigger crisis in trade war"},
        {"title": "Nuclear talks collapse, troops mobilize"},
        {"title": "Markets tumble on war fears"},
    ]
    score = geopolitical_score(headlines)
    assert score["score"] is not None and score["score"] > 50
    assert score["level"] in ("high", "severe")
    assert score["top_keywords"]


def test_geopolitical_score_low_on_boring_headlines():
    headlines = [
        {"title": "Company reports quarterly earnings beat"},
        {"title": "New product launch planned for spring"},
        {"title": "Local marathon draws thousands"},
    ]
    score = geopolitical_score(headlines)
    assert score["score"] is not None and score["score"] < 25
    assert score["level"] == "low"


def test_affected_assets_map_changes_with_level():
    calm = affected_assets("low")
    stressed = affected_assets("high")
    assert "often_rises_on_stress" in stressed
    assert "often_rises_on_stress" not in calm
