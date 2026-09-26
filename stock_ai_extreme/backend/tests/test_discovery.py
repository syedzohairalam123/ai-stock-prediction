"""
Phase 19 — Advanced Market Discovery / New & Trending Engine tests.

Two layers, no network:

* the trend engine, taxonomy and feed logic are tested as pure functions
  (with a fixture universe injected into the service);
* the routes are exercised through the FastAPI app with that same fixture
  universe, so no provider call is ever made.

Honesty assertions matter as much as the happy path here: a missing signal
must stay missing, the NEW feed must refuse entities without a real
createdAt, and personalization must be disclosed rather than hidden.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.discovery import service, store
from app.discovery.config import discovery_settings
from app.discovery.collectors import _data_mode_for_status, _num
from app.discovery.taxonomy import (
    entity_category_and_tags,
    normalize_category,
    normalize_tag,
    tags_from_name,
    tags_from_sector_groups,
    taxonomy_from,
)
from app.discovery.trend_engine import TrendEngine


@pytest.fixture
def engine() -> TrendEngine:
    return TrendEngine()


# ---------------------------------------------------------------------------
# Trend engine — individual components (spec §4)
# ---------------------------------------------------------------------------
def test_recency_score_uses_half_life_and_real_timestamps(engine):
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    fresh = engine.calculate_recency_score("2026-01-10T00:00:00+00:00", now=now)
    half = engine.calculate_recency_score(now - timedelta(hours=72), now=now)
    stale = engine.calculate_recency_score(now - timedelta(days=60), now=now)
    assert fresh == pytest.approx(1.0)
    assert half == pytest.approx(0.5, abs=1e-3)
    assert stale < 0.01


def test_recency_score_is_none_without_a_timestamp(engine):
    assert engine.calculate_recency_score(None) is None
    assert engine.calculate_recency_score("") is None
    assert engine.calculate_recency_score("not-a-date") is None


def test_activity_score_saturates_per_kind_and_takes_magnitude(engine):
    # |−6%| over a 5% saturation clamps to 1.0 — a big *move* is fully active.
    assert engine.calculate_activity_score(-6.0, "change_pct") == pytest.approx(1.0)
    assert engine.calculate_activity_score(2.5, "change_pct") == pytest.approx(0.5)
    # Different kinds use their own saturations, never the change-pct one.
    assert engine.calculate_activity_score(125_000, "event_volume") == pytest.approx(0.5)
    assert engine.calculate_activity_score(1000, "event_participants") == pytest.approx(0.5)
    assert engine.calculate_activity_score(30, "topic_mentions") == pytest.approx(0.5)


def test_activity_score_refuses_non_measurements(engine):
    assert engine.calculate_activity_score(None, "change_pct") is None
    assert engine.calculate_activity_score(float("nan")) is None
    assert engine.calculate_activity_score("abc") is None


def test_velocity_score_uses_kind_specific_saturation(engine):
    assert engine.calculate_velocity_score(6.0, "topic") == pytest.approx(1.0)
    assert engine.calculate_velocity_score(2.5, "topic") == pytest.approx(2.5 / 6.0)
    assert engine.calculate_velocity_score(2.5, "activity") == pytest.approx(0.5)
    # A *falling* entity gets no velocity credit — the component measures rising
    # activity, and clamping keeps the score inside [0, 1].
    assert engine.calculate_velocity_score(-5.0, "activity") == pytest.approx(0.0)
    assert engine.calculate_velocity_score(None) is None


def test_interest_score_is_zero_for_zero_recorded_events(engine):
    # Zero is a real observation ("nothing recorded"), not "unavailable".
    assert engine.calculate_interest_score(0) == pytest.approx(0.0)
    assert engine.calculate_interest_score(25) == pytest.approx(1.0)
    assert engine.calculate_interest_score(12.5) == pytest.approx(0.5)
    assert engine.calculate_interest_score(None) is None


def test_news_score_measures_breadth_or_headline_mentions(engine):
    assert engine.calculate_news_score(source_count=3) == pytest.approx(0.5)
    assert engine.calculate_news_score(mentions_24h=5) == pytest.approx(0.5)
    # No honest link to the corpus → missing signal, never 0 pretending to be one.
    assert engine.calculate_news_score() is None


# ---------------------------------------------------------------------------
# Trend engine — aggregate (spec §4: weights visible, missing signals reported)
# ---------------------------------------------------------------------------
def test_trend_score_renormalizes_over_available_signals(engine):
    result = engine.calculate_trend_score(
        {"recency": 1.0, "activity": None, "velocity": None, "interest": 0.0, "news": 0.0}
    )
    # used weights = recency .20 + interest .15 + news .15 = .50 → 1.0*.20/.50
    assert result["score"] == pytest.approx(40.0, abs=0.01)
    assert set(result["weightsUsed"]) == {"recency", "interest", "news"}
    assert set(result["missing"]) == {"activity", "velocity"}
    # weights used must sum to the *renormalized* share, not to 1
    assert sum(result["weightsUsed"].values()) == pytest.approx(0.5)


def test_trend_score_with_no_signals_reports_none_not_zero(engine):
    result = engine.calculate_trend_score(
        {"recency": None, "activity": None, "velocity": None, "interest": None, "news": None}
    )
    assert result["score"] is None
    assert result["weightsUsed"] == {}
    assert len(result["missing"]) == 5


def test_trend_score_is_deterministic_and_bounded(engine):
    components = {"recency": 0.9, "activity": 0.7, "velocity": 0.4, "interest": 0.2, "news": 0.6}
    first = engine.calculate_trend_score(components)
    second = engine.calculate_trend_score(components)
    assert first == second
    assert 0.0 <= first["score"] <= 100.0


def test_popularity_score_is_interest_first(engine):
    result = engine.calculate_popularity_score({"interest": 1.0, "activity": 0.0})
    # .7*1 + .3*0 → 70
    assert result["score"] == pytest.approx(70.0, abs=0.01)
    assert "activity" in result["components"]
    assert engine.calculate_popularity_score({"interest": None, "activity": None})["score"] is None


def test_velocity_from_history_needs_two_points_in_the_window():
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    two = [
        (now - timedelta(hours=4), 10.0),
        (now, 30.0),
    ]
    assert TrendEngine.velocity_from_history(two, lookback_hours=6, now=now) == pytest.approx(5.0)
    assert TrendEngine.velocity_from_history(two[:1], lookback_hours=6, now=now) is None
    # A point outside the lookback window does not count as "recent motion".
    old = [(now - timedelta(hours=48), 10.0), (now - timedelta(hours=47), 30.0)]
    assert TrendEngine.velocity_from_history(old, lookback_hours=6, now=now) is None


def test_engine_describe_exposes_every_constant(engine):
    described = engine.describe()
    assert described["trendWeights"] == discovery_settings.trend_weights
    assert described["recencyHalfLifeHours"] == discovery_settings.recency_half_life_hours
    assert "saturations" in described and "note" in described


# ---------------------------------------------------------------------------
# Taxonomy (spec §5, §6, §13)
# ---------------------------------------------------------------------------
def test_category_aliases_map_onto_the_canonical_vocabulary():
    assert normalize_category("equity") == "Stocks"
    assert normalize_category("STOCKS") == "Stocks"
    assert normalize_category("Market Theme") == "Finance"
    assert normalize_category("nonsense") is None


def test_lexicon_tags_match_whole_words_only():
    # Regression: substring matching used to tag "Strait …" as AI because
    # "str**ai**t" contains "ai" — the same class of bug that mis-filed
    # forecast events as Tech.
    assert tags_from_name("Strait of Hormuz traffic returns to normal") == []
    assert "Technology" in tags_from_name("Systems Limited technology growth")
    assert "Gold" in tags_from_name("Gold holds near record highs")
    assert "Bitcoin" in tags_from_name("Bitcoin halving countdown")


def test_sector_group_tags_come_from_the_real_psx_groups():
    mapping = tags_from_sector_groups({"oil_gas": ["OGDC"], "banking": ["HBL"]})
    assert mapping == {"OGDC": "Oil Gas", "HBL": "Banking"}


def test_entity_category_and_tags_deduplicate_and_canonize():
    category, tags = entity_category_and_tags(
        category="equities", tags=["Technology", "technology"], name="Systems Limited"
    )
    assert category == "Stocks"
    assert tags.count("Technology") == 1
    # the category itself is never repeated as a tag
    assert "Stocks" not in tags


def test_taxonomy_counts_real_entities():
    model = taxonomy_from(
        [
            {"category": "Stocks", "tags": ["Technology", "PSX"]},
            {"category": "Stocks", "tags": ["Technology"]},
            {"category": "Crypto", "tags": ["Bitcoin"]},
        ]
    )
    by_name = {c["name"]: c["count"] for c in model["categories"]}
    assert by_name["Stocks"] == 2
    assert by_name["Crypto"] == 1
    assert by_name["Esports"] == 0  # empty categories stay visible, not hidden
    tag_by_name = {t["name"]: t["count"] for t in model["tags"]}
    assert tag_by_name["Technology"] == 2
    assert "Stocks" in model["tags"][0]["categories"] or model["tags"]


# ---------------------------------------------------------------------------
# Collector helpers
# ---------------------------------------------------------------------------
def test_data_mode_mapping_never_invents_live():
    assert _data_mode_for_status("LIVE") == "LIVE"
    assert _data_mode_for_status("RECENT") == "DELAYED"
    assert _data_mode_for_status("CACHED") == "DELAYED"
    assert _data_mode_for_status("STALE") == "DELAYED"
    assert _data_mode_for_status("UNAVAILABLE") == "UNAVAILABLE"
    assert _data_mode_for_status(None) == "DELAYED"


def test_num_helper_drops_nan_and_strings():
    assert _num("3.5") == 3.5
    assert _num(float("nan")) is None
    assert _num(None) is None
    assert _num("nope") is None


# ---------------------------------------------------------------------------
# Feed logic (spec §1, §2, §9) with a fixture universe — no network
# ---------------------------------------------------------------------------
def _entity(
    entity_id: str,
    *,
    name: str,
    entity_type: str = "stock",
    category: str = "Stocks",
    tags=(),
    created_at=None,
    updated_at=None,
    trend_score=None,
    popularity_score=None,
    activity_value=None,
    personal=None,
):
    return {
        "id": entity_id,
        "type": entity_type,
        "name": name,
        "symbol": entity_id.split(":", 1)[1] if ":" in entity_id else None,
        "category": category,
        "tags": list(tags),
        "createdAt": created_at,
        "updatedAt": updated_at,
        "activity": {"label": "Day change", "value": activity_value, "unit": "%"},
        "source": "test-source",
        "dataMode": "LIVE",
        "status": "ACTIVE",
        "route": None,
        "provenance": None,
        "trend": {"score": trend_score, "components": {}, "weightsUsed": {}, "missing": []},
        "popularity": {"score": popularity_score, "components": {}, "weightsUsed": {}, "missing": []},
        "scoreComponents": {},
        "signals": {},
        "interest": {"view": 0, "search": 0, "watchlist": 0, "total": 0},
        "personal": personal or {"watchlist": False, "recentlyViewed": False, "preferredCategory": False},
    }


@pytest.fixture
def universe():
    entities = [
        _entity(
            "stock:AAA", name="Alpha Tech", category="Stocks", tags=["Technology", "PSX"],
            updated_at="2026-01-10T00:00:00+00:00", trend_score=80.0, popularity_score=40.0,
            activity_value=1.5,
            personal={"watchlist": True, "recentlyViewed": False, "preferredCategory": False},
        ),
        _entity(
            "forecast:1", name="Will BTC close above 100k?", entity_type="forecast_event",
            category="Crypto", tags=["Bitcoin"], created_at="2026-01-09T00:00:00+00:00",
            updated_at="2026-01-09T12:00:00+00:00", trend_score=60.0, popularity_score=70.0,
            activity_value=250_000,
        ),
        _entity(
            "topic:xyz", name="Systems Limited technology earnings", entity_type="news_topic",
            category="Stocks", tags=["Technology", "Earnings"], created_at="2026-01-10T00:00:00+00:00",
            updated_at="2026-01-10T01:00:00+00:00", trend_score=45.0, popularity_score=10.0,
        ),
        _entity(
            "index:^GSPC", name="S&P 500", entity_type="index", category="Finance",
            tags=["Index"], updated_at="2026-01-10T02:00:00+00:00", trend_score=None,
            popularity_score=None,
        ),
    ]
    return {
        "entities": entities,
        "sources": [{"source": "test-source", "status": "OK", "count": len(entities)}],
        "generatedAt": "2026-01-10T03:00:00+00:00",
    }


@pytest.fixture
def patched_universe(monkeypatch, universe):
    async def _fake_get_universe(force: bool = False):
        return universe

    monkeypatch.setattr(service, "get_universe", _fake_get_universe)
    return universe


def _run_feed(**kwargs):
    import asyncio

    return asyncio.run(service.get_feed(**kwargs))


def test_trending_mode_sorts_by_trend_score_desc(patched_universe):
    feed = _run_feed(mode="trending")
    scores = [item["trend"]["score"] for item in feed["items"]]
    assert scores == sorted(scores, key=lambda s: -1 if s is None else s, reverse=True)
    assert feed["items"][0]["id"] == "stock:AAA"
    assert feed["total"] == 4
    assert feed["engine"]["trendWeights"] == discovery_settings.trend_weights
    assert feed["sources"][0]["source"] == "test-source"
    assert feed["notes"]  # honesty notes always ride along


def test_new_mode_requires_a_real_created_at(patched_universe):
    feed = _run_feed(mode="new")
    assert all(item["createdAt"] for item in feed["items"])
    assert feed["excludedNoCreatedAt"] == 2  # stock + index have no createdAt
    assert feed["total"] == 2
    # newest first
    dates = [item["createdAt"] for item in feed["items"]]
    assert dates == sorted(dates, reverse=True)


def test_popular_mode_uses_the_interest_first_score(patched_universe):
    feed = _run_feed(mode="popular")
    assert feed["items"][0]["id"] == "forecast:1"  # popularity 70 > 40 > 10
    order = [item["popularity"]["score"] for item in feed["items"]]
    assert order == sorted(order, key=lambda s: -1 if s is None else s, reverse=True)


def test_recent_mode_sorts_by_updated_at(patched_universe):
    feed = _run_feed(mode="recent")
    stamps = [item["updatedAt"] for item in feed["items"]]
    assert stamps[0] == "2026-01-10T02:00:00+00:00"
    assert stamps == sorted(stamps, reverse=True)


def test_tag_filter_reaches_every_type_that_carries_the_tag(patched_universe):
    feed = _run_feed(mode="trending", tag="technology")
    ids = {item["id"] for item in feed["items"]}
    # stock + news topic, and NOT the BTC event (different tag entirely)
    assert ids == {"stock:AAA", "topic:xyz"}


def test_category_and_type_filters(patched_universe):
    by_category = _run_feed(mode="trending", category="Crypto")
    assert [item["id"] for item in by_category["items"]] == ["forecast:1"]
    by_type = _run_feed(mode="trending", entity_type="index")
    assert [item["id"] for item in by_type["items"]] == ["index:^GSPC"]


def test_since_filter_only_keeps_entities_created_in_window(patched_universe):
    feed = _run_feed(mode="new", since="2026-01-10")
    assert [item["id"] for item in feed["items"]] == ["topic:xyz"]


def test_q_filter_matches_name_symbol_or_tag(patched_universe):
    feed = _run_feed(mode="trending", q="s&p")
    assert [item["id"] for item in feed["items"]] == ["index:^GSPC"]
    tagged = _run_feed(mode="trending", q="bitcoin")
    assert "forecast:1" in {item["id"] for item in tagged["items"]}


def test_personalization_boosts_and_discloses(patched_universe):
    plain = _run_feed(mode="trending", personalize=False)
    personal = _run_feed(mode="trending", personalize=True)

    plain_rank = next(i["rankScore"] for i in plain["items"] if i["id"] == "stock:AAA")
    personal_item = next(i for i in personal["items"] if i["id"] == "stock:AAA")
    # raw score unchanged, rank boosted, boost flagged on the item itself
    assert personal_item["trend"]["score"] == 80.0
    assert personal_item["rankScore"] > plain_rank
    assert personal_item["personalBoostApplied"] is True
    assert personal_item["personal"]["watchlist"] is True
    assert personal["personalization"]["enabled"] is True
    assert "watchlist" in personal["personalization"]["signals"]


def test_preferred_categories_are_only_explicit_selections(patched_universe):
    feed = _run_feed(mode="trending", personalize=True, prefer=["Crypto"])
    crypto_item = next(i for i in feed["items"] if i["id"] == "forecast:1")
    assert crypto_item["personal"]["preferredCategory"] is True
    assert crypto_item["personal"]["watchlist"] is False


def test_pagination_is_stable(patched_universe):
    first = _run_feed(mode="trending", limit=2, offset=0)
    second = _run_feed(mode="trending", limit=2, offset=2)
    assert first["hasMore"] is True
    assert len(first["items"]) == 2 and len(second["items"]) == 2
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
    assert first["total"] == second["total"] == 4


def test_unknown_mode_falls_back_to_trending(patched_universe):
    feed = _run_feed(mode="sideways")
    assert feed["mode"] == "trending"


def test_observation_sampling_is_throttled(universe):
    import asyncio

    from app.db import init_db

    init_db()  # create trend_observations/discovery_events before any write
    items = universe["entities"][:2]

    # An earlier route test in this session may already have sampled these
    # fixture entities (the trending feed samples on read). Start clean so the
    # assertion measures this test's writes, not someone else's.
    from app.db import session_scope
    from app.models import TrendObservation

    with session_scope() as db:
        db.query(TrendObservation).filter(
            TrendObservation.entity_id.in_(["stock:AAA", "forecast:1"])
        ).delete(synchronize_session=False)

    written_first = asyncio.run(service.sample_observations(items))
    assert written_first == 2
    # second pass inside the sample interval writes nothing new
    written_second = asyncio.run(service.sample_observations(items))
    assert written_second == 0

    stored = store.observation_history("stock:AAA", hours=1)
    assert len(stored) == 1
    assert stored[0]["score"] == 80.0
    assert stored[0]["activity"] == 1.5


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app
    from fastapi.testclient import TestClient

    init_db()
    return TestClient(app)


def test_engine_endpoint_exposes_the_scoring_contract(client):
    body = client.get("/api/discover/engine").json()
    assert body["trendWeights"] == discovery_settings.trend_weights
    assert body["feedModes"] == ["trending", "new", "popular", "recent"]
    assert body["personalization"]["signals"] == ["watchlist", "recently_viewed", "preferred_categories"]


def test_discover_rejects_unknown_mode_and_type(client):
    assert client.get("/api/discover?mode=nope").status_code == 422
    assert client.get("/api/discover?type=spaceship").status_code == 422


def test_discover_feed_route_serves_the_fixture_universe(client, patched_universe):
    response = client.get("/api/discover?mode=trending&limit=3")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "trending"
    assert len(body["items"]) == 3
    assert body["engine"]["note"]


def test_events_route_records_real_interest(client):
    response = client.post("/api/discover/events", json={"entityId": "stock:AAA", "kind": "view"})
    assert response.status_code == 200
    assert response.json()["recorded"] is True

    # the recorded event is a real row the interest scorer can count
    counts = store.interest_counts(["stock:AAA"])
    assert counts["stock:AAA"]["view"] >= 1

    rejected = client.post("/api/discover/events", json={"entityId": "x", "kind": "hacked"})
    assert rejected.status_code == 422


def test_trend_history_route_reports_empty_history_honestly(client, patched_universe):
    # `index:^GSPC` is deliberately an entity no other test sampled, so this
    # asserts the honest "no observations yet" path rather than a side effect.
    response = client.get("/api/discover/trends/index:^GSPC?hours=24")
    assert response.status_code == 200
    body = response.json()
    assert body["entityId"] == "index:^GSPC"
    assert body["entity"]["id"] == "index:^GSPC"
    # fixture universe has no stored observations → say so, don't draw a line
    assert body["analytics"]["available"] is False
    assert body["analytics"]["count"] == 0


def test_discovery_tables_exist_after_init_db():
    from sqlalchemy import inspect

    from app.db import engine as db_engine

    tables = inspect(db_engine).get_table_names()
    assert "trend_observations" in tables
    assert "discovery_events" in tables
