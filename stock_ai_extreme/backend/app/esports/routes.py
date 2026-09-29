"""
API routes for Phase 21A - Real-Time Esports Data Ingestion

This module provides FastAPI routes for esports data access.
Following the existing API patterns in the project.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.esports.providers.base import EsportsDataStatus, MatchStatus
from app.esports.services.manager import EsportsDataManager
from app.esports.services import feed as feed_service
from app.esports.websocket.manager import esports_ws_manager


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO date/datetime query value into an aware UTC datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(400, f"Invalid date: {value}. Use ISO format (YYYY-MM-DD).") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

logger = logging.getLogger("neural_market.esports.routes")

esports_router = APIRouter(prefix="/api/esports", tags=["esports"])

# Global data manager (will be configured in main.py)
esports_data_manager: Optional[EsportsDataManager] = None


def configure_esports(manager: EsportsDataManager):
    """Configure the esports system with the data manager."""
    global esports_data_manager
    esports_data_manager = manager
    logger.info("Esports system configured")


# Request/Response Models
class GameResponse(BaseModel):
    id: str
    external_id: str
    name: str
    short_name: str
    source: str
    metadata: dict


class TournamentResponse(BaseModel):
    id: str
    external_id: str
    name: str
    game_id: str
    start_date: str
    end_date: Optional[str] = None
    prize_pool: Optional[float] = None
    region: Optional[str] = None
    status: str
    metadata: dict


class MatchResponse(BaseModel):
    id: str
    external_id: str
    game_id: str
    tournament_id: str
    series_id: str
    status: str
    scheduled_at: str
    team_a_id: str
    team_b_id: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    best_of: int
    current_map: Optional[str] = None
    map_number: int
    score_a: int
    score_b: int
    winner_id: Optional[str] = None
    source: str
    source_timestamp: Optional[str] = None
    received_at: str
    metadata: dict


class TeamResponse(BaseModel):
    id: str
    external_id: str
    name: str
    short_name: str
    game_id: str
    logo_url: Optional[str] = None
    region: Optional[str] = None
    metadata: dict


class PlayerResponse(BaseModel):
    id: str
    external_id: str
    name: str
    handle: str
    team_id: str
    game_id: str
    role: Optional[str] = None
    country: Optional[str] = None
    metadata: dict


class LiveSnapshotResponse(BaseModel):
    match_id: str
    game_id: str
    status: str
    current_map: Optional[str] = None
    map_number: int
    score_a: int
    score_b: int
    team_a_id: str
    team_b_id: str
    current_map_scores: dict
    game_state: dict
    timestamp: str
    data_age_seconds: Optional[float] = None
    data_status: str


class HealthResponse(BaseModel):
    status: str
    providers: dict
    cache: dict
    websocket: dict


# Routes
@esports_router.get("/games")
async def get_games():
    """Get all supported esports games."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        games = await esports_data_manager.get_games()
        return {
            "games": [game.to_dict() for game in games],
            "count": len(games)
        }
    except Exception as e:
        logger.error(f"Failed to get games: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/games/{game_id}/tournaments")
async def get_tournaments(game_id: str):
    """Get tournaments for a specific game."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        tournaments = await esports_data_manager.get_tournaments(game_id)
        return {
            "tournaments": [tournament.to_dict() for tournament in tournaments],
            "count": len(tournaments)
        }
    except Exception as e:
        logger.error(f"Failed to get tournaments: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/games/{game_id}/matches")
async def get_matches(game_id: str, tournament_id: Optional[str] = None):
    """Get matches for a game, optionally filtered by tournament."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        matches = await esports_data_manager.get_matches(game_id, tournament_id)
        return {
            "matches": [match.to_dict() for match in matches],
            "count": len(matches)
        }
    except Exception as e:
        logger.error(f"Failed to get matches: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/matches/{match_id}")
async def get_match(match_id: str):
    """Get a specific match by ID."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        match = await esports_data_manager.get_match(match_id)
        if not match:
            raise HTTPException(404, f"Match {match_id} not found")
        
        return match.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get match: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/matches/{match_id}/live")
async def get_match_live(match_id: str):
    """Get live snapshot for a specific match."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        snapshot = await esports_data_manager.get_live_snapshot(match_id)
        if not snapshot:
            raise HTTPException(404, f"Live snapshot for match {match_id} not found")
        
        return snapshot.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get live snapshot: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/games/{game_id}/teams")
async def get_teams(game_id: str):
    """Get teams for a specific game."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        teams = await esports_data_manager.get_teams(game_id)
        return {
            "teams": [team.to_dict() for team in teams],
            "count": len(teams)
        }
    except Exception as e:
        logger.error(f"Failed to get teams: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/teams/{team_id}/players")
async def get_players(team_id: str):
    """Get players for a specific team."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    
    try:
        players = await esports_data_manager.get_players(team_id)
        return {
            "players": [player.to_dict() for player in players],
            "count": len(players)
        }
    except Exception as e:
        logger.error(f"Failed to get players: {e}")
        raise HTTPException(500, str(e))


# ---------------------------------------------------------------------------
# Phase 21B — additive read surface for the Esports Hub UI.
#
# Every route below is purely additive: the Phase 21A routes above are
# untouched. All values are provider-supplied; a field the source does not
# publish is ``null`` and the UI renders its labelled fallback.
# ---------------------------------------------------------------------------

