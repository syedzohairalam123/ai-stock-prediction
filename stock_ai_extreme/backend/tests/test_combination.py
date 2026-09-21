"""Phase 15.1/15.2 — correlation-adjusted combination analysis."""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import combination as combo


def _ou_series(n=80, seed=1, level=0.0, phi=0.9, sigma=0.5, common=None, common_weight=0.9):
    """A bounded, mean-reverting probability series (stays near 50%).

    Log-odds follow an AR(1) around `level`, so the probability never drifts to
    0/1 the way an unconstrained random walk does. When `common` is supplied its
    shocks are shared, which lets a test dial in a chosen correlation.
    """
    rng = np.random.default_rng(seed)
    values = [level]
    for i in range(n - 1):
        shock = rng.normal(0, sigma)
        if common is not None:
            shock = common_weight * common[i] + (1 - common_weight) * shock
        values.append(level + phi * (values[-1] - level) + shock)
    return [100.0 / (1.0 + math.exp(-v)) for v in values]


def _history(probabilities, start=None):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "timestamp": (start + timedelta(days=i)).isoformat(),
            "yesProbability": float(p),
            "noProbability": float(100.0 - p),
        }
        for i, p in enumerate(probabilities)
    ]


def _event(event_id, probabilities, outcome="YES"):
    return {
        "id": event_id,
        "marketId": event_id,
        "label": event_id,
        "outcome": outcome,
        "probability": probabilities[-1],
        "history": _history(probabilities),
    }


def _independence(probabilities):
    product = 1.0
    for probability in probabilities:
        product *= probability / 100.0
    return product * 100.0


def test_nearest_positive_definite_fixes_a_non_psd_matrix():
    bad = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    fixed = combo.nearest_positive_definite(bad)
    eigenvalues = np.linalg.eigvalsh(fixed)
    assert np.all(eigenvalues > -1e-8)
    assert np.allclose(np.diag(fixed), 1.0, atol=1e-8)
    assert np.allclose(fixed, fixed.T, atol=1e-8)


def test_align_series_forward_fills_onto_the_union_window():
    early = _history(_ou_series(10, seed=1))
    late = _history(_ou_series(6, seed=2), start=datetime(2026, 1, 5, tzinfo=timezone.utc))
    matrix = combo.align_series([{"history": early}, {"history": late}])
    assert matrix is not None
    assert matrix.shape[0] == 2
    # No NaNs survive: leading columns the late series never saw are dropped.
    assert not np.isnan(matrix).any()
    assert matrix.shape[1] >= 5


def test_identical_series_produce_near_perfect_correlation():
    probabilities = _ou_series(80, seed=4)
    events = [_event("a", probabilities), _event("b", probabilities)]

    result = combo.combine_events(events, draws=8000, seed=1)

    expected_independence = _independence([probabilities[-1], probabilities[-1]])
    assert result["correlationApplied"] is True
    assert result["correlation"]["matrix"][0][1] > 0.9
    assert result["independenceProbability"] == pytest.approx(expected_independence, abs=0.05)
    # Perfectly dependent events collapse toward the single-event probability,
    # far above the product of two.
    assert result["correlationAdjustedProbability"] > expected_independence + 10.0


def test_uncorrelated_series_stay_near_independence():
    first = _ou_series(100, seed=9)
    second = _ou_series(100, seed=10)
    events = [_event("a", first), _event("b", second)]

    result = combo.combine_events(events, draws=20000, seed=2)

    assert result["correlationApplied"] is True
    assert abs(result["correlationAdjustedProbability"] - result["independenceProbability"]) <= 8.0


def test_independence_fallback_when_history_is_missing():
    events = [
        {"id": "a", "outcome": "YES", "probability": 60.0, "history": []},
        {"id": "b", "outcome": "YES", "probability": 50.0, "history": []},
    ]
    result = combo.combine_events(events, draws=2000, seed=3)

    assert result["correlationApplied"] is False
    assert result["correlation"]["reason"]
    # Falls back to the independence product (60% x 50% = 30%).
    assert result["independenceProbability"] == pytest.approx(30.0, abs=0.01)
    assert result["correlationAdjustedProbability"] == pytest.approx(30.0, abs=1.0)


def test_sensitivity_returns_tornado_and_scenarios():
    events = [
        _event("a", _ou_series(60, seed=11)),
        _event("b", _ou_series(60, seed=12)),
        _event("c", _ou_series(60, seed=13)),
    ]

    result = combo.combine_events(events, draws=3000, delta_pp=10.0, seed=4)

    sensitivity = result["sensitivity"]
    assert len(sensitivity["tornado"]) == 3
    assert len(sensitivity["scenarios"]) == 3
    # Raising an input probability can never lower P(all YES).
    for row in sensitivity["tornado"]:
        assert row["high"] >= row["low"] - 1e-6
        assert row["swing"] == pytest.approx(abs(row["high"] - row["low"]), abs=0.01)
    assert result["atLeastOneProbability"] >= result["correlationAdjustedProbability"]
    assert set(result["exactlyKProbability"].keys()) == {"0", "1", "2", "3"}


def test_outcome_selection_inverts_no_markets():
    probabilities = _ou_series(40, seed=21)
    yes_event = _event("a", probabilities, outcome="YES")
    no_event = _event("b", probabilities, outcome="NO")
    # Same history, opposite outcome: their selected series move oppositely.
    report = combo.correlation_report([yes_event, no_event])
    assert report["matrix"][0][1] < -0.5


def test_correlation_report_shape():
    events = [_event("a", _ou_series(50, seed=31)), _event("b", _ou_series(50, seed=32))]
    report = combo.correlation_report(events)
    for key in ("matrix", "pearson", "spearman", "leadLag", "observations", "applied", "eventLabels"):
        assert key in report
    assert len(report["matrix"]) == 2
    assert len(report["leadLag"]) == 2


def test_invalid_probability_is_rejected():
    with pytest.raises(ValueError):
        combo.combine_events([{"id": "a", "outcome": "YES", "probability": 120.0, "history": []}])
