"""
Tests for the observed-movement event study (Phase 17, spec §7, §9, §10).

The study is pure aggregation over already-stored movement rows, so every test
here is a synthetic table built by hand: no provider call, no network and no
expected value copied from a live feed. The contract being pinned down is that
the study reports an honest denominator — measured observations are averaged,
unavailable ones are counted separately and never folded in as 0%.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.breaking_news.config import breaking_news_settings
from app.breaking_news.impact_stats import build_impact_study, summarize_observed_movements

NOW = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)


def row(
    *,
    entity: str = "OGDC",
    entity_type: str = "STOCK",
    observation_window: str = "1h",
    change: float | None = -0.4,
    available: bool = True,
    magnitude: str = "MEDIUM",
    confidence: float | None = 0.8,
    mfe: float | None = 1.2,
    mae: float | None = -1.5,
    volatility: float | None = 0.7,
    published_at: datetime | None = None,
    breaking_news_id: str | None = "evt-1",
    article_id: int | None = 42,
) -> dict:
    return {
        "entity": entity,
        "entity_type": entity_type,
        "observation_window": observation_window,
        "price_change_percent": change,
        "max_favorable_excursion_percent": mfe,
        "max_adverse_excursion_percent": mae,
        "realized_volatility_percent": volatility,
        "confidence": confidence,
        "impact_magnitude": magnitude,
        "window_available": available,
        "news_published_at": published_at or NOW,
        "breaking_news_id": breaking_news_id,
        "article_id": article_id,
    }


class AttrRow:
    """ORM-like row so the study is exercised through attribute access too."""

    def __init__(self, **kwargs):
        for key, value in row(**kwargs).items():
            setattr(self, key, value)


# ===========================================================================
# summarize_observed_movements
# ===========================================================================

def test_empty_sample_reports_no_measurements_instead_of_zero():
    stats = summarize_observed_movements([])
    assert stats["sample_size"] == 0
    assert stats["mean_percent"] is None
    assert stats["median_percent"] is None
    assert stats["hit_rate_up"] is None
    assert stats["best"] is None and stats["worst"] is None


def test_mean_median_and_direction_counts_come_from_the_real_values():
    stats = summarize_observed_movements([
        row(change=2.0),
        row(change=-1.0),
        row(change=0.0),
    ])
    assert stats["sample_size"] == 3
    assert stats["up"] == 1 and stats["down"] == 1 and stats["flat"] == 1
    assert stats["hit_rate_up"] == pytest.approx(1 / 3, abs=1e-4)
    assert stats["mean_percent"] == pytest.approx((2.0 - 1.0 + 0.0) / 3, abs=1e-4)
    assert stats["median_percent"] == pytest.approx(0.0)


def test_unavailable_rows_are_counted_but_never_averaged_as_zero():
    stats = summarize_observed_movements([
        row(change=1.0, available=True),
        row(change=3.0, available=True),
        # A window that could not be measured carries no move. Counting it as 0%
        # would drag the mean from 2.0 to 1.33 — the denominator stays honest.
        row(change=None, available=False),
    ])
    assert stats["sample_size"] == 2
    assert stats["unavailable_samples"] == 1
    assert stats["mean_percent"] == pytest.approx(2.0)


def test_a_single_observation_has_no_dispersion():
    stats = summarize_observed_movements([row(change=1.5)])
    assert stats["sample_size"] == 1
    assert stats["stdev_percent"] is None


def test_sample_deviation_appears_from_two_observations():
    stats = summarize_observed_movements([row(change=0.0), row(change=2.0)])
    assert stats["stdev_percent"] == pytest.approx(1.4142, abs=1e-3)


def test_best_and_worst_are_real_rows_with_their_provenance():
    best = row(entity="HBL", change=4.5, published_at=NOW - timedelta(hours=3))
    worst = row(entity="PPL", change=-3.25, published_at=NOW - timedelta(hours=1))
    stats = summarize_observed_movements([row(change=0.5), best, worst])
    assert stats["best"]["entity"] == "HBL"
    assert stats["best"]["price_change_percent"] == pytest.approx(4.5)
    assert stats["worst"]["entity"] == "PPL"
    assert stats["max_gain_percent"] == pytest.approx(4.5)
    assert stats["max_loss_percent"] == pytest.approx(-3.25)


def test_non_finite_values_are_treated_as_absent_not_as_extremes():
    stats = summarize_observed_movements([
        row(change=float("nan")),
        row(change=float("inf")),
        row(change=1.0),
    ])
    assert stats["sample_size"] == 1
    assert stats["mean_percent"] == pytest.approx(1.0)


def test_observed_window_bounds_use_the_real_timestamps():
    stats = summarize_observed_movements([
        row(change=1.0, published_at=NOW - timedelta(hours=6)),
        row(change=-1.0, published_at=NOW),
    ])
    assert stats["first_observed_at"] == (NOW - timedelta(hours=6)).isoformat()
    assert stats["last_observed_at"] == NOW.isoformat()


def test_attributes_are_read_the_same_way_as_dict_keys():
    stats = summarize_observed_movements([AttrRow(change=2.5), AttrRow(change=0.5)])
    assert stats["sample_size"] == 2
    assert stats["mean_percent"] == pytest.approx(1.5)


def test_magnitude_breakdown_counts_only_measured_rows():
    stats = summarize_observed_movements([
        row(change=3.0, magnitude="HIGH"),
        row(change=0.2, magnitude="LOW"),
        row(change=None, available=False, magnitude="NONE"),
    ])
    assert stats["magnitude_breakdown"]["HIGH"] == 1
    assert stats["magnitude_breakdown"]["LOW"] == 1
    assert stats["magnitude_breakdown"]["NONE"] == 0


# ===========================================================================
# build_impact_study
# ===========================================================================

def test_study_groups_by_entity_type_and_window():
    study = build_impact_study(
        [
            row(entity="OGDC", entity_type="STOCK", observation_window="1h", change=1.0),
            row(entity="OGDC", entity_type="STOCK", observation_window="1h", change=-1.0),
            row(entity="GOLD", entity_type="COMMODITY", observation_window="24h", change=0.5),
        ],
        hours=168,
        min_sample=1,
    )
    assert study["samples_considered"] == 3
    assert study["measured_samples"] == 3
    assert {group["key"] for group in study["by_entity"]} == {"OGDC", "GOLD"}
    assert {group["key"] for group in study["by_entity_type"]} == {"STOCK", "COMMODITY"}
    assert {group["key"] for group in study["by_window"]} == {"1h", "24h"}
    assert study["disclaimer"]


def test_groups_are_ordered_by_sample_size_so_evidence_comes_first():
    study = build_impact_study(
        [
            row(entity="OGDC", change=1.0),
            row(entity="OGDC", change=1.0),
            row(entity="OGDC", change=1.0),
            row(entity="HBL", change=1.0),
        ],
        hours=168,
        min_sample=1,
    )
    assert [group["key"] for group in study["by_entity"]] == ["OGDC", "HBL"]


def test_a_thin_group_is_flagged_insufficient_rather_than_hidden():
    study = build_impact_study(
        [row(entity="HBL", change=2.0)],
        hours=168,
        min_sample=5,
    )
    group = next(g for g in study["by_entity"] if g["key"] == "HBL")
    assert group["sufficient_sample"] is False
    assert group["stats"]["sample_size"] == 1
    assert study["sufficient_groups"] == 0


def test_a_group_meeting_the_threshold_is_marked_sufficient():
    study = build_impact_study(
        [row(entity="OGDC", change=float(i)) for i in range(5)],
        hours=168,
        min_sample=5,
    )
    group = next(g for g in study["by_entity"] if g["key"] == "OGDC")
    assert group["sufficient_sample"] is True
    assert study["sufficient_groups"] >= 1


def test_min_sample_defaults_to_the_configured_value():
    study = build_impact_study([row()], hours=24)
    assert study["min_sample"] == breaking_news_settings.impact_study_min_sample


def test_group_lists_are_capped_by_configuration():
    rows = [row(entity=f"SYM{i}") for i in range(60)]
    study = build_impact_study(rows, hours=168, min_sample=1)
    assert len(study["by_entity"]) <= breaking_news_settings.impact_study_max_groups


def test_an_empty_study_is_safe_and_explicit():
    study = build_impact_study([], hours=24, min_sample=5)
    assert study["overall"]["sample_size"] == 0
    assert study["by_entity"] == []
    assert study["measured_samples"] == 0
    assert study["generated_at"]


def test_the_window_filter_label_is_echoed_back():
    study = build_impact_study(
        [row(observation_window="1h")], hours=48, min_sample=1, window="1h", entity_type="STOCK"
    )
    assert study["window"] == "1h"
    assert study["entity_type"] == "STOCK"
    assert study["hours"] == 48


# ===========================================================================
# API surface
# ===========================================================================

@pytest.fixture
def client():
    from app.db import init_db
    from app.main import app

    init_db()
    # Not used as a context manager: entering it would start the background
    # maintenance loop, which performs real network ingests.
    return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)


def test_impact_study_endpoint_returns_the_documented_shape(client):
    body = client.get("/api/breaking-news/impact/study?hours=24").json()
    assert {
        "generated_at", "hours", "min_sample", "overall", "by_entity",
        "by_entity_type", "by_window", "measured_samples", "unavailable_samples",
        "disclaimer",
    } <= set(body)
    assert body["hours"] == 24
    assert body["overall"]["sample_size"] >= 0
    assert body["disclaimer"]


def test_impact_study_endpoint_validates_the_window(client):
    assert client.get("/api/breaking-news/impact/study?window=7m").status_code == 422
    assert client.get("/api/breaking-news/impact/study?window=4h").status_code == 200
