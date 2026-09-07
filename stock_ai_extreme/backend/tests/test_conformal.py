import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge

from app.conformal import calibrate_split_conformal


def _linear_with_noise(n=400, noise_std=2.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.arange(n, dtype=float)
    y = 3.0 * x + rng.normal(0, noise_std, n)
    X = pd.DataFrame({"x": x})
    y = pd.Series(y)
    return X, y


def test_half_width_is_positive_and_finite():
    X, y = _linear_with_noise()
    result = calibrate_split_conformal(lambda: Ridge(alpha=0.1), X, y, confidence=0.9)
    assert result.half_width > 0
    assert result.confidence == 0.9
    assert result.calibration_size > 0


def test_raises_when_not_enough_rows():
    X, y = _linear_with_noise(n=10)
    with pytest.raises(ValueError):
        calibrate_split_conformal(lambda: Ridge(alpha=0.1), X, y, calibration_frac=0.9, min_calibration_points=15)


def test_half_width_for_step_grows_with_horizon():
    X, y = _linear_with_noise()
    result = calibrate_split_conformal(lambda: Ridge(alpha=0.1), X, y)
    w1 = result.half_width_for_step(1)
    w4 = result.half_width_for_step(4)
    w9 = result.half_width_for_step(9)
    assert w1 < w4 < w9
    assert w4 == pytest.approx(w1 * 2, rel=1e-6)   # sqrt(4)=2
    assert w9 == pytest.approx(w1 * 3, rel=1e-6)   # sqrt(9)=3


def test_empirical_coverage_is_reasonably_close_to_target_on_unseen_test_data():
    """The real validation of conformal prediction: build the interval on a
    calibration slice, then check on a THIRD, still-unseen slice whether
    roughly `confidence` fraction of true values actually land inside it."""
    X, y = _linear_with_noise(n=1000, noise_std=2.0, seed=1)
    n_test = 200
    X_fit, y_fit = X.iloc[:-n_test], y.iloc[:-n_test]
    X_test, y_test = X.iloc[-n_test:], y.iloc[-n_test:]

    confidence = 0.9
    result = calibrate_split_conformal(lambda: Ridge(alpha=0.1), X_fit, y_fit, confidence=confidence)

    # refit on all of X_fit/y_fit (mirrors how the app uses this: calibrate,
    # then train the "real" model on everything before the true forecast horizon)
    model = Ridge(alpha=0.1).fit(X_fit, y_fit)
    preds = model.predict(X_test)
    covered = np.abs(y_test.to_numpy() - preds) <= result.half_width
    empirical_coverage = covered.mean()

    # Split-conformal only guarantees *marginal* coverage and this is a finite
    # sample, so allow a reasonable tolerance band rather than an exact match.
    assert empirical_coverage > confidence - 0.08
