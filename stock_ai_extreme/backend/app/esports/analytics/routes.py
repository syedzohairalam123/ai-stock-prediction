"""
Phase 21C §15 — the esports analytics API (`/api/v1/esports/...`).

Additive to the Phase 21A/21B routers: nothing under `/api/esports` changes.
Every identifier is validated against a strict allow-list pattern before it
reaches a provider (spec §21 — malformed IDs / injection), and every list
endpoint is paginated with an upper bound.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.esports.analytics.metrics import PLAYER_METRIC_SCHEMA
from app.esports.analytics.observability import esports_metrics
from app.esports.analytics.service import analytics_service
from app.esports.analytics.store import analytics_store
from app.esports.analytics.workers import ANOMALY_CACHE_KEY

logger = logging.getLogger("neural_market.esports.analytics.routes")

analytics_router = APIRouter(prefix="/api/v1/esports", tags=["esports-analytics"])

#: Provider identifiers are `game-team`-style slugs; anything else is rejected
#: before it can be interpolated into an upstream URL.
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ALLOWED_GAMES = {"cs2", "lol", "dota2"}


def _validate_id(value: str, label: str) -> str:
    if not ID_PATTERN.match(value or ""):
        raise HTTPException(400, f"Invalid {label}: must match [A-Za-z0-9._-], 1–64 chars.")
    return value


def _validate_game(game_id: Optional[str]) -> Optional[str]:
    if game_id is None:
        return None
    if game_id not in ALLOWED_GAMES:
        raise HTTPException(400, f"Unknown game_id. Expected one of {sorted(ALLOWED_GAMES)}.")
    return game_id


class InterestRequest(BaseModel):
    game_id: str = Field(..., min_length=2, max_length=32)
    match_id: Optional[str] = Field(default=None, max_length=64)
    kind: str = Field(default="view", pattern="^(view|search|follow)$")


@analytics_router.get("/analytics/engine")
async def get_analytics_engine():
    """The transparent contract: trending weights, signals and metric schemas."""
    return {
        "trending_weights": analytics_service.weights.as_dict(),
        "trending_signals": [
            {"key": "live", "label": "Live matches (this app's feed)"},
            {"key": "event", "label": "Events ingested (event velocity)"},
            {"key": "start_rate", "label": "Match start rate"},
            {"key": "search", "label": "Search velocity (app-recorded)"},
            {"key": "watchlist", "label": "Follows / watchlist adds (app-recorded)"},
            {"key": "viewer", "label": "Viewer count (only if a provider publishes one)"},
        ],
        "saturation": analytics_service.saturation,
        "min_sample": analytics_service.min_sample,
        "anomaly_z_threshold": analytics_service.z_threshold,
        "player_metric_schema": PLAYER_METRIC_SCHEMA,
        "note": "Weights are centralized here and in settings — never inside a UI component.",
    }


@analytics_router.get("/analytics/team/{team_id}")
async def analytics_team(team_id: str, game_id: Optional[str] = None):
    _validate_id(team_id, "team_id")
    _validate_game(game_id)
    try:
        return await analytics_service.get_team_analytics(team_id, game_id=game_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("team analytics failed for %s: %s", team_id, exc)
        raise HTTPException(500, "Team analytics unavailable.") from exc


@analytics_router.get("/analytics/player/{player_id}")
async def analytics_player(
    player_id: str,
    team_id: Optional[str] = None,
    game_id: Optional[str] = None,
):
    _validate_id(player_id, "player_id")
    if team_id:
        _validate_id(team_id, "team_id")
    _validate_game(game_id)
    try:
        payload = await analytics_service.get_player_analytics(
            player_id, team_id=team_id, game_id=game_id
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("player analytics failed for %s: %s", player_id, exc)
        raise HTTPException(500, "Player analytics unavailable.") from exc
    if payload is None:
        raise HTTPException(404, "Player not found in the analytics window.")
    return payload


@analytics_router.get("/analytics/match/{match_id}")
async def analytics_match(match_id: str):
    _validate_id(match_id, "match_id")
    try:
        payload = await analytics_service.get_match_analytics(match_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("match analytics failed for %s: %s", match_id, exc)
        raise HTTPException(500, "Match analytics unavailable.") from exc
    if payload is None:
        raise HTTPException(404, "Match not found.")
    return payload


@analytics_router.get("/trending/games")
async def trending_games():
    try:
        return await analytics_service.get_trending_games()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("trending games failed: %s", exc)
        raise HTTPException(500, "Trending games unavailable.") from exc


@analytics_router.get("/trending/matches")
async def trending_matches(
    game_id: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0, le=500),
):
    _validate_game(game_id)
    try:
        payload = await analytics_service.get_trending_matches(game_id=game_id, limit=limit + offset)
        page = payload.get("matches", [])[offset : offset + limit]
        return {**payload, "matches": page, "count": len(page), "limit": limit, "offset": offset}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("trending matches failed: %s", exc)
        raise HTTPException(500, "Trending matches unavailable.") from exc


@analytics_router.get("/data-quality")
async def data_quality(
    game_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    _validate_game(game_id)
    try:
        payload = await analytics_service.get_data_quality(game_id=game_id, limit=limit)
        payload["anomaly_scan"] = analytics_store.cache_get(ANOMALY_CACHE_KEY)
        return payload
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.error("data quality failed: %s", exc)
        raise HTTPException(500, "Data quality unavailable.") from exc


@analytics_router.get("/observability")
async def observability():
    try:
        return await analytics_service.get_observability()
    except Exception as exc:
        logger.error("observability failed: %s", exc)
        raise HTTPException(500, "Observability unavailable.") from exc


@analytics_router.get("/metrics/prometheus")
async def prometheus_metrics():
    """
    A minimal Prometheus-style text exposition of the same counters, so the
    observability data can be scraped without a JSON adapter.
    """
    try:
        payload = await analytics_service.get_observability()
    except Exception as exc:
        raise HTTPException(500, "Metrics unavailable.") from exc
    obs = payload.get("observability") or {}
    lines = [
        "# HELP esports_event_ingestion_rate_per_second Events ingested per second (rolling).",
        "# TYPE esports_event_ingestion_rate_per_second gauge",
        f"esports_event_ingestion_rate_per_second {obs.get('event_ingestion_rate_per_second', 0)}",
        "# HELP esports_connected_clients Active WebSocket clients.",
        "# TYPE esports_connected_clients gauge",
        f"esports_connected_clients {obs.get('connected_clients', 0) or 0}",
        "# HELP esports_error_rate_per_second Errors per second (rolling).",
        "# TYPE esports_error_rate_per_second gauge",
        f"esports_error_rate_per_second {obs.get('error_rate_per_second', 0)}",
    ]
    for name, summary in (obs.get("provider_latency_ms") or {}).items():
        safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if summary.get("p95") is not None:
            lines.append(f'esports_provider_latency_p95_ms{{provider="{safe}"}} {summary["p95"]}')
    ws = (obs.get("websocket_broadcast_latency_ms") or {})
    if ws.get("p95") is not None:
        lines.append(f'esports_ws_broadcast_latency_p95_ms {ws["p95"]}')
    return "\n".join(lines) + "\n"


@analytics_router.post("/interest")
async def record_interest(body: InterestRequest):
    """Record one real interest event (view/search/follow) for the trending engine."""
    if body.game_id not in ALLOWED_GAMES:
        raise HTTPException(400, f"Unknown game_id. Expected one of {sorted(ALLOWED_GAMES)}.")
    if body.match_id:
        _validate_id(body.match_id, "match_id")
    accepted = analytics_store.record_interest(body.game_id, body.kind, body.match_id)
    if not accepted:
        raise HTTPException(400, "Interest event rejected.")
    analytics_store.mark_dirty(body.game_id)
    return {"recorded": True, "kind": body.kind, "game_id": body.game_id, "totals": analytics_store.totals()}
