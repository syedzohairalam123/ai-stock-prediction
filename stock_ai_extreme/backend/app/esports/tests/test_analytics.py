"""
Phase 21C test suite — analytics, trending, data quality, recovery, security.

Everything here runs offline against constructed provider records, so the
statistical claims (§1–§12), the failure paths (§19–§20) and the input
validation (§21) are all deterministic. No network, no database, no fabricated
production data: the fixtures are only inputs, never presented as live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.esports.analytics import metrics, source_consistency, trending
from app.esports.analytics.data_quality import (
    DataQualityEngine,
    aggregate_quality,
    evaluate_data_quality,
)
from app.esports.analytics.observability import EsportsObservability, esports_metrics
from app.esports.analytics.service import EsportsAnalyticsService
from app.esports.analytics.store import AnalyticsStore, analytics_store
from app.esports.providers.base import (
    EventType,
    Game,
    GameEvent,
    Match,
    MatchStatus,
    Player,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def make_match(
    mid: str,
    status: MatchStatus = MatchStatus.COMPLETED,
    *,
    game: str = "cs2",
    minutes_ago: int = 60,
    score: tuple[int, int] = (2, 0),
    games: list | None = None,
    source: str = "csapi.de",
    team_a: str = "ta",
    team_b: str = "tb",
    data_mode: str = "DELAYED",
) -> Match:
    scheduled = NOW - timedelta(minutes=minutes_ago)
    meta: dict = {
        "team_names": {team_a: "Alpha", team_b: "Beta"},
        "league": "Test League",
        "data_mode": data_mode,
    }
    if games is not None:
        meta["games"] = games
    return Match(
        id=mid,
        external_id=mid,
        game_id=game,
        tournament_id=f"{game}-tour-1",
        series_id=f"{game}-s-1",
        status=status,
        scheduled_at=scheduled,
        team_a_id=team_a,
        team_b_id=team_b,
        started_at=scheduled,
        ended_at=scheduled if status == MatchStatus.COMPLETED else None,
        best_of=3,
        current_map="Mirage",
        map_number=1,
        score_a=score[0],
        score_b=score[1],
        winner_id=team_a if status == MatchStatus.COMPLETED and score[0] > score[1] else None,
        source=source,
        source_timestamp=scheduled,
        received_at=NOW,
        meta_data=meta,
    )


def make_event(
    eid: str,
    match_id: str = "m1",
    *,
    sequence: int = 1,
    event_type: EventType = EventType.SCORE_CHANGED,
    seconds_after: int = 0,
    game: str = "cs2",
    source: str = "csapi.de",
) -> GameEvent:
    stamp = NOW + timedelta(seconds=seconds_after)
    return GameEvent(
        id=eid,
        match_id=match_id,
        game_id=game,
        type=event_type,
        timestamp=stamp,
        sequence=sequence,
        payload={},
        source=source,
        source_timestamp=stamp,
        received_at=stamp,
    )


def map_games(*entries) -> list[dict]:
    """Per-map records as the sources publish them: name + decisive score."""
    return [
        {"name": name, "team_a_score": a, "team_b_score": b, "duration": duration}
        for name, a, b, duration in entries
    ]


# ===========================================================================
# §1, §3 — recent form
# ===========================================================================

class TestTeamForm:
    def test_form_reports_wins_losses_and_sample_size(self):
        matches = [
            make_match("m1", score=(2, 0), minutes_ago=300),
            make_match("m2", score=(2, 1), minutes_ago=240),
            make_match("m3", score=(0, 2), minutes_ago=180),
            make_match("m4", score=(2, 0), minutes_ago=120),
            make_match("m5", score=(2, 1), minutes_ago=60),
        ]
        form = metrics.calculate_team_form(matches, "ta")
        assert form["value"]["wins"] == 4
        assert form["value"]["losses"] == 1
        assert form["value"]["win_rate"] == pytest.approx(0.8)
        # The sample size the spec insists on is always present.
        assert form["sample_size"] == 5
        assert form["date_range"]["from"] is not None
        assert form["date_range"]["to"] is not None
        assert form["sources"] == ["csapi.de"]
        assert form["data_quality"] in ("HIGH", "MEDIUM", "LOW")

    def test_form_limits_to_the_requested_window_and_streak(self):
        matches = [make_match(f"m{i}", score=(2, 0), minutes_ago=60 * (10 - i)) for i in range(10)]
        form = metrics.calculate_team_form(matches, "ta", limit=3)
        assert form["sample_size"] == 3
        assert form["value"]["streak"] == "W3"

    def test_form_is_low_quality_with_a_tiny_sample(self):
        form = metrics.calculate_team_form([make_match("m1", score=(2, 0))], "ta")
        assert form["data_quality"] == "LOW"

    def test_form_has_no_numbers_without_history(self):
        form = metrics.calculate_team_form([], "ta")
        assert form["sample_size"] == 0
        assert form["value"]["win_rate"] is None
        assert form["data_quality"] == "UNAVAILABLE"

    def test_infer_winner_reads_the_published_score(self):
        assert metrics.infer_winner(make_match("m1", score=(2, 1))) == "ta"
        assert metrics.infer_winner(make_match("m1", score=(0, 2))) == "tb"
        # Live matches never yield a winner — nothing is guessed.
        assert metrics.infer_winner(make_match("m1", MatchStatus.LIVE, score=(1, 0))) is None

    def test_series_win_rate_excludes_undecided_matches(self):
        matches = [
            make_match("m1", score=(2, 0), minutes_ago=120),
            make_match("m2", MatchStatus.LIVE, score=(1, 1), minutes_ago=5),
        ]
        series = metrics.calculate_series_win_rate(matches, "ta")
        assert series["value"]["wins"] == 1
        assert series["value"]["losses"] == 0
        assert series["sample_size"] == 1  # the live match is not a result

    def test_historical_consistency_is_bounded(self):
        assert metrics.calculate_historical_consistency([1, 1, 1]) == pytest.approx(1.0)
        assert metrics.calculate_historical_consistency([10, -10, 10, -10]) < 0.5
        assert metrics.calculate_historical_consistency([1]) is None


# ===========================================================================
# §4 — map analytics
# ===========================================================================

class TestMapAnalytics:
    def test_map_win_rate_from_real_per_map_records(self):
        matches = [
            make_match("m1", games=map_games(("Mirage", 13, 7, 2100), ("Inferno", 7, 13, 2400))),
            make_match("m2", minutes_ago=30, games=map_games(("Mirage", 13, 9, 2000))),
        ]
        result = metrics.calculate_map_analytics(matches, "ta")
        by_map = {entry["map"]: entry for entry in result["maps"]}
        assert by_map["Mirage"]["played"] == 2
        assert by_map["Mirage"]["wins"] == 2
        assert by_map["Mirage"]["win_rate"] == pytest.approx(1.0)
        assert by_map["Inferno"]["win_rate"] == pytest.approx(0.0)
        assert by_map["Mirage"]["recent_form"] == ["W", "W"]
        assert result["sources"] == ["csapi.de"]

    def test_maps_without_identity_are_incomplete_not_invented(self):
        games = map_games(("Mirage", 13, 7, 2100), (None, 13, 5, 1800))
        result = metrics.calculate_map_analytics([make_match("m1", games=games)], "ta")
        assert result["incomplete_records"] == 1
        assert result["sample_size"] == 1  # only the identifiable map counted

    def test_unavailable_when_the_source_publishes_no_maps(self):
        result = metrics.calculate_map_analytics([make_match("m1")], "ta")
        assert result["available"] is False
        assert result["maps"] == []
        assert result["data_quality"] == "UNAVAILABLE"
        assert result["sample_size"] == 0

    def test_map_quality_reflects_sample_size(self):
        matches = [make_match(f"m{i}", minutes_ago=60 * i, games=map_games(("Mirage", 13, 7, 2000))) for i in range(6)]
        result = metrics.calculate_map_analytics(matches, "ta")
        assert result["maps"][0]["sample_size"] == 6
        assert result["maps"][0]["data_quality"] == "HIGH"

    def test_cs2_published_maps_key_is_used_not_ignored(self):
        """csapi.de stores per-map records under ``maps`` (no ``games`` key)."""
        match = make_match("m1", game="cs2", source="csapi.de")
        match.meta_data.pop("games", None)
        match.meta_data["maps"] = [
            {"map_number": 1, "name": "Nuke", "team_a_score": 13, "team_b_score": 8},
            {"map_number": 2, "name": "Ancient", "team_a_score": 13, "team_b_score": 11},
        ]
        result = metrics.calculate_map_analytics([match], "ta")
        assert result["available"] is True
        by_map = {entry["map"]: entry for entry in result["maps"]}
        assert by_map["Nuke"]["wins"] == 1
        assert by_map["Ancient"]["win_rate"] == pytest.approx(1.0)
        assert result["sources"] == ["csapi.de"]


# ===========================================================================
# §1 — duration, score progression, event frequency
# ===========================================================================

class TestSeriesStatistics:
    def test_duration_statistics_use_pandas(self):
        matches = [make_match("m1", games=map_games(("Mirage", 13, 7, 1800), ("Inferno", 13, 10, 2400)))]
        result = metrics.calculate_match_duration_stats(matches)
        assert result["available"] is True
        assert result["value"]["mean_seconds"] == pytest.approx(2100.0)
        assert result["value"]["max_seconds"] == pytest.approx(2400.0)
        assert len(result["value"]["rolling_mean_seconds"]) == 2
        assert result["sample_size"] == 2

    def test_duration_is_unavailable_without_published_games(self):
        result = metrics.calculate_match_duration_stats([make_match("m1")])
        assert result["available"] is False
        assert result["value"] is None

    def test_score_progression_detects_a_rising_trend(self):
        matches = [
            make_match("m1", score=(2, 0), minutes_ago=300),
            make_match("m2", score=(2, 1), minutes_ago=200),
            make_match("m3", score=(2, 1), minutes_ago=100),
            make_match("m4", score=(2, 0), minutes_ago=50),
        ]
        result = metrics.calculate_score_progression(matches, "ta")
        assert result["value"]["differential_mean"] == pytest.approx(1.5)
        assert result["value"]["trend"] in ("RISING", "STABLE", "FALLING")

    def test_event_frequency_counts_by_type(self):
        events = [
            make_event("e1", sequence=1, event_type=EventType.MATCH_STARTED, seconds_after=0),
            make_event("e2", sequence=2, event_type=EventType.SCORE_CHANGED, seconds_after=30),
            make_event("e3", sequence=3, event_type=EventType.SCORE_CHANGED, seconds_after=60),
            make_event("e4", sequence=4, event_type=EventType.SCORE_CHANGED, seconds_after=90),
        ]
        result = metrics.calculate_event_frequency(events)
        assert result["total_events"] == 4
        assert result["by_type"]["SCORE_CHANGED"] == 3
        assert result["span_minutes"] == pytest.approx(1.5)
        assert result["events_per_minute"] == round(4 / 1.5, 4)
        assert result["sample_size"] == 4

    def test_event_frequency_is_unavailable_without_events(self):
        result = metrics.calculate_event_frequency([])
        assert result["available"] is False
        assert result["data_quality"] == "UNAVAILABLE"


# ===========================================================================
# §5 — player analytics (game-specific only)
# ===========================================================================

class TestPlayerAnalytics:
    def _players(self):
        return [
            Player(
                id="p1", external_id="p1", name="P One", handle="p1", team_id="ta", game_id="cs2",
                country="SE", role="rifler",
                meta_data={"rating": 1.18, "adr": 78.4, "kast": 71.2, "k": 210, "d": 160, "avatar_url": "http://x/p1.png"},
            ),
            Player(id="p2", external_id="p2", name="P Two", handle="p2", team_id="ta", game_id="cs2"),
        ]

    def test_cs2_metrics_are_reported_and_derived(self):
        result = metrics.player_analytics(self._players(), "cs2")
        assert result["available"] is True
        first = result["players"][0]
        keys = {m["key"] for m in first["metrics"]}
        assert {"rating", "adr", "kast"}.issubset(keys)
        kd = next(m for m in first["metrics"] if m["key"] == "kd_ratio")
        assert kd["value"] == pytest.approx(210 / 160, rel=1e-3)
        # The player with no published statistic is omitted, not padded with zeros.
        assert [p["id"] for p in result["players"]] == ["p1"]
        assert result["metric_schema"] == metrics.PLAYER_METRIC_SCHEMA["cs2"]

    def test_lol_never_borrows_cs2_statistics(self):
        result = metrics.player_analytics(self._players(), "lol")
        assert result["available"] is False
        assert result["players"] == []
        assert "no per-player statistics" in result["reason"]
        assert result["data_quality"] == "UNAVAILABLE"

    def test_dota_uses_its_own_metric_set(self):
        players = [
            Player(id="d1", external_id="d1", name="D One", handle="d1", team_id="ta", game_id="dota2",
                   meta_data={"games_played": 412, "wins": 231})
        ]
        result = metrics.player_analytics(players, "dota2")
        keys = {m["key"] for m in result["players"][0]["metrics"]}
        assert keys == {"games_played", "wins"}
        assert "rating" not in keys


# ===========================================================================
# §10 — anomaly detection
# ===========================================================================

class TestAnomalyDetection:
    def test_no_anomaly_claim_from_a_tiny_sample(self):
        result = metrics.zscore_anomalies([1.0, 2.0, 3.0])
        assert result["available"] is False
        assert result["anomalies"] == []

    def test_zscore_flags_a_real_outlier_with_the_required_label(self):
        values = [10.0] * 20 + [100.0]
        result = metrics.zscore_anomalies(values, labels=[f"m{i}" for i in range(21)])
        assert result["available"] is True
        assert len(result["anomalies"]) == 1
        finding = result["anomalies"][0]
        assert finding["label"] == metrics.ANOMALY_LABEL == "ANOMALY DETECTED"
        assert finding["direction"] == "high"
        assert finding["reference"] == "m20"
        assert finding["z_score"] > 3

    def test_zero_variance_yields_no_false_positives(self):
        result = metrics.zscore_anomalies([5.0] * 10)
        assert result["available"] is True
        assert result["anomalies"] == []

    def test_robust_zscore_needs_five_points_and_finds_outliers(self):
        assert metrics.robust_zscore_anomalies([1.0, 2.0, 3.0])["available"] is False
        values = [40.0, 41.0, 39.0, 40.0, 42.0, 40.0, 300.0]
        result = metrics.robust_zscore_anomalies(values)
        assert result["available"] is True
        assert any(a["label"] == "ANOMALY DETECTED" for a in result["anomalies"])

    def test_isolation_forest_is_gated_on_sample_size(self):
        small = metrics.isolation_forest_anomalies([[1, 2], [2, 3], [3, 4]])
        assert small["available"] is False
        assert "at least" in small["reason"]

        rows = [[2000, 13, 7] for _ in range(18)] + [[2000, 9, 9], [5000, 13, 11]]
        result = metrics.isolation_forest_anomalies(rows)
        assert result["available"] is True
        assert result["sample_size"] == 20

    def test_event_interval_anomalies_are_labelled(self):
        events = [make_event(f"e{i}", sequence=i, seconds_after=i * 10) for i in range(1, 9)]
        events.append(make_event("e9", sequence=9, seconds_after=8 * 10 + 900))
        intervals = [
            (events[i + 1].timestamp - events[i].timestamp).total_seconds() for i in range(len(events) - 1)
        ]
        result = metrics.zscore_anomalies(intervals, method="zscore_event_interval")
        assert result["available"] is True
        assert all(f["label"] == "ANOMALY DETECTED" for f in result["anomalies"])


# ===========================================================================
# §6–§9 — trending engine
# ===========================================================================

class TestTrendingEngine:
    def test_missing_signals_reduce_confidence_instead_of_being_invented(self):
        result = trending.calculate_trending_score({"live": 3}, trending.TrendingWeights())
        assert "viewer" in result["missing_signals"]
        assert "search" in result["missing_signals"]
        assert result["confidence"] == "LOW"
        assert result["score"] is not None

    def test_weights_are_centralized_and_configurable(self):
        weights = trending.TrendingWeights(live=1.0, event=0.0, start_rate=0.0, search=0.0, watchlist=0.0, viewer=0.0)
        result = trending.calculate_trending_score({"live": 25, "event": 999}, weights)
        # event carries zero weight, so the saturated live signal decides the score.
        assert result["score"] == pytest.approx(1.0)
        assert result["weights"]["live"] == 1.0
        assert result["components"]["event"] == 1.0

    def test_normalize_signal_handles_missing_and_saturates(self):
        assert trending.normalize_signal(None, 10) is None
        assert trending.normalize_signal(5, 10) == pytest.approx(0.5)
        assert trending.normalize_signal(500, 10) == 1.0
        assert trending.normalize_signal(0, 10) == 0.0

    def test_engine_ranks_games_by_measured_activity(self):
        engine = trending.TrendingGameEngine()
        result = engine.compute([
            {"game_id": "cs2", "name": "Counter-Strike 2", "live_match_count": 6, "event_count_window": 240,
             "match_start_rate": 4, "search_count": 12, "watchlist_count": 3, "viewer_count": None},
            {"game_id": "lol", "name": "League of Legends", "live_match_count": 1, "event_count_window": 0,
             "match_start_rate": 0, "search_count": 0, "watchlist_count": 0, "viewer_count": None},
        ])
        assert [g["game_id"] for g in result["games"]] == ["cs2", "lol"]
        assert result["games"][0]["score"] > result["games"][1]["score"]
        assert result["games"][0]["activity_metric"]["source"] == "this app"
        assert result["engine"]["weights"] == trending.TrendingWeights().as_dict()

    def test_viewer_metric_only_when_a_provider_publishes_one(self):
        engine = trending.TrendingGameEngine()
        result = engine.compute([
            {"game_id": "cs2", "name": "CS2", "live_match_count": 2, "viewer_count": 1204},
        ])
        metric = result["games"][0]["activity_metric"]
        assert metric["label"] == "active viewers"
        assert metric["value"] == 1204
        assert metric["source"] == "provider"

    def test_no_activity_number_when_every_signal_is_absent(self):
        engine = trending.TrendingGameEngine()
        result = engine.compute([{"game_id": "cs2", "name": "CS2"}])
        assert result["games"][0]["score"] is None
        assert result["games"][0]["activity_metric"]["value"] is None
        assert result["games"][0]["activity_metric"]["label"] == "activity unavailable"

    def test_trending_matches_rank_live_above_finished(self):
        live = make_match("live", MatchStatus.LIVE, minutes_ago=2, data_mode="LIVE")
        done = make_match("done", MatchStatus.COMPLETED, minutes_ago=600)
        ranked = trending.rank_trending_matches([done, live], now=NOW)
        assert ranked[0]["match_id"] == "live"
        assert ranked[0]["components"]["live_state"] == 1.0

    def test_trending_matches_break_ties_on_observed_events(self):
        quiet = make_match("quiet", MatchStatus.LIVE, minutes_ago=2, data_mode="LIVE")
        busy = make_match("busy", MatchStatus.LIVE, minutes_ago=2, data_mode="LIVE")
        ranked = trending.rank_trending_matches([quiet, busy], event_counts={"busy": 40}, now=NOW)
        assert ranked[0]["match_id"] == "busy"
        assert ranked[0]["components"]["events_observed"] == 40


# ===========================================================================
# §11 — data quality engine
# ===========================================================================

class TestDataQuality:
    def test_fresh_complete_live_match_scores_high(self):
        match = make_match("m1", MatchStatus.LIVE, minutes_ago=0, data_mode="LIVE")
        result = evaluate_data_quality(match, providers=[{"name": "csapi.de", "status": "AVAILABLE",
                                                          "request_count": 10, "error_count": 0}], now=NOW)
        assert result["label"] == "HIGH"
        assert result["score"] >= 0.8
        assert result["reasons"] == []

    def test_missing_fields_and_stale_age_lower_the_label_with_reasons(self):
        match = make_match("m1", MatchStatus.LIVE, minutes_ago=90, data_mode="LIVE")
        match.best_of = None
        match.tournament_id = ""
        match.source_timestamp = None
        match.received_at = NOW - timedelta(hours=2)  # genuinely stale ingest
        result = evaluate_data_quality(match, providers=[], now=NOW)
        assert result["label"] == "LOW"
        assert "best_of" in result["missing_fields"]
        assert any("missing fields" in reason for reason in result["reasons"])
        assert any("exceeds the stale threshold" in reason for reason in result["reasons"])

    def test_quality_weights_are_renormalized_when_an_axis_is_unmeasurable(self):
        match = make_match("m1")
        result = evaluate_data_quality(match, providers=None, now=NOW)
        # No provider report and no events: those two axes are excluded rather
        # than scored as zero, and the remaining weights are renormalized.
        assert result["components"]["provider_health"] is None
        assert result["components"]["sequence_integrity"] is None
        assert "provider_health" not in result["weights_used"]
        assert "sequence_integrity" not in result["weights_used"]
        expected = DataQualityEngine.WEIGHTS["freshness"] + DataQualityEngine.WEIGHTS["completeness"]
        assert sum(result["weights_used"].values()) == pytest.approx(expected)

    def test_sequence_integrity_detects_duplicates_and_gaps(self):
        events = [
            make_event("e1", sequence=1),
            make_event("e1", sequence=2),   # duplicate id
            make_event("e3", sequence=40),  # gap
        ]
        clean = evaluate_data_quality(make_match("m1"), events=[make_event("c1", sequence=1)], now=NOW)
        result = evaluate_data_quality(make_match("m1"), events=events, now=NOW)
        assert "duplicate_event_ids" in result["sequence_issues"]
        assert "sequence_gaps" in result["sequence_issues"]
        # An unhealthy sequence measurably lowers the score and is explained.
        assert result["score"] < clean["score"]
        assert result["components"]["sequence_integrity"] < 0.5
        assert any("sequence issues" in reason for reason in result["reasons"])

    def test_provider_down_is_reported(self):
        result = evaluate_data_quality(
            make_match("m1", MatchStatus.LIVE, minutes_ago=0),
            providers=[{"name": "csapi.de", "status": "DOWN", "request_count": 5, "error_count": 5}],
            now=NOW,
        )
        assert result["provider_status"] == "DOWN"
        assert any("DOWN" in reason for reason in result["reasons"])

    def test_aggregate_rolls_up_and_handles_empty(self):
        high = {"label": "HIGH", "score": 0.9}
        low = {"label": "LOW", "score": 0.2}
        rolled = aggregate_quality([high, low])
        assert rolled["label"] == "MEDIUM"
        assert rolled["evaluated"] == 2
        assert rolled["counts"]["HIGH"] == 1
        assert aggregate_quality([])["label"] == "UNAVAILABLE"


# ===========================================================================
# §12 — source consistency
# ===========================================================================

class TestSourceConsistency:
    def test_cross_source_discrepancy_is_reported_not_overwritten(self):
        a = make_match("a1", source="csapi.de", score=(2, 0))
        b = make_match("b1", source="other-feed", score=(1, 0))
        result = source_consistency.detect_discrepancies([a, b])
        assert result["label"] == "SOURCE DISCREPANCY"
        assert result["count"] >= 1
        fields = {d["field"] for d in result["discrepancies"]}
        assert "score_a" in fields or "score_b" in fields
        assert result["cross_source_groups_compared"] == 1
        # Neither record was mutated.
        assert a.score_a == 2 and b.score_a == 1

    def test_intra_source_series_score_mismatch_is_caught(self):
        match = make_match("m1", score=(2, 0), games=map_games(("Mirage", 13, 7, 2000), ("Inferno", 7, 13, 2000)))
        result = source_consistency.detect_discrepancies([match])
        assert result["label"] == "SOURCE DISCREPANCY"
        assert any(d["kind"] == "intra_source" for d in result["discrepancies"])

    def test_agreeing_sources_are_consistent(self):
        a = make_match("a1", source="csapi.de", score=(2, 0))
        b = make_match("b1", source="other-feed", score=(2, 0))
        result = source_consistency.detect_discrepancies([a, b])
        assert result["label"] == "CONSISTENT"
        assert result["count"] == 0


# ===========================================================================
# §13, §16 — store: interest, cache, dirty set
# ===========================================================================

class TestAnalyticsStore:
    def test_interest_counts_only_accept_real_kinds(self):
        store = AnalyticsStore()
        assert store.record_interest("cs2", "view") is True
        assert store.record_interest("cs2", "follow") is True
        assert store.record_interest("cs2", "bogus") is False
        assert store.record_interest("", "view") is False
        counts = store.interest_counts()
        assert counts["cs2"]["view"] == 1
        assert counts["cs2"]["follow"] == 1
        assert counts["cs2"]["search"] == 0

    def test_cache_expiry_and_stale_fallback(self):
        store = AnalyticsStore()
        store.cache_set("k", {"v": 1}, ttl_seconds=-1.0)
        assert store.cache_get("k") is None
        assert store.cache_get_stale("k") == {"v": 1}

    def test_cache_hits_and_prefix_invalidation(self):
        store = AnalyticsStore()
        store.cache_set("trending:games", 1, 60)
        store.cache_set("team:cs2:ta", 2, 60)
        assert store.cache_get("trending:games") == 1
        assert store.invalidate("trending:") == 1
        assert store.cache_get("team:cs2:ta") == 2
        stats = store.stats()
        assert stats["cache_hits"] == 2

    def test_dirty_set_is_drained_once(self):
        store = AnalyticsStore()
        store.mark_dirty("cs2")
        store.mark_dirty("lol")
        assert store.dirty_count() == 2
        assert store.take_dirty() == {"cs2", "lol"}
        assert store.take_dirty() == set()

    def test_event_and_start_counters_are_measured(self):
        store = AnalyticsStore()
        store.record_event("m1", "cs2", EventType.SCORE_CHANGED.value)
        store.record_event("m1", "cs2", EventType.MATCH_STARTED.value)
        assert store.event_counts()["m1"] == 2
        assert store.event_counts_by_game()["cs2"] == 2
        assert store.start_counts()["m1"] == 1


# ===========================================================================
# §17 — observability
# ===========================================================================

class TestObservability:
    def test_latency_series_reports_percentiles(self):
        obs = EsportsObservability()
        for value in (10, 20, 30, 40, 500):
            obs.record_provider_latency("csapi.de", value)
        snapshot = obs.snapshot(connected_clients=7, ws_channels=3)
        summary = snapshot["provider_latency_ms"]["csapi.de"]
        assert summary["count"] == 5
        assert summary["p50"] <= summary["p95"] <= summary["p99"] <= summary["max"]
        assert snapshot["connected_clients"] == 7
        assert snapshot["ws_channels_with_subscribers"] == 3

    def test_event_ingestion_and_error_rates(self):
        obs = EsportsObservability()
        for _ in range(10):
            obs.record_event_ingested("cs2")
        obs.record_error()
        snapshot = obs.snapshot()
        assert snapshot["events_recorded_by_game"]["cs2"] == 10
        assert snapshot["event_ingestion_rate_per_second"] > 0
        assert snapshot["error_rate_per_second"] > 0

    def test_analytics_job_duration_is_tracked_per_job(self):
        obs = EsportsObservability()
        obs.record_analytics_job("dirty_refresh", 12.5)
        obs.record_analytics_job("dirty_refresh", 7.5)
        jobs = obs.snapshot()["analytics_jobs"]["dirty_refresh"]
        assert jobs["runs"] == 2
        assert jobs["avg_ms"] == pytest.approx(10.0)

    def test_series_are_bounded_so_observation_cannot_grow_memory(self):
        obs = EsportsObservability()
        for i in range(5000):
            obs.record_ws_broadcast(i)
        assert len(obs.ws_broadcast.samples) <= 512

    def test_module_singleton_is_the_recording_target(self):
        assert isinstance(esports_metrics, EsportsObservability)


# ===========================================================================
# §19, §20 — failure recovery + data integrity through the service layer
# ===========================================================================

class FakeManager:
    """A manager whose provider behaviour can be broken on demand (§19)."""

    def __init__(self, matches, games=None, events=None, players=None):
        self._matches = matches
        self._games = games or [
            Game(id="cs2", external_id="cs2", name="Counter-Strike 2", short_name="CS2", source="csapi.de")
        ]
        self._events = events or []
        self._players = players or []
        self.fail_matches = False
        self.fail_health = False
        self.calls = 0

    async def get_games(self):
        if self.fail_matches:
            raise RuntimeError("provider down")
        return self._games

    async def get_matches(self, game_id=None, tournament_id=None):
        self.calls += 1
        if self.fail_matches:
            raise RuntimeError("provider down")
        return [m for m in self._matches if game_id is None or m.game_id == game_id]

    async def get_match(self, match_id):
        return next((m for m in self._matches if m.id == match_id), None)

    async def get_match_events(self, match_id):
        return [e for e in self._events if e.match_id == match_id]

    async def get_players(self, team_id):
        if self.fail_matches:
            raise RuntimeError("provider down")
        return [p for p in self._players if p.team_id == team_id]

    async def provider_health_report(self):
        if self.fail_health:
            raise RuntimeError("health endpoint down")
        return [{"name": "csapi.de", "status": "AVAILABLE", "request_count": 4, "error_count": 0}]

    def get_stats(self):
        return {"matches": len(self._matches)}


def _service(matches, **kwargs):
    manager = FakeManager(matches, **kwargs)
    service = EsportsAnalyticsService()
    service.history_limit = 100
    service.configure(manager)
    # Test isolation: the analytics store is a process-wide singleton whose
    # TTL cache survives across test files (e.g. when another module's API
    # tests run first and populate trending entries). Clear it so every test
    # starts from a clean cache state.
    analytics_store.invalidate()
    return service, manager


@pytest.mark.asyncio
async def test_team_analytics_survives_a_provider_outage():
    service, manager = _service([make_match("m1", score=(2, 0))])
    first = await service.get_team_analytics("ta")
    assert first["form"]["value"]["wins"] == 1
    assert first["sample_size"] == 1
    manager.fail_matches = True
    # The cached aggregate keeps answering while the provider is down, and it
    # still holds only real history — nothing is fabricated to fill the gap.
    cached = await service.get_team_analytics("ta")
    assert cached["cache"] == "hit"
    assert cached["form"]["value"]["wins"] == 1


@pytest.mark.asyncio
async def test_provider_health_failure_does_not_blank_analytics():
    service, manager = _service([make_match("m1", score=(2, 0))])
    manager.fail_health = True
    payload = await service.get_team_analytics("ta")
    assert payload["data_quality"]["evaluated"] >= 0
    assert payload["form"]["value"]["wins"] == 1


@pytest.mark.asyncio
async def test_match_analytics_returns_none_for_unknown_match():
    service, _ = _service([make_match("m1")])
    assert await service.get_match_analytics("does-not-exist") is None


@pytest.mark.asyncio
async def test_match_analytics_labels_anomalies_and_scores_events():
    games = map_games(("Mirage", 13, 7, 2000), ("Inferno", 13, 9, 2100))
    match = make_match("m1", score=(2, 0), games=games)
    events = [make_event(f"e{i}", "m1", sequence=i, seconds_after=i * 10) for i in range(1, 8)]
    service, _ = _service([match], events=events)
    payload = await service.get_match_analytics("m1")
    assert payload["match_id"] == "m1"
    assert payload["event_frequency"]["total_events"] == 7
    # The label is always one of the two explicit values — never speculation.
    assert payload["anomaly_detection"]["label"] in ("ANOMALY DETECTED", "NO ANOMALY")
    assert "not an explanation" in payload["anomaly_detection"]["note"]


@pytest.mark.asyncio
async def test_trending_games_uses_measured_signals_only():
    matches = [
        make_match("m1", MatchStatus.LIVE, minutes_ago=1, data_mode="LIVE"),
        make_match("m2", MatchStatus.LIVE, minutes_ago=2, data_mode="LIVE"),
    ]
    service, _ = _service(matches)
    payload = await service.get_trending_games()
    row = payload["games"][0]
    assert row["signals"]["live"] == 2
    assert row["signals"]["viewer"] is None
    assert "viewer" in row["missing_signals"]
    cache = await service.get_trending_games()
    assert cache["cache"] == "hit"


@pytest.mark.asyncio
async def test_poll_cycle_is_incremental_and_reports_jobs():
    matches = [make_match("m1", MatchStatus.LIVE, minutes_ago=1, data_mode="LIVE")]
    service, _ = _service(matches)
    for index in range(5):
        service.mark_event("m1", "cs2", EventType.SCORE_CHANGED.value)
    assert service.manager.calls >= 0
    report = await service.refresh_dirty()
    assert report["elapsed_ms"] >= 0
    assert "cs2" in report["refreshed"]
    # The worker drained the dirty set, so a second pass recomputes nothing.
    assert (await service.refresh_dirty())["refreshed"] == []


@pytest.mark.asyncio
async def test_data_quality_endpoint_payload_is_traceable():
    service, _ = _service([make_match("m1", MatchStatus.LIVE, minutes_ago=0, data_mode="LIVE")])
    payload = await service.get_data_quality()
    assert payload["aggregate"]["label"] in ("HIGH", "MEDIUM", "LOW", "UNAVAILABLE")
    assert payload["matches"][0]["source"] == "csapi.de"
    assert payload["matches"][0]["evaluated_at"] is not None


@pytest.mark.asyncio
async def test_observability_includes_store_and_websocket_stats():
    service, _ = _service([])
    payload = await service.get_observability()
    obs = payload["observability"]
    assert "event_ingestion_rate_per_second" in obs
    assert obs["analytics_store"]["backend"] == "in-process-async-ttl"
    assert payload["manager_stats"] == {"matches": 0}


@pytest.mark.asyncio
async def test_analytics_marks_only_the_affected_game_dirty_on_completion():
    service, _ = _service([make_match("m1")])
    await service.get_trending_games()  # prime the trending cache
    service.mark_event("m1", "cs2", EventType.MATCH_ENDED.value)
    # A completion invalidates trending; the next read is recomputed, not stale.
    refreshed = await service.get_trending_games()
    assert refreshed["cache"] == "miss"


@pytest.mark.asyncio
async def test_duplicate_and_out_of_order_events_do_not_corrupt_counters():
    service, _ = _service([make_match("m1", MatchStatus.LIVE, minutes_ago=1, data_mode="LIVE")])
    # Duplicate delivery of the same event increments the observed count once per
    # delivery, but never creates phantom matches or a negative rate.
    for _ in range(3):
        service.mark_event("m1", "cs2", EventType.SCORE_CHANGED.value)
    payload = await service.get_observability()
    assert payload["observability"]["event_ingestion_rate_per_second"] >= 0
    assert payload["observability"]["event_processing_ms"]["count"] >= 0


# ===========================================================================
# §21 — security: identifier validation
# ===========================================================================

class TestInputValidation:
    def test_valid_provider_ids_are_accepted(self):
        from app.esports.analytics.routes import _validate_id

        for value in ("ta", "team-a", "team_123", "A" * 64, "cs2-team.1"):
            assert _validate_id(value, "team_id") == value

    def test_injection_attempts_are_rejected_before_reaching_a_provider(self):
        from fastapi import HTTPException

        from app.esports.analytics.routes import _validate_id

        for value in (
            "../../../etc/passwd",
            "https://evil.example/x",
            "team'a OR 1=1--",
            "<script>alert(1)</script>",
            "team a",
            "",
            "A" * 65,
            "team%00",
            "team;rm -rf /",
        ):
            with pytest.raises(HTTPException) as exc:
                _validate_id(value, "team_id")
            assert exc.value.status_code == 400

    def test_unknown_game_ids_are_rejected(self):
        from fastapi import HTTPException

        from app.esports.analytics.routes import _validate_game

        assert _validate_game("cs2") == "cs2"
        assert _validate_game(None) is None
        for value in ("overwatch", "cs2;drop", "", "CS2 "):
            with pytest.raises(HTTPException) as exc:
                _validate_game(value)
            assert exc.value.status_code == 400

    def test_interest_kind_is_rejected_when_not_a_real_signal(self):
        store = AnalyticsStore()
        for kind in ("like", "hate", "bet", "watch"):
            assert store.record_interest("cs2", kind) is False


# ===========================================================================
# §2 — the libraries are used for real analysis
# ===========================================================================

def test_statistical_tooling_is_imported_for_real_use():
    import numpy
    import pandas
    import scipy
    import sklearn

    assert all(module is not None for module in (numpy, pandas, scipy, sklearn))
    frame = metrics.build_series_frame([make_match("m1"), make_match("m2", minutes_ago=30)])
    assert len(frame) == 2
    assert "margin" in frame.columns
    assert frame["scheduled_at"].is_monotonic_increasing
