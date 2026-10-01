"""
Time-series edge cases + look-ahead-bias protection (spec §96, §25).

The leakage tests are the important ones: they mechanically prove that row ``i``'s
features cannot see the future (by truncating the series and comparing) and that
the target really is the future return it claims to be.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from app.crypto.forecasting import features as feature_mod
from app.crypto.schemas import Candle
from app.crypto.tests.synthetic import (
    EPOCH,
    duplicated,
    flat_candles,
    make_candles,
    out_of_order,
    with_gaps,
)

HORIZON = 3


class TestFeatureEdges:
    def test_insufficient_history_reports_reason(self):
        matrix = feature_mod.build_features(make_candles(30), horizon=HORIZON)
        assert matrix.n_rows == 0
        assert matrix.diagnostics["reason"] == "insufficient history"

    def test_deterministic_matrix(self):
        candles = make_candles(200)
        a = feature_mod.build_features(candles, horizon=HORIZON)
        b = feature_mod.build_features(candles, horizon=HORIZON)
        assert a.X == b.X
        assert a.y == b.y

    def test_duplicate_and_out_of_order_do_not_break_matrix(self):
        base = make_candles(200)
        for variant in (duplicated(base), out_of_order(base)):
            matrix = feature_mod.build_features(variant, horizon=HORIZON)
            assert matrix.n_rows > 0
            stamps = [ts.isoformat() for ts in matrix.feature_timestamps]
            assert stamps == sorted(stamps)

    def test_gapped_series_still_builds(self):
        candles = with_gaps(make_candles(200), drop_indices=[50, 51, 100, 150])
        matrix = feature_mod.build_features(candles, horizon=HORIZON)
        assert matrix.n_rows > 100  # real rows survive; gaps just shift timestamps

    def test_zero_price_rows_are_dropped_not_imputed(self):
        candles = make_candles(200)
        poisoned = list(candles)
        poisoned[120] = Candle(
            timestamp=poisoned[120].timestamp, open=0.0, high=1.0, low=0.0, close=0.0, volume=1.0
        )
        matrix = feature_mod.build_features(poisoned, horizon=HORIZON)
        # The row and its neighbours that depended on it must not appear.
        stamps = [ts.isoformat() for ts in matrix.feature_timestamps]
        assert poisoned[120].timestamp.isoformat() not in stamps

    def test_timezone_aware_and_naive_equivalent(self):
        aware = make_candles(150)
        naive = [
            Candle(
                timestamp=c.timestamp.replace(tzinfo=None),
                open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume,
            )
            for c in aware
        ]
        a = feature_mod.build_features(aware, horizon=HORIZON)
        b = feature_mod.build_features(naive, horizon=HORIZON)
        assert a.X == b.X
        assert a.y == b.y

    def test_latest_row_is_newest_computable_observation(self):
        candles = make_candles(200)
        matrix = feature_mod.build_features(candles, horizon=HORIZON)
        assert matrix.latest_row
        assert matrix.latest_candle_index == len(candles) - 1
        assert matrix.latest_base_close == pytest.approx(candles[-1].close)
        live = feature_mod.latest_matrix(matrix)
        assert live is not None and len(live.X) == 1
        assert live.base_close[0] == pytest.approx(candles[-1].close)


class TestLeakage:
    """spec §25: no future candle may influence a feature row."""

    def test_truncation_does_not_change_earlier_rows(self):
        candles = make_candles(200)
        full = feature_mod.build_features(candles, horizon=HORIZON)
        for cut in (150, 180):
            truncated = feature_mod.build_features(candles[:cut], horizon=HORIZON)
            # Every row present in both must be identical.
            for row in range(min(full.n_rows, truncated.n_rows)):
                assert full.X[row] == truncated.X[row], f"leakage at row {row}, cut={cut}"
            # And the targets must match too.
            assert full.y[: truncated.n_rows] == truncated.y[: truncated.n_rows]

    def test_target_is_exactly_the_future_return(self):
        candles = make_candles(200)
        matrix = feature_mod.build_features(candles, horizon=HORIZON)
        for row in range(matrix.n_rows):
            base = matrix.base_close[row]
            candle_index = matrix.candle_indices[row]
            expected = math.log(candles[candle_index + HORIZON].close / base)
            assert matrix.y[row] == pytest.approx(expected)

    def test_feature_timestamps_precede_target_timestamps(self):
        candles = make_candles(200)
        matrix = feature_mod.build_features(candles, horizon=HORIZON)
        for feature_ts, target_ts, index in zip(
            matrix.feature_timestamps, matrix.target_timestamps, matrix.candle_indices
        ):
            assert target_ts > feature_ts
            assert target_ts == candles[index + HORIZON].timestamp

    def test_appending_future_rows_does_not_change_past_targets(self):
        candles = make_candles(150)
        matrix_before = feature_mod.build_features(candles, horizon=HORIZON)
        future_extra = make_candles(20, start=candles[-1].close)
        # Rebase the appended block's timestamps to continue the series.
        shifted = [
            Candle(
                timestamp=candles[-1].timestamp + timedelta(seconds=3600 * (i + 1)),
                open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume,
            )
            for i, c in enumerate(future_extra)
        ]
        matrix_after = feature_mod.build_features(list(candles) + shifted, horizon=HORIZON)
        n = matrix_before.n_rows
        assert matrix_after.X[:n] == matrix_before.X[:n]
        assert matrix_after.y[:n] == matrix_before.y[:n]

    def test_flat_series_has_zero_targets(self):
        candles = flat_candles(200)
        matrix = feature_mod.build_features(candles, horizon=HORIZON)
        assert all(value == pytest.approx(0.0) for value in matrix.y)