@esports_router.get("/featured")
async def get_featured_match(game_id: Optional[str] = None):
    """The backend's featured-match ranking (§3). Never merely the first row."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        featured = await feed_service.featured_match(esports_data_manager, game_id)
        return {"featured": featured, "generated_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"Failed to compute featured match: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/matches")
async def list_matches(
    game_id: Optional[str] = None,
    status: Optional[List[str]] = Query(None),
    live: bool = False,
    upcoming: bool = False,
    tournament_id: Optional[str] = None,
    region: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Cross-game match feed with server-side filtering (§6, §24)."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    statuses: List[str] = []
    for raw in status or []:
        statuses.extend(part.strip().upper() for part in raw.split(",") if part.strip())
    filters = {
        "game": game_id,
        "statuses": statuses or None,
        "live": live,
        "upcoming": upcoming,
        "tournament_id": tournament_id,
        "region": region,
        "q": q,
        "date_from": _parse_dt(date_from),
        "date_to": _parse_dt(date_to),
    }
    try:
        return await feed_service.build_feed(esports_data_manager, filters, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"Failed to build match feed: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/matches/{match_id}/detail")
async def get_match_detail(match_id: str):
    """Full live-match page payload: teams, players, events, snapshot, sources."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        detail = await feed_service.match_detail(esports_data_manager, match_id)
        if detail is None:
            raise HTTPException(404, f"Match {match_id} not found")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get match detail: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/matches/{match_id}/events")
async def get_match_events_route(match_id: str):
    """Live match events (§8): timestamped, sequenced, deduplicated."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        events = await esports_data_manager.get_match_events(match_id)
        return {
            "match_id": match_id,
            "events": [event.to_dict() for event in events],
            "count": len(events),
        }
    except Exception as e:
        logger.error(f"Failed to get match events: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/tournaments/{tournament_id}")
async def get_tournament(tournament_id: str):
    """One tournament plus its real related matches (§14)."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        detail = await feed_service.tournament_detail(esports_data_manager, tournament_id)
        if detail is None:
            raise HTTPException(404, f"Tournament {tournament_id} not found")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tournament: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/games/summary")
async def get_games_summary():
    """Per-game activity counts for the hub category cards (§5)."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        return await feed_service.game_summary(esports_data_manager)
    except Exception as e:
        logger.error(f"Failed to get games summary: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/games/{game_id}/summary")
async def get_game_summary(game_id: str):
    """Per-game activity counts for a single game."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        return await feed_service.game_summary(esports_data_manager, game_id)
    except Exception as e:
        logger.error(f"Failed to get game summary: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/sources")
async def get_sources():
    """Per-provider data-source status for the data-source panel (§15)."""
    if not esports_data_manager:
        raise HTTPException(503, "Esports data manager not configured")
    try:
        providers = await esports_data_manager.provider_health_report()
        return {"providers": providers, "count": len(providers)}
    except Exception as e:
        logger.error(f"Failed to get provider health: {e}")
        raise HTTPException(500, str(e))


@esports_router.get("/health")
async def esports_health():
    """Get esports system health status."""
    if not esports_data_manager:
        return {
            "status": "not_configured",
            "message": "Esports data manager not configured"
        }
    
    try:
        stats = esports_data_manager.get_stats()
        providers = await esports_data_manager.provider_health_report()
        overall = "ok"
        if providers and all(p.get("status") == "DOWN" for p in providers):
            overall = "degraded"
        return {
            "status": overall,
            "providers": providers,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Failed to get health status: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@esports_router.websocket("/ws/{client_id}")
async def esports_websocket(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time esports data."""
    await esports_ws_manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            # Handle different message types
            message_type = data.get("type")
            
            if message_type == "subscribe":
                # Phase 21B: a client may subscribe to one match, one game's
                # events, or the cross-game firehose that feeds the ticker.
                match_id = data.get("match_id")
                game_id = data.get("game_id")
                channel = data.get("channel")
                if match_id:
                    await esports_data_manager.subscribe_to_match(match_id, client_id)
                elif game_id:
                    await esports_data_manager.subscribe_to_game(game_id, client_id)
                elif channel == "all" or data.get("all"):
                    await esports_data_manager.subscribe_to_all(client_id)
            
            elif message_type == "unsubscribe":
                match_id = data.get("match_id")
                if match_id:
                    await esports_data_manager.unsubscribe_from_match(match_id, client_id)
            
            elif message_type == "snapshot":
                # Phase 21B §17: an explicit snapshot request lets a client
                # recover cleanly after a reconnect instead of applying missed
                # events to stale local state.
                match_id = data.get("match_id")
                if match_id:
                    snapshot = await esports_data_manager.get_live_snapshot(match_id)
                    await esports_ws_manager.send_personal_message(client_id, {
                        "type": "snapshot",
                        "channel": f"esports:match:{match_id}",
                        "data": snapshot.to_dict() if snapshot else None,
                        "requested": True,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            
            elif message_type == "ping":
                await esports_ws_manager.send_personal_message(client_id, {
                    "type": "pong",
                    "timestamp": datetime.utcnow().isoformat(),
                })
            
            elif message_type == "pong":
                await esports_ws_manager.handle_pong(client_id)
            
            else:
                logger.warning(f"Unknown message type: {message_type}")
    
    except WebSocketDisconnect:
        await esports_ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
        await esports_ws_manager.disconnect(client_id)
