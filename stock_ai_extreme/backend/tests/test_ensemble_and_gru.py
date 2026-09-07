import pytest

from app.gru_agent import GRUPredictionAgent
from app.ensemble import combine_forecasts, run_ensemble


def _fake_output(prices, rmse, lowers=None, uppers=None):
    lowers = lowers or [p - 5 for p in prices]
    uppers = uppers or [p + 5 for p in prices]
    points = [
        {"date": f"2024-01-{i+1:02d}", "price": p, "lower": lo, "upper": up}
        for i, (p, lo, up) in enumerate(zip(prices, lowers, uppers))
    ]
    return points, {"mae": rmse * 0.8, "rmse": rmse, "model": "fake"}


def test_gru_agent_fails_gracefully_without_tensorflow():
    import pandas as pd
    df = pd.DataFrame({"Close": [100.0] * 150})
    with pytest.raises(ValueError, match="TensorFlow"):
        GRUPredictionAgent().predict(df, horizon=3, epochs=5)


def test_combine_forecasts_weights_more_accurate_model_higher():
    # model A has half the RMSE of model B -> should get roughly 2x the weight
    outputs = {
        "a": _fake_output([100.0, 101.0], rmse=1.0),
        "b": _fake_output([110.0, 111.0], rmse=2.0),
    }
    combined, metrics = combine_forecasts(outputs)
    assert metrics["weights"]["a"] > metrics["weights"]["b"]
    # weighted price should sit strictly between the two component prices,
    # closer to "a" (the lower-error model) than the midpoint
    midpoint = (100.0 + 110.0) / 2
    assert 100.0 < combined[0]["price"] < midpoint


def test_combine_forecasts_reports_disagreement():
    outputs = {
        "a": _fake_output([100.0], rmse=1.0),
        "b": _fake_output([200.0], rmse=1.0),
    }
    combined, _ = combine_forecasts(outputs)
    assert combined[0]["model_disagreement"] > 0


def test_combine_forecasts_raises_on_empty_input():
    with pytest.raises(ValueError):
        combine_forecasts({})


def test_run_ensemble_degrades_gracefully_when_recurrent_models_unavailable():
    import pandas as pd
    df = pd.DataFrame({"Close": [100.0 + i * 0.1 for i in range(150)]})

    def fake_tabular(df, horizon, kind):
        return _fake_output([100.0 + i for i in range(horizon)], rmse=1.5)

    def broken_recurrent(df, horizon):
        raise ValueError("TensorFlow is unavailable. Run: pip install tensorflow")

    points, metrics = run_ensemble(df, horizon=3, tabular_forecaster=fake_tabular,
                                    lstm_forecaster=broken_recurrent, gru_forecaster=broken_recurrent)
    assert set(metrics["components"]) == {"rf", "ridge"}  # both recurrent models silently dropped
    assert len(points) == 3


def test_run_ensemble_includes_recurrent_models_when_available():
    def fake_tabular(df, horizon, kind):
        return _fake_output([100.0] * horizon, rmse=2.0)

    def fake_recurrent(df, horizon):
        return _fake_output([101.0] * horizon, rmse=1.0)

    points, metrics = run_ensemble(None, horizon=2, tabular_forecaster=fake_tabular,
                                    lstm_forecaster=fake_recurrent, gru_forecaster=fake_recurrent)
    assert set(metrics["components"]) == {"rf", "ridge", "lstm", "gru"}
