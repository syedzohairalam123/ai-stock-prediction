"""
Shared training/forecasting logic for gated-recurrent time-series models
(LSTM, GRU). Both `LSTMPredictionAgent` and `GRUPredictionAgent` call into
`forecast_recurrent()` below with a different Keras layer class — the
training loop, scaling, windowing, and recursive multi-step forecast are
identical, so there's exactly one place to fix a bug instead of two.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import MinMaxScaler


def forecast_recurrent(df: pd.DataFrame, horizon: int, lookback: int, epochs: int, cell_type: str) -> tuple[list[dict], dict]:
    try:
        from tensorflow.keras import Sequential
        from tensorflow.keras.callbacks import EarlyStopping
        from tensorflow.keras.layers import GRU, LSTM, Dense, Dropout
    except ImportError as e:
        raise ValueError("TensorFlow is unavailable. Run: pip install tensorflow") from e

    Cell = {"lstm": LSTM, "gru": GRU}.get(cell_type)
    if Cell is None:
        raise ValueError(f"Unknown recurrent cell_type: {cell_type!r} (expected 'lstm' or 'gru')")

    values = df[["Close"]].values.astype("float32")
    if len(values) < lookback + 70:
        raise ValueError(f"{cell_type.upper()} requires at least 100 trading records; select a longer range.")

    scaler = MinMaxScaler()
    s = scaler.fit_transform(values)
    X, y = [], []
    for i in range(lookback, len(s)):
        X.append(s[i - lookback:i])
        y.append(s[i])
    X, y = np.array(X), np.array(y)

    cut = max(30, int(len(X) * .8))
    model = Sequential([
        Cell(64, return_sequences=True, input_shape=(lookback, 1)),
        Dropout(.15),
        Cell(32),
        Dense(16, activation="relu"),
        Dense(1),
    ])
    model.compile(optimizer="adam", loss="mse")
    model.fit(
        X[:cut], y[:cut], validation_split=.15, epochs=epochs, batch_size=16, verbose=0,
        callbacks=[EarlyStopping(patience=5, restore_best_weights=True)],
    )

    test = model.predict(X[cut:], verbose=0)
    actual = scaler.inverse_transform(y[cut:]).ravel()
    predicted = scaler.inverse_transform(test).ravel()
    mae = float(mean_absolute_error(actual, predicted))
    rmse = float(mean_squared_error(actual, predicted) ** .5)

    window = s[-lookback:].reshape(1, lookback, 1)
    forecasts = []
    for _ in range(horizon):
        nxt = model.predict(window, verbose=0)[0, 0]
        forecasts.append(nxt)
        window = np.concatenate([window[:, 1:, :], np.array(nxt).reshape(1, 1, 1)], axis=1)
    prices = scaler.inverse_transform(np.array(forecasts).reshape(-1, 1)).ravel()

    cursor = pd.Timestamp(df.index[-1]).date()
    dates = []
    while len(dates) < horizon:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            dates.append(cursor)

    points = [
        {"date": d.isoformat(), "price": round(float(p), 4), "lower": round(float(p - 1.96 * rmse), 4), "upper": round(float(p + 1.96 * rmse), 4)}
        for d, p in zip(dates, prices)
    ]
    metrics = {"mae": round(mae, 4), "rmse": round(rmse, 4), "model": cell_type, "lookback": lookback, "epochs": epochs}
    return points, metrics
