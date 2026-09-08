"""
Market regime detection (the honest slice of the old Phase 15 "3D analytics"
plus a genuinely advanced signal most hobby projects skip).

Classifies what kind of market an asset is currently in — trending-up,
trending-down, range-bound, or high-volatility chop — from real price
history, using two independent, explainable methods:

  1. ADX + directional movement (trend STRENGTH, from Phase 5 indicators)
  2. Return volatility vs its own history (compression vs stress)

Optional hidden Markov model (hmmlearn, a small optional dependency) gives a
statistically proper regime switch model; when it isn't installed, the
deterministic rule-based classifier still works and says so.

Pure computation on the indicator-enriched frames DataAgent already returns —
no network, no new hard dependency, fully testable with synthetic data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REGIMES = ("trending_up", "trending_down", "range_bound", "high_volatility")

REGIME_LABELS = {
    "trending_up": "Trending Up",
    "trending_down": "Trending Down",
    "range_bound": "Range-Bound",
    "high_volatility": "High-Volatility Chop",
}


def _annualized_vol(returns: pd.Series, window: int = 30) -> float:
    return float(returns.tail(window).std() * (252 ** 0.5))


def _vol_percentile(returns: pd.Series, window: int = 30, lookback: int = 252) -> float:
    """Where the current 30d vol sits vs the past year of itself (0-100)."""
    vol = returns.rolling(window).std() * (252 ** 0.5)
    history = vol.tail(lookback).dropna()
    current = history.iloc[-1] if len(history) else None
    if current is None or len(history) < 20:
        return 50.0
    return round(float((history < current).mean() * 100), 2)


def rule_based_regime(df: pd.DataFrame) -> dict:
    """Deterministic, explainable classifier. Every threshold used is visible
    in the response so no one has to trust a black box."""
    last = df.iloc[-1]
    close = float(last["Close"])
    rsi = float(last["rsi_14"]) if "rsi_14" in df.columns and pd.notna(last.get("rsi_14")) else None
    adx = float(last["adx_14"]) if "adx_14" in df.columns and pd.notna(last.get("adx_14")) else None
    plus_di = float(last["plus_di_14"]) if "plus_di_14" in df.columns and pd.notna(last.get("plus_di_14")) else None
    minus_di = float(last["minus_di_14"]) if "minus_di_14" in df.columns and pd.notna(last.get("minus_di_14")) else None

    returns = df["Close"].pct_change()
    vol_now = round(_annualized_vol(returns), 4)
    vol_pct = _vol_percentile(returns)
    sma_30 = float(last["sma_30"]) if "sma_30" in df.columns and pd.notna(last.get("sma_30")) else None

    # Direction: price vs its 30-day mean + DI crossover.
    above_mean = sma_30 is not None and close > sma_30
    di_bullish = plus_di is not None and minus_di is not None and plus_di > minus_di

    reasons: list[str] = []
    if adx is not None and adx > 25:
        regime = "trending_up" if (above_mean or di_bullish) else "trending_down"
        reasons.append(f"ADX {adx:.1f} > 25 (strong trend)")
        reasons.append("price above 30d mean / +DI > -DI" if regime == "trending_up" else "price below 30d mean / -DI > +DI")
    else:
        if vol_pct > 85:
            regime = "high_volatility"
            adx_txt = f"{adx:.1f}" if adx is not None else "n/a"
            reasons.append(f"volatility in the {vol_pct:.0f}th percentile of the past year (ADX {adx_txt} below trend threshold)")
        else:
            regime = "range_bound"
            reasons.append(f"ADX {adx:.1f} below 25 (weak trend)" if adx is not None else "no ADX data — trend strength unknown")
            reasons.append(f"volatility in the {vol_pct:.0f}th percentile — not stressed")
    if rsi is not None:
        reasons.append(f"RSI {rsi:.1f}")

    confidence = 0.6 if adx is not None and adx > 30 else 0.5 if adx is not None else 0.3
    return {
        "method": "rule_based",
        "regime": regime, "label": REGIME_LABELS[regime],
        "confidence": confidence,
        "signals": {
            "adx_14": round(adx, 2) if adx is not None else None,
            "rsi_14": round(rsi, 2) if rsi is not None else None,
            "price_vs_sma30": "above" if above_mean else "below" if sma_30 is not None else None,
            "di_signal": "bullish" if di_bullish else "bearish" if minus_di is not None else None,
            "annualized_vol_30d": vol_now,
            "vol_percentile_1y": vol_pct,
        },
        "reasoning": reasons,
    }


def hmm_regime(df: pd.DataFrame, n_states: int = 3) -> dict | None:
    """Optional statistical upgrade via hmmlearn. Returns None (never raises)
    when hmmlearn isn't installed or the data is too short — the rule-based
    answer above remains the always-available baseline."""
    try:
        from hmmlearn.hmm import GaussianHMM  # optional dependency
    except ImportError:
        return None

    returns = (df["Close"].pct_change().dropna().to_numpy()).reshape(-1, 1)
    if len(returns) < 120:
        return None
    try:
        model = GaussianHMM(n_components=n_states, covariance_type="full", n_iter=200, random_state=42)
        model.fit(returns)
        states = model.predict(returns)
    except Exception:
        return None

    # Rank states by their average return/volatility to give them honest names.
    stats = []
    for s in range(n_states):
        mask = states == s
        if mask.sum() < 5:
            return None  # a degenerate state assignment isn't worth labeling
        stats.append({
            "state": s, "days": int(mask.sum()),
            "mean_return": float(returns[mask].mean()),
            "vol": float(returns[mask].std()),
        })
    stats.sort(key=lambda x: x["mean_return"])
    names = ["bearish", "neutral", "bullish"] if n_states == 3 else [f"state_{i}" for i in range(n_states)]
    mapping = {s["state"]: names[i] for i, s in enumerate(stats)}
    current_state = int(states[-1])
    return {
        "method": "hmm_gaussian",
        "regime": mapping[current_state],
        "states": [{**s, "label": mapping[s["state"]]} for s in stats],
        "transition_matrix": np.round(model.transmat_, 4).tolist(),
        "note": "Hidden Markov model over daily returns; state labels assigned by ranked mean return.",
    }


def detect_regime(df: pd.DataFrame) -> dict:
    """Full regime report: rule-based always, HMM when available."""
    if df is None or df.empty or len(df) < 60:
        return {"status": "insufficient_data", "message": "Need at least 60 rows of price history.",
                "rule_based": None, "hmm": None}
    result = {"status": "ok", "rule_based": rule_based_regime(df), "hmm": hmm_regime(df)}
    rb = result["rule_based"]
    result["summary"] = f"{rb['label']} — {', '.join(rb['reasoning'])}."
    result["disclaimer"] = "Regime is a descriptive statistic of past price behavior, not a prediction."
    return result
