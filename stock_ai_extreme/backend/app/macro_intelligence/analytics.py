"""
Phase 23A — Python analytics for macro intelligence.

Provides statistical analysis using pandas, numpy, scipy, and statsmodels:
- Rate change history analysis
- Macro trend analysis with rolling averages
- Event-window analysis for market reactions
- Historical regime comparison

All calculations are based on real data. No unsupported economic conclusions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger("neural_market.macro_intelligence.analytics")


@dataclass
class PolicyRateAnalytics:
    """Analytics for policy rate history."""

    total_decisions: int = 0
    hikes: int = 0
    cuts: int = 0
    unchanged: int = 0
    avg_hike_bps: float = 0.0
    avg_cut_bps: float = 0.0
    max_hike_bps: int = 0
    max_cut_bps: int = 0
    current_rate: Optional[float] = None
    rate_range_min: Optional[float] = None
    rate_range_max: Optional[float] = None
    total_bps_change: int = 0
    volatility_bps: float = 0.0  # Standard deviation of rate changes


@dataclass
class MacroTrendAnalytics:
    """Analytics for macro indicator trends."""

    series_id: str = ""
    trend: str = "unknown"  # increasing, decreasing, stable, volatile
    latest_value: float = 0.0
    previous_value: float = 0.0
    change_pct: float = 0.0
    rolling_avg_3m: Optional[float] = None
    rolling_avg_6m: Optional[float] = None
    rolling_avg_12m: Optional[float] = None
    volatility: float = 0.0  # Standard deviation
    momentum: float = 0.0  # Recent momentum score


@dataclass
class EventWindowAnalysis:
    """Market reaction analysis around policy decisions."""

    decision_date: Optional[datetime] = None
    market_ticker: Optional[str] = None
    pre_event_avg: Optional[float] = None
    post_event_avg: Optional[float] = None
    change_1d: Optional[float] = None
    change_3d: Optional[float] = None
    change_5d: Optional[float] = None
    change_10d: Optional[float] = None
    change_20d: Optional[float] = None
    pre_volatility: Optional[float] = None
    post_volatility: Optional[float] = None
    #: Phase 23B spec §7 — the *sessions* each observation is anchored to, so a
    #: consumer can see exactly which trading days a window return spans.
    decision_session: Optional[str] = None      # trading session used as the anchor
    pre_session: Optional[str] = None           # session immediately before the anchor
    window_end_sessions: Optional[dict] = None  # {"window_5d": "YYYY-MM-DD"}


def analyze_policy_rates(decisions: list[dict]) -> PolicyRateAnalytics:
    """Analyze historical policy rate decisions.

    Args:
        decisions: List of policy decision dictionaries with:
            - new_rate: float
            - previous_rate: float
            - change_bps: int
            - direction: str (HIKE, CUT, UNCHANGED)
            - decision_timestamp: str (ISO format)

    Returns:
        PolicyRateAnalytics with comprehensive statistics.
    """
    if not decisions:
        return PolicyRateAnalytics()

    df = pd.DataFrame(decisions)

    if df.empty:
        return PolicyRateAnalytics()

    # Convert timestamps
    df["decision_timestamp"] = pd.to_datetime(df["decision_timestamp"])
    df = df.sort_values("decision_timestamp")

    # Count by direction
    hikes = len(df[df["direction"] == "HIKE"])
    cuts = len(df[df["direction"] == "CUT"])
    unchanged = len(df[df["direction"] == "UNCHANGED"])

    # Calculate average bps changes
    hike_bps = df[df["direction"] == "HIKE"]["change_bps"]
    cut_bps = df[df["direction"] == "CUT"]["change_bps"]

    avg_hike_bps = float(hike_bps.mean()) if not hike_bps.empty else 0.0
    avg_cut_bps = float(cut_bps.mean()) if not cut_bps.empty else 0.0
    max_hike_bps = int(hike_bps.max()) if not hike_bps.empty else 0
    max_cut_bps = int(cut_bps.min()) if not cut_bps.empty else 0  # Most negative cut

    # Current rate and range. The frame is sorted ASCENDING by timestamp, so
    # the newest decision is the LAST row — `current_rate` must be the most
    # recent verified setting, never the oldest (a real order-dependent bug:
    # it silently reported the stale rate whenever input arrived oldest-first,
    # and the reverse whenever it arrived newest-first).
    current_rate = float(df.iloc[-1]["new_rate"]) if not df.empty else None
    rate_range_min = float(df["new_rate"].min()) if not df.empty else None
    rate_range_max = float(df["new_rate"].max()) if not df.empty else None

    # Total bps change over the period: newest minus oldest, always.
    if len(df) >= 2:
        oldest_rate = float(df.iloc[0]["new_rate"])
        newest_rate = float(df.iloc[-1]["new_rate"])
        total_bps_change = int(round((newest_rate - oldest_rate) * 100))
    else:
        total_bps_change = 0

    # Volatility (standard deviation of rate changes)
    volatility_bps = float(df["change_bps"].std()) if len(df) > 1 else 0.0

    return PolicyRateAnalytics(
        total_decisions=len(df),
        hikes=hikes,
        cuts=cuts,
        unchanged=unchanged,
        avg_hike_bps=avg_hike_bps,
        avg_cut_bps=avg_cut_bps,
        max_hike_bps=max_hike_bps,
        max_cut_bps=max_cut_bps,
        current_rate=current_rate,
        rate_range_min=rate_range_min,
        rate_range_max=rate_range_max,
        total_bps_change=total_bps_change,
        volatility_bps=volatility_bps,
    )


def analyze_macro_trend(
    observations: list[dict],
    series_id: str = "",
    window_3m: int = 90,
    window_6m: int = 180,
    window_12m: int = 360,
) -> MacroTrendAnalytics:
    """Analyze macro indicator trend with rolling averages.

    Args:
        observations: List of macro series observations with:
            - observation_date: str (ISO format)
            - value: float
        series_id: Series identifier
        window_3m: 3-month window in days
        window_6m: 6-month window in days
        window_12m: 12-month window in days

    Returns:
        MacroTrendAnalytics with trend classification and statistics.
    """
    if not observations:
        return MacroTrendAnalytics(series_id=series_id)

    df = pd.DataFrame(observations)

    if df.empty or len(df) < 2:
        return MacroTrendAnalytics(series_id=series_id)

    # Convert dates and sort
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df = df.sort_values("observation_date").reset_index(drop=True)

    # Calculate change percentage
    latest_value = float(df.iloc[-1]["value"])
    previous_value = float(df.iloc[-2]["value"])
    change_pct = ((latest_value - previous_value) / previous_value * 100) if previous_value != 0 else 0.0

    # Calculate rolling averages if enough data
    rolling_avg_3m = None
    rolling_avg_6m = None
    rolling_avg_12m = None

    if len(df) >= window_3m:
        rolling_avg_3m = float(df.tail(window_3m)["value"].mean())
    if len(df) >= window_6m:
        rolling_avg_6m = float(df.tail(window_6m)["value"].mean())
    if len(df) >= window_12m:
        rolling_avg_12m = float(df.tail(window_12m)["value"].mean())

    # Volatility (standard deviation)
    volatility = float(df["value"].std()) if len(df) > 1 else 0.0

    # Momentum (recent 30-day change vs 90-day average)
    momentum = 0.0
    if len(df) >= 90:
        recent_30d = float(df.tail(30)["value"].mean())
        avg_90d = float(df.tail(90)["value"].mean())
        momentum = ((recent_30d - avg_90d) / avg_90d * 100) if avg_90d != 0 else 0.0

    # Classify trend
    trend = "stable"
    if abs(change_pct) < 0.5:
        trend = "stable"
    elif change_pct > 0:
        trend = "increasing"
    else:
        trend = "decreasing"

    # Check for volatility
    if volatility > (latest_value * 0.05) if latest_value != 0 else False:
        trend = "volatile"

    return MacroTrendAnalytics(
        series_id=series_id,
        trend=trend,
        latest_value=latest_value,
        previous_value=previous_value,
        change_pct=change_pct,
        rolling_avg_3m=rolling_avg_3m,
        rolling_avg_6m=rolling_avg_6m,
        rolling_avg_12m=rolling_avg_12m,
        volatility=volatility,
        momentum=momentum,
    )


def analyze_event_window(
    market_data: list[dict],
    decision_date: datetime,
    windows: list[int] = [1, 3, 5, 10, 20],
) -> EventWindowAnalysis:
    """Analyze market reaction around a policy decision.

    Args:
        market_data: List of market price data with:
            - date: str (ISO format)
            - close: float (closing price)
        decision_date: Decision timestamp
        windows: Event windows in days to analyze

    Returns:
        EventWindowAnalysis with pre/post event statistics.

    Note: This requires sufficient market data around the decision date.
    Clearly labeled as historical observation, not causation claim.
    """
    if not market_data:
        return EventWindowAnalysis(decision_date=decision_date)

    df = pd.DataFrame(market_data)

    if df.empty:
        return EventWindowAnalysis(decision_date=decision_date)

    # Convert dates
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Find decision date in data
    decision_idx = df[df["date"] == decision_date].index

    if len(decision_idx) == 0:
        # Find closest date
        decision_idx = df[df["date"] <= decision_date].tail(1).index

    if len(decision_idx) == 0:
        return EventWindowAnalysis(decision_date=decision_date)

    decision_idx = decision_idx[0]

    # Pre-event window (20 days before)
    pre_start = max(0, decision_idx - 20)
    pre_data = df.iloc[pre_start:decision_idx]

    # Post-event window (20 days after)
    post_end = min(len(df), decision_idx + 21)
    post_data = df.iloc[decision_idx:post_end]

    pre_event_avg = float(pre_data["close"].mean()) if not pre_data.empty else None
    post_event_avg = float(post_data["close"].mean()) if not post_data.empty else None

    # Calculate changes for each window, recording the closing session each
    # window lands on so the observation is fully traceable (spec §7).
    changes = {}
    window_end_sessions: dict[str, str] = {}
    for window in windows:
        post_end_idx = min(len(df), decision_idx + window + 1)
        window_data = df.iloc[decision_idx:post_end_idx]

        if not window_data.empty and not pre_data.empty:
            pre_price = float(pre_data.iloc[-1]["close"])
            post_price = float(window_data.iloc[-1]["close"])
            change_pct = ((post_price - pre_price) / pre_price * 100) if pre_price != 0 else 0.0
            changes[f"change_{window}d"] = change_pct
            window_end_sessions[f"window_{window}d"] = pd.Timestamp(
                window_data.iloc[-1]["date"]
            ).date().isoformat()

    # Volatility before and after
    pre_volatility = float(pre_data["close"].std()) if len(pre_data) > 1 else None
    post_volatility = float(post_data["close"].std()) if len(post_data) > 1 else None

    return EventWindowAnalysis(
        decision_date=decision_date,
        pre_event_avg=pre_event_avg,
        post_event_avg=post_event_avg,
        change_1d=changes.get("change_1d"),
        change_3d=changes.get("change_3d"),
        change_5d=changes.get("change_5d"),
        change_10d=changes.get("change_10d"),
        change_20d=changes.get("change_20d"),
        pre_volatility=pre_volatility,
        post_volatility=post_volatility,
        decision_session=pd.Timestamp(df.iloc[decision_idx]["date"]).date().isoformat(),
        pre_session=(
            pd.Timestamp(df.iloc[decision_idx - 1]["date"]).date().isoformat()
            if decision_idx > 0
            else None
        ),
        window_end_sessions=window_end_sessions or None,
    )


def compare_historical_regimes(
    decisions: list[dict],
    macro_data: dict[str, list[dict]],
) -> dict:
    """Compare macro regimes across historical periods.

    Args:
        decisions: Policy decision history
        macro_data: Dict mapping series_id to observations

    Returns:
        Dictionary with regime comparison statistics.

    Note: This is for historical observation only, not forecasting.
    """
    if not decisions or not macro_data:
        return {"error": "Insufficient data for regime comparison"}

    # Group decisions by rate direction periods
    df = pd.DataFrame(decisions)
    df["decision_timestamp"] = pd.to_datetime(df["decision_timestamp"])
    df = df.sort_values("decision_timestamp")

    # Identify rate cycles (hiking vs cutting cycles)
    regimes = []
    current_regime = None
    start_date = None

    for _, row in df.iterrows():
        direction = row["direction"]
        date = row["decision_timestamp"]

        if current_regime != direction:
            if current_regime is not None:
                regimes.append({
                    "regime": current_regime,
                    "start_date": start_date,
                    "end_date": date,
                    "duration_days": (date - start_date).days,
                })
            current_regime = direction
            start_date = date

    # Add final regime
    if current_regime is not None:
        regimes.append({
            "regime": current_regime,
            "start_date": start_date,
            "end_date": df.iloc[-1]["decision_timestamp"],
            "duration_days": (df.iloc[-1]["decision_timestamp"] - start_date).days,
        })

    # Calculate macro averages for each regime
    regime_comparison = []
    for regime in regimes:
        regime_macros = {}
        for series_id, observations in macro_data.items():
            obs_df = pd.DataFrame(observations)
            obs_df["observation_date"] = pd.to_datetime(obs_df["observation_date"])

            # Filter observations within regime period
            mask = (obs_df["observation_date"] >= regime["start_date"]) & \
                   (obs_df["observation_date"] <= regime["end_date"])
            regime_obs = obs_df[mask]

            if not regime_obs.empty:
                regime_macros[series_id] = {
                    "avg_value": float(regime_obs["value"].mean()),
                    "min_value": float(regime_obs["value"].min()),
                    "max_value": float(regime_obs["value"].max()),
                    "volatility": float(regime_obs["value"].std()),
                }

        regime_comparison.append({
            **regime,
            "macro_indicators": regime_macros,
        })

    return {
        "regimes": regime_comparison,
        "total_regimes": len(regimes),
        "note": "Historical observation only, not predictive",
    }


def calculate_rate_change_correlation(
    rate_decisions: list[dict],
    macro_series: list[dict],
    lag_days: int = 30,
) -> dict:
    """Calculate correlation between rate changes and macro indicators.

    Args:
        rate_decisions: Policy decision history
        macro_series: Macro indicator observations
        lag_days: Days to lag macro data behind rate changes

    Returns:
        Dictionary with correlation statistics.

    Note: Correlation does not imply causation. This is historical analysis.
    """
    if not rate_decisions or not macro_series:
        return {"error": "Insufficient data for correlation analysis"}

    # Build time series of rate changes
    rate_df = pd.DataFrame(rate_decisions)
    rate_df["decision_timestamp"] = pd.to_datetime(rate_df["decision_timestamp"])
    rate_df = rate_df.sort_values("decision_timestamp")

    # Build time series of macro data
    macro_df = pd.DataFrame(macro_series)
    macro_df["observation_date"] = pd.to_datetime(macro_df["observation_date"])
    macro_df = macro_df.sort_values("observation_date")

    # Merge on dates with lag
    rate_df["merge_date"] = rate_df["decision_timestamp"] + timedelta(days=lag_days)
    merged = pd.merge(
        rate_df[["merge_date", "change_bps"]],
        macro_df[["observation_date", "value"]],
        left_on="merge_date",
        right_on="observation_date",
        how="inner"
    )

    if len(merged) < 10:
        return {"error": "Insufficient overlapping data points"}

    # Calculate correlation
    correlation, p_value = stats.pearsonr(merged["change_bps"], merged["value"])

    return {
        "correlation": float(correlation),
        "p_value": float(p_value),
        "sample_size": len(merged),
        "lag_days": lag_days,
        "interpretation": _interpretate_correlation(correlation, p_value),
    }


def _interpretate_correlation(correlation: float, p_value: float) -> str:
    """Interpret correlation coefficient and p-value."""
    if p_value > 0.05:
        return "Not statistically significant"

    abs_corr = abs(correlation)
    if abs_corr < 0.3:
        strength = "weak"
    elif abs_corr < 0.7:
        strength = "moderate"
    else:
        strength = "strong"

    direction = "positive" if correlation > 0 else "negative"
    return f"{strength} {direction} correlation (statistically significant)"
