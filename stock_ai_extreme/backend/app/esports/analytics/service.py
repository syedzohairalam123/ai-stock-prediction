"""
Phase 21C §13, §15, §16 — analytics orchestration.

Binds the Phase 21A data manager to the analytics engine and exposes the
JSON-ready payloads the API returns. Everything expensive is cached with a TTL,
and a match completion / live event only marks the affected game **dirty** —
so real-time WebSocket delivery never waits on a historical recomputation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.esports.analytics import metrics, source_consistency, trending
from app.esports.analytics.data_quality import aggregate_quality, evaluate_data_quality
from app.esports.analytics.observability import esports_metrics
from app.esports.analytics.store import analytics_store
from app.esports.providers.base import Match, MatchStatus
from app.esports.services import feed as feed_service

logger = logging.getLogger("neural_market.esports.analytics.service")


class EsportsAnalyticsService:
    def __init__(self) -> None:
        self._manager: Any = None
        self.weights = trending.TrendingWeights.from_settings(settings)
        self.saturation = float(getattr(settings, "esports_trend_saturation", 25.0))
        self.history_limit = int(getattr(settings, "esports_analytics_history_limit", 200))
        self.min_sample = int(getattr(settings, "esports_analytics_min_sample", 3))
        self.cache_ttl = float(getattr(settings, "esports_analytics_cache_ttl_seconds", 120))
        self.trending_ttl = float(getattr(settings, "esports_trending_cache_ttl_seconds", 60))
        self.event_window = int(getattr(settings, "esports_event_window_seconds", 120))
        self.z_threshold = float(getattr(settings, "esports_anomaly_z_threshold", 3.0))
        self.engine = trending.TrendingGameEngine(self.weights, saturation=self.saturation)

    # ------------------------------------------------------------------ wiring
    def configure(self, manager: Any) -> None:
        self._manager = manager
        logger.info("Esports analytics service configured (trending weights=%s)", self.weights.as_dict())

    @property
    def manager(self) -> Any:
        if self._manager is None:
            raise RuntimeError("Esports analytics service is not configured with a data manager.")
        return self._manager

    # ------------------------------------------------------------------ helpers
    async def _matches(self, game_id: Optional[str] = None) -> List[Match]:
        matches = await feed_service.gather_matches(self.manager, game_id)
        if self.history_limit and len(matches) > self.history_limit:
            matches = sorted(matches, key=lambda m: m.scheduled_at or datetime.min, reverse=True)[: self.history_limit]
        return matches

    async def _providers(self) -> List[Dict[str, Any]]:
        try:
            return await self.manager.provider_health_report()
        except Exception:  # a health failure must not blank analytics
            return []

    def _cached(self, key: str, ttl: float):
        return analytics_store.cache_get(key), analytics_store.cache_get_stale(key)

    # ==================================================================
    # §1–§4, §15 — team analytics
    # ==================================================================
    async def get_team_analytics(self, team_id: str, *, game_id: Optional[str] = None) -> Dict[str, Any]:
        key = f"team:{game_id or 'all'}:{team_id}"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}
        matches = await self._matches(game_id)
        providers = await self._providers()
        team_matches = metrics.team_games(matches, team_id, finished_only=False)

        form = metrics.calculate_team_form(matches, team_id, min_sample=self.min_sample)
        series = metrics.calculate_series_win_rate(matches, team_id, min_sample=self.min_sample)
        maps = metrics.calculate_map_analytics(matches, team_id, min_sample=self.min_sample)
        durations = metrics.calculate_match_duration_stats(matches, team_id, min_sample=self.min_sample)
        progression = metrics.calculate_score_progression(matches, team_id, min_sample=self.min_sample)

        margins = [
            metrics._team_score(m, team_id) - metrics._opp_score(m, team_id)
            for m in metrics.team_games(matches, team_id)
        ]
        consistency = metrics.calculate_historical_consistency(margins)

        quality = [
            evaluate_data_quality(m, providers=providers, now=datetime.now(timezone.utc))
            for m in team_matches[:25]
        ]
        payload = {
            "team_id": team_id,
            "game_id": game_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sample_size": len(team_matches),
            "date_range": metrics._date_range(team_matches),
            "sources": metrics._sources(team_matches),
            "form": form,
            "series_win_rate": series,
            "map_analytics": maps,
            "duration": durations,
            "score_progression": progression,
            "historical_consistency": {
                "value": consistency,
                "sample_size": len(margins),
                "date_range": metrics._date_range(metrics.team_games(matches, team_id)),
                "sources": metrics._sources(matches),
                "data_quality": metrics.quality_label(len(margins), self.min_sample),
            },
            "data_quality": aggregate_quality(quality),
            "source_consistency": source_consistency.detect_discrepancies(team_matches),
            "cache": "miss",
        }
        analytics_store.cache_set(key, payload, self.cache_ttl)
        return payload

    # ==================================================================
    # §5, §15 — player analytics
    # ==================================================================
    async def get_player_analytics(
        self, player_id: str, *, team_id: Optional[str] = None, game_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Player metrics, resolved from a bounded, cached search.

        The provider interfaces have no global player index, so when the caller
        does not supply the team the search is limited to the teams playing the
        most recent matches — a bounded, disclosed scan rather than a crawl of
        every team in the database.
        """
        key = f"player:{game_id or 'all'}:{player_id}:{team_id or '-'}"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}

        candidates: List[str] = []
        if team_id:
            candidates = [team_id]
        else:
            matches = await self._matches(game_id)
            seen: List[str] = []
            for match in sorted(matches, key=lambda m: m.scheduled_at or datetime.min, reverse=True):
                for candidate in (match.team_a_id, match.team_b_id):
                    if candidate not in seen:
                        seen.append(candidate)
                if len(seen) >= 24:
                    break
            candidates = seen[:24]

        found_players = []
        resolved_team: Optional[str] = None
        resolved_game: Optional[str] = game_id
        for candidate in candidates:
            try:
                players = await self.manager.get_players(candidate)
            except Exception:
                continue
            for player in players:
                if player.id == player_id or player.external_id == player_id:
                    found_players = [player]
                    resolved_team = candidate
                    resolved_game = player.game_id
                    break
            if found_players:
                break

        if not found_players:
            return None

        analytics = metrics.player_analytics(found_players, resolved_game or "unknown", min_sample=1)
        payload = {
            "player_id": player_id,
            "team_id": resolved_team,
            "game_id": resolved_game,
            "scanned_teams": len(candidates),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **analytics,
            "cache": "miss",
        }
        analytics_store.cache_set(key, payload, self.cache_ttl)
        return payload

    # ==================================================================
    # §10, §15 — match analytics (with anomaly detection)
    # ==================================================================
    async def get_match_analytics(self, match_id: str) -> Optional[Dict[str, Any]]:
        key = f"match:{match_id}"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}
        match = await self.manager.get_match(match_id)
        if match is None:
            return None
        events = await self.manager.get_match_events(match_id)
        providers = await self._providers()
        now = datetime.now(timezone.utc)

        # Event-interval analysis: gaps between consecutive events, in seconds.
        ordered = sorted(events, key=lambda e: e.sequence)
        intervals: List[float] = []
        for previous, current in zip(ordered, ordered[1:]):
            delta = (current.timestamp - previous.timestamp).total_seconds()
            if delta >= 0:
                intervals.append(delta)
        event_anomalies = metrics.zscore_anomalies(
            intervals,
            z_threshold=self.z_threshold,
            labels=[f"{ordered[i + 1].type.value}@{ordered[i + 1].sequence}" for i in range(len(ordered) - 1)],
            method="zscore_event_interval",
        )
        event_frequency = metrics.calculate_event_frequency(events, min_sample=self.min_sample)

        duration_series = [
            float(g.get("duration"))
            for g in (match.meta_data or {}).get("games") or []
            if isinstance(g.get("duration"), (int, float)) and g.get("duration")
        ]
        duration_anomalies = metrics.zscore_anomalies(
            duration_series, z_threshold=self.z_threshold, method="zscore_duration"
        )

        # Multivariate view when the sample justifies IsolationForest.
        feature_rows = []
        for game in (match.meta_data or {}).get("games") or []:
            row = [game.get("duration"), game.get("team_a_score"), game.get("team_b_score")]
            if all(isinstance(v, (int, float)) for v in row):
                feature_rows.append(row)
        isolation = metrics.isolation_forest_anomalies(feature_rows)

        anomalies = [*event_anomalies.get("anomalies", []), *duration_anomalies.get("anomalies", []),
                     *isolation.get("anomalies", [])]

        team_a_analytics = await self.get_team_analytics(match.team_a_id, game_id=match.game_id)
        team_b_analytics = await self.get_team_analytics(match.team_b_id, game_id=match.game_id)

        payload = {
            "match_id": match_id,
            "game_id": match.game_id,
            "generated_at": now.isoformat(),
            "status": match.status.value if isinstance(match.status, MatchStatus) else str(match.status),
            "event_frequency": event_frequency,
            "duration_stats": metrics.calculate_match_duration_stats([match], min_sample=1),
            "anomaly_detection": {
                "label": metrics.ANOMALY_LABEL if anomalies else "NO ANOMALY",
                "count": len(anomalies),
                "findings": anomalies,
                "checks": {
                    "event_interval": event_anomalies,
                    "duration": duration_anomalies,
                    "multivariate": isolation,
                },
                "note": "Descriptive only — a flagged value is unusual for this sample, not an explanation.",
            },
            "team_a": {"team_id": match.team_a_id, "form": team_a_analytics["form"]},
            "team_b": {"team_id": match.team_b_id, "form": team_b_analytics["form"]},
            "data_quality": evaluate_data_quality(match, events=events, providers=providers, now=now),
            "source_consistency": source_consistency.detect_discrepancies([match]),
            "cache": "miss",
        }
        analytics_store.cache_set(key, payload, self.cache_ttl)
        return payload

    # ==================================================================
    # §6–§9, §15 — trending
    # ==================================================================
    async def get_trending_games(self) -> Dict[str, Any]:
        key = "trending:games"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}

        games = await self.manager.get_games()
        interest = analytics_store.interest_counts(self.event_window * 30)
        observed_by_game = analytics_store.event_counts_by_game()
        rows: List[Dict[str, Any]] = []
        for game in games:
            try:
                matches = await self.manager.get_matches(game.id)
            except Exception:
                matches = []
            live = sum(
                1 for m in matches
                if (m.status.value if isinstance(m.status, MatchStatus) else str(m.status))
                in (MatchStatus.LIVE.value, MatchStatus.PAUSED.value, MatchStatus.MAP_BREAK.value)
            )
            starts = 0
            for match in matches:
                counts = analytics_store.start_counts()
                starts += counts.get(match.id, 0)
            bucket = interest.get(game.id, {})
            rows.append(
                {
                    "game_id": game.id,
                    "name": game.name,
                    "short_name": game.short_name,
                    "live_match_count": live,
                    "event_count_window": int(observed_by_game.get(game.id, 0)),
                    "match_start_rate": starts,
                    "search_count": int(bucket.get("search", 0)),
                    "watchlist_count": int(bucket.get("follow", 0)),
                    # No provider publishes a viewer count for these feeds, so it
                    # stays None and reduces confidence rather than being guessed.
                    "viewer_count": None,
                    "last_updated": max(
                        (m.source_timestamp for m in matches if m.source_timestamp is not None),
                        default=None,
                    ),
                    "data_mode": (game.meta_data or {}).get("data_mode"),
                }
            )
        # Normalise datetime for JSON.
        for row in rows:
            if isinstance(row["last_updated"], datetime):
                row["last_updated"] = row["last_updated"].isoformat()
        result = self.engine.compute(rows)
        result["interest_totals"] = analytics_store.totals()
        result["cache"] = "miss"
        analytics_store.cache_set(key, result, self.trending_ttl)
        return result

    async def get_trending_matches(self, *, game_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        key = f"trending:matches:{game_id or 'all'}:{limit}"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}
        matches = await self._matches(game_id)
        event_counts = analytics_store.event_counts()
        start_counts = analytics_store.start_counts()
        ranked = trending.rank_trending_matches(
            matches, event_counts=event_counts, start_counts=start_counts, limit=limit
        )
        by_id = {m.id: m for m in matches}
        enriched = []
        for row in ranked:
            match = by_id.get(row["match_id"])
            if match is None:
                continue
            enriched.append({**row, "match": feed_service.serialize_match(match)})
        result = {
            "matches": enriched,
            "count": len(enriched),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "selection": {
                "method": "weighted measured activity (live state, observed events, observed starts, recency)",
                "weights": {"live_state": 0.45, "events_observed": 0.25, "starts_observed": 0.15, "recency": 0.15},
                "note": "Only activity this application measured contributes; nothing is hardcoded.",
            },
            "cache": "miss",
        }
        analytics_store.cache_set(key, result, self.trending_ttl)
        return result

    # ==================================================================
    # §11, §12, §15 — quality + consistency
    # ==================================================================
    async def get_data_quality(self, *, game_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        key = f"quality:{game_id or 'all'}"
        cached = analytics_store.cache_get(key)
        if cached is not None:
            return {**cached, "cache": "hit"}
        matches = await self._matches(game_id)
        providers = await self._providers()
        now = datetime.now(timezone.utc)
        ordered = sorted(matches, key=lambda m: m.scheduled_at or datetime.min, reverse=True)[:limit]
        results = [evaluate_data_quality(m, providers=providers, now=now) for m in ordered]
        result = {
            "game_id": game_id,
            "aggregate": aggregate_quality(results),
            "matches": results,
            "providers": providers,
            "source_consistency": source_consistency.detect_discrepancies(matches),
            "generated_at": now.isoformat(),
            "cache": "miss",
        }
        analytics_store.cache_set(key, result, self.cache_ttl)
        return result

    # ==================================================================
    # §17 — observability
    # ==================================================================
    async def get_observability(self) -> Dict[str, Any]:
        clients = channels = None
        try:
            from app.esports.websocket.manager import esports_ws_manager

            stats = esports_ws_manager.get_connection_stats()
            clients = int(stats.get("active_connections", 0))
            channels = int(stats.get("channels_with_subscribers", 0))
        except Exception:
            pass
        snapshot = esports_metrics.snapshot(connected_clients=clients, ws_channels=channels)
        snapshot["analytics_store"] = analytics_store.stats()
        snapshot["dirty_games"] = analytics_store.dirty_count()
        return {
            "observability": snapshot,
            "manager_stats": self.manager.get_stats() if self._manager else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ==================================================================
    # §13/§14 — incremental maintenance (used by the worker)
    # ==================================================================
    def mark_event(self, match_id: Optional[str], game_id: Optional[str], event_type: str) -> None:
        """Called by the ingest path: cheap, lock-only, never blocks delivery."""
        analytics_store.record_event(match_id, game_id, event_type)
        analytics_store.mark_dirty(game_id)
        esports_metrics.record_event_ingested(game_id)
        if event_type in ("MATCH_ENDED", "MAP_ENDED"):
            # A completion changes history — drop the affected cached views.
            analytics_store.invalidate("trending:")
            if match_id:
                analytics_store.invalidate(f"match:{match_id}")

    async def refresh_dirty(self, limit: int = 4) -> Dict[str, Any]:
        """Recompute only what changed (worker entry point)."""
        dirty = list(analytics_store.take_dirty())[:limit]
        refreshed: List[str] = []
        started = datetime.now(timezone.utc)
        for game_id in dirty:
            try:
                await self.get_trending_games()
                await self.get_trending_matches(game_id=game_id, limit=5)
                analytics_store.invalidate(f"quality:{game_id}")
                refreshed.append(game_id)
            except Exception as exc:
                logger.warning("dirty refresh failed for %s: %s", game_id, exc)
        elapsed_ms = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        esports_metrics.record_analytics_job("dirty_refresh", elapsed_ms)
        return {"refreshed": refreshed, "elapsed_ms": round(elapsed_ms, 3)}


#: Process-wide singleton, configured in main.py alongside the data manager.
analytics_service = EsportsAnalyticsService()


def configure(manager: Any) -> None:
    analytics_service.configure(manager)
