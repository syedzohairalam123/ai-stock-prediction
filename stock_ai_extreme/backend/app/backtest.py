"""
Phase 9 — walk-forward backtesting.

Rolling-origin evaluation: repeatedly fit on everything up to day T, predict
day T+1, compare against the REAL close that actually happened, then slide
forward. This is the only honest way to backtest a time-series model —
never fit on data that includes the day you're "predicting".

Refitting a model at every single day is unnecessarily slow for a backtest
that's meant to run inside an HTTP request, so the model is refit every
`refit_every` days (an expanding window) and reused for the days in between
— a standard, transparent walk-forward pattern, not a shortcut that hides
anything from the reported metrics.

The paper-trading numbers here assume one specific, simple default strategy
("go long when the model predicts tomorrow's close is higher than today's,
otherwise hold cash") purely so total-return/drawdown/win-rate have a
concrete meaning. This is not a recommended trading strategy — see the
project's rule against ever presenting this as investment advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


FEATURE_COLS = ["Open", "High", "Low", "Close", "Volume", "sma_10", "sma_30", "ema_10", "ema_26",
                "rsi_14", "macd", "macd_signal", "bb_upper", "bb_lower"]


def _model_factory(kind: str):
    if kind == "rf":
        return RandomForestRegressor(n_estimators=150, min_samples_leaf=2, n_jobs=-1, random_state=42)
    return Ridge(alpha=1.0)


@dataclass
class BacktestResult:
    daily: list[dict] = field(default_factory=list)
    mae: float = 0.0
    rmse: float = 0.0
    directional_accuracy: float = 0.0
    total_return_pct: float = 0.0
    benchmark_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    model: str = "ridge"
    refit_every: int = 5
    test_days: int = 0


def walk_forward_backtest(df: pd.DataFrame, model_kind: str = "ridge", test_days: int = 60, refit_every: int = 5) -> BacktestResult:
    cols = [c for c in FEATURE_COLS if c in df.columns]
    z = df.copy()
    z["target"] = z.Close.shift(-1)
    z = z.dropna(subset=cols + ["target"])

    min_train = 100
    if len(z) < min_train + test_days:
        raise ValueError(f"Not enough usable rows for a {test_days}-day backtest — need at least {min_train + test_days}, have {len(z)}.")

    start_idx = len(z) - test_days
    X, y = z[cols], z["target"]

    daily = []
    model = None
    equity = 1.0
    peak_equity = 1.0
    max_drawdown = 0.0
    trade_returns = []
    benchmark_equity = 1.0

    for i, idx in enumerate(range(start_idx, len(z))):
        if model is None or i % refit_every == 0:
            model = _model_factory(model_kind)
            model.fit(X.iloc[:idx], y.iloc[:idx])

        row = X.iloc[[idx]]
        predicted_next_close = float(model.predict(row)[0])
        actual_next_close = float(y.iloc[idx])
        current_close = float(z["Close"].iloc[idx])

        realized_return = (actual_next_close - current_close) / current_close
        went_long = predicted_next_close > current_close

        if went_long:
            equity *= (1 + realized_return)
            trade_returns.append(realized_return)
        benchmark_equity *= (1 + realized_return)  # buy-and-hold every day, for comparison

        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)

        daily.append({
            "date": pd.Timestamp(z.index[idx]).date().isoformat(),
            "actual": round(actual_next_close, 4),
            "predicted": round(predicted_next_close, 4),
            "went_long": went_long,
            "realized_return_pct": round(realized_return * 100, 4),
        })

    actuals = np.array([d["actual"] for d in daily])
    predicteds = np.array([d["predicted"] for d in daily])
    mae = float(mean_absolute_error(actuals, predicteds))
    rmse = float(mean_squared_error(actuals, predicteds) ** 0.5)
    actual_direction = np.sign(np.diff(np.concatenate([[float(z["Close"].iloc[start_idx - 1])], actuals])))
    predicted_direction = np.sign(predicteds - np.concatenate([[float(z["Close"].iloc[start_idx - 1])], actuals[:-1]]))
    directional_accuracy = float(np.mean(actual_direction == predicted_direction))

    return BacktestResult(
        daily=daily,
        mae=round(mae, 4),
        rmse=round(rmse, 4),
        directional_accuracy=round(directional_accuracy, 4),
        total_return_pct=round((equity - 1) * 100, 4),
        benchmark_return_pct=round((benchmark_equity - 1) * 100, 4),
        max_drawdown_pct=round(max_drawdown * 100, 4),
        win_rate=round(float(np.mean([r > 0 for r in trade_returns])) if trade_returns else 0.0, 4),
        num_trades=len(trade_returns),
        model=model_kind,
        refit_every=refit_every,
        test_days=test_days,
    )
