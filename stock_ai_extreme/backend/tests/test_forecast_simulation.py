"""Phase 14.3 — Monte-Carlo probability simulation engine."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import forecast_simulation as sim


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


def _mean_reverting_series(n=120, level=60.0, seed=7):
    rng = np.random.default_rng(seed)
    values = [level]
    for _ in range(n - 1):
        prev = values[-1]
        values.append(prev + 0.25 * (level - prev) + rng.normal(0, 1.2))
    return [min(99.0, max(1.0, v)) for v in values]


def test_logit_sigmoid_roundtrip():
    p = np.array([1.0, 25.0, 50.0, 75.0, 99.0]) / 100.0
    assert np.allclose(sim.sigmoid(sim.logit(p)), p, atol=1e-9)


def test_extract_series_sorts_and_dedupes():
    points = _history([50, 51, 52])
    points.append(dict(points[-1]))  # duplicate timestamp
    ts, probs = sim.extract_series(points)
    assert ts.size == probs.size == 3
    assert list(probs) == pytest.approx([0.50, 0.51, 0.52])


def test_simulation_reports_bands_and_terminal_distribution():
    probabilities = _mean_reverting_series()
    result = sim.simulate_probability(
        history=_history(probabilities),
        current_probability=probabilities[-1],
        horizon_days=30,
        paths=2000,
        model="auto",
        seed=11,
    )

    assert result is not None
    assert result["model"] in {"OU_MEAN_REVERTING", "GBM_RANDOM_WALK", "ENSEMBLE_OU_GBM"}
    assert result["paths"] == 2000
    assert result["sampleSize"] == len(probabilities)
    assert result["steps"] >= 1

    path = result["path"]
    assert len(path["median"]) == result["steps"]
    # Percentile bands must be monotonically ordered at every step.
    for i in range(result["steps"]):
        assert path["p5"][i] <= path["p25"][i] <= path["median"][i] <= path["p75"][i] <= path["p95"][i]
        assert 0.0 <= path["p5"][i] <= 100.0
        assert 0.0 <= path["p95"][i] <= 100.0

    terminal = result["terminal"]
    assert 0.0 <= terminal["pYes"] <= 100.0
    assert terminal["pYes"] + terminal["pNo"] == pytest.approx(100.0)
    assert terminal["percentiles"]["p5"] <= terminal["percentiles"]["p50"] <= terminal["percentiles"]["p95"]
    assert len(terminal["histogram"]["counts"]) == 20
    assert sum(terminal["histogram"]["counts"]) == 2000
    assert len(terminal["pYesConfidenceInterval95"]) == 2


def test_insufficient_history_returns_none():
    assert sim.simulate_probability(history=_history([50, 51]), current_probability=51, horizon_days=10) is None
    assert sim.simulate_probability(history=[], current_probability=None, horizon_days=10) is None


def test_model_override_selects_gbm():
    probabilities = _mean_reverting_series()
    result = sim.simulate_probability(
        history=_history(probabilities),
        current_probability=60.0,
        horizon_days=30,
        paths=1000,
        model="gbm",
        seed=3,
    )
    assert result is not None
    assert result["model"] == "GBM_RANDOM_WALK"


def test_ensemble_model_runs_both_dynamics():
    probabilities = _mean_reverting_series()
    result = sim.simulate_probability(
        history=_history(probabilities),
        current_probability=60.0,
        horizon_days=20,
        paths=1001,
        model="ensemble",
        seed=5,
    )
    assert result is not None
    assert result["model"] == "ENSEMBLE_OU_GBM"
    assert result["paths"] == 1001


def test_simulation_is_deterministic_for_a_seed():
    probabilities = _mean_reverting_series()
    kwargs = dict(
        history=_history(probabilities),
        current_probability=60.0,
        horizon_days=15,
        paths=1500,
        model="auto",
        seed=42,
    )
    first = sim.simulate_probability(**kwargs)
    second = sim.simulate_probability(**kwargs)
    assert first is not None and second is not None
    assert first["path"]["median"] == second["path"]["median"]
    assert first["terminal"]["pYes"] == second["terminal"]["pYes"]
