"""
Phase 21C — Advanced Esports Analytics, Trending Engine and Production QA.

Layers on top of Phase 21A (ingestion/state/WebSocket) and 21B (the hub UI)
without changing either:

- ``metrics``             descriptive analytics (team form, map/player/duration,
                         score progression, event frequency, anomaly detection)
- ``trending``            the weighted trending engine (centralized weights)
- ``data_quality``        the DataQualityEngine (HIGH/MEDIUM/LOW)
- ``source_consistency``  SOURCE DISCREPANCY detection
- ``store``               bounded interest signals + aggregate cache + dirty set
- ``observability``       latency/rate/client metrics with percentiles
- ``service``             orchestration + caching + incremental maintenance
- ``workers``             background analytics jobs (never on the live path)
- ``routes``              the additive ``/api/v1/esports`` API
"""

from .metrics import (
    ANOMALY_LABEL,
    calculate_event_frequency,
    calculate_historical_consistency,
    calculate_map_analytics,
    calculate_match_duration_stats,
    calculate_score_progression,
    calculate_series_win_rate,
    calculate_team_form,
    player_analytics,
    zscore_anomalies,
)
from .trending import TrendingGameEngine, TrendingWeights, calculate_trending_score
from .data_quality import DataQualityEngine, aggregate_quality, evaluate_data_quality
from .source_consistency import detect_discrepancies
from .service import analytics_service, configure
from .routes import analytics_router

__all__ = [
    "ANOMALY_LABEL",
    "calculate_event_frequency",
    "calculate_historical_consistency",
    "calculate_map_analytics",
    "calculate_match_duration_stats",
    "calculate_score_progression",
    "calculate_series_win_rate",
    "calculate_team_form",
    "player_analytics",
    "zscore_anomalies",
    "TrendingGameEngine",
    "TrendingWeights",
    "calculate_trending_score",
    "DataQualityEngine",
    "evaluate_data_quality",
    "aggregate_quality",
    "detect_discrepancies",
    "analytics_service",
    "configure",
    "analytics_router",
]
