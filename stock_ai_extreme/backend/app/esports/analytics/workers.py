"""
Phase 21C §14 — background analytics workers.

A single asyncio loop, started from the app's lifespan, that keeps the expensive
work *off* the live path:

  1. trending refresh        — recompute the trending score for dirty games
  2. historical aggregation  — warm team analytics for recently active teams
  3. anomaly detection       — descriptive outlier scan across recent results
  4. cleanup                 — prune expired cache rows and stale observations

Every job is best-effort and isolated: a failing provider or a bad payload is
logged and the loop moves on. Live WebSocket delivery never awaits any of this
(spec §13, §14).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.config import settings
from app.esports.analytics import metrics
from app.esports.analytics.observability import esports_metrics
from app.esports.analytics.service import analytics_service
from app.esports.analytics.store import analytics_store

logger = logging.getLogger("neural_market.esports.analytics.workers")

ANOMALY_CACHE_KEY = "anomalies:global"
WARM_TEAMS_PER_GAME = 6


async def refresh_trending() -> Dict[str, Any]:
    """Recompute trending for dirty games (bounded by the service)."""
    started = time.monotonic()
    result = await analytics_service.refresh_dirty(limit=4)
    elapsed = (time.monotonic() - started) * 1000
    esports_metrics.record_analytics_job("trending_refresh", elapsed)
    return result


async def warm_team_aggregates() -> Dict[str, Any]:
    """Cache team analytics for the teams playing the most recent matches."""
    started = time.monotonic()
    warmed = 0
    manager = analytics_service.manager
    games = await manager.get_games()
    for game in games:
        try:
            matches = await manager.get_matches(game.id)
        except Exception as exc:
            logger.debug("aggregation warm skipped for %s: %s", game.id, exc)
            continue
        ordered = sorted(matches, key=lambda m: m.scheduled_at or datetime.min, reverse=True)
        seen: List[str] = []
        for match in ordered:
            for team_id in (match.team_a_id, match.team_b_id):
                if team_id not in seen:
                    seen.append(team_id)
            if len(seen) >= WARM_TEAMS_PER_GAME:
                break
        for team_id in seen[:WARM_TEAMS_PER_GAME]:
            try:
                await analytics_service.get_team_analytics(team_id, game_id=game.id)
                warmed += 1
            except Exception as exc:
                logger.debug("team aggregation failed for %s: %s", team_id, exc)
    elapsed = (time.monotonic() - started) * 1000
    esports_metrics.record_analytics_job("aggregation_warm", elapsed)
    return {"teams_warmed": warmed, "elapsed_ms": round(elapsed, 3)}


async def anomaly_scan() -> Dict[str, Any]:
    """
    Descriptive outlier scan over the real recent-result distributions.

    Runs against durations and score margins — quantities every provider
    publishes — and caches the finding for the data-quality endpoint. No cause
    is ever inferred; results carry the ANOMALY DETECTED label and the method
    that produced them.
    """
    started = time.monotonic()
    manager = analytics_service.manager
    games = await manager.get_games()
    scan: Dict[str, Any] = {"games": {}, "generated_at": datetime.now(timezone.utc).isoformat()}
    total = 0
    for game in games:
        try:
            matches = await manager.get_matches(game.id)
        except Exception:
            continue
        durations: List[float] = []
        margins: List[float] = []
        labels: List[str] = []
        for match in matches:
            for index, record in enumerate((match.meta_data or {}).get("games") or []):
                value = record.get("duration")
                if isinstance(value, (int, float)) and value:
                    durations.append(float(value))
            margins.append(float(abs(match.score_a - match.score_b)))
            labels.append(match.id)
        duration_findings = metrics.zscore_anomalies(
            durations, z_threshold=analytics_service.z_threshold, method="zscore_duration"
        )
        margin_findings = metrics.zscore_anomalies(
            margins, z_threshold=analytics_service.z_threshold, labels=labels, method="zscore_score_margin"
        )
        count = len(duration_findings.get("anomalies", [])) + len(margin_findings.get("anomalies", []))
        total += count
        scan["games"][game.id] = {
            "label": metrics.ANOMALY_LABEL if count else "NO ANOMALY",
            "count": count,
            "duration": duration_findings,
            "score_margin": margin_findings,
        }
    scan["total_findings"] = total
    scan["note"] = "Descriptive only; a flagged value is unusual for the sample, not a diagnosis."
    
    # Derived convenience fields (additive — the nested per-game structure above
    # is unchanged): the hub-level data-quality UI reads a flat findings array
    # plus the number of matches that contributed to the scan, so surface both
    # here in their honest, computed form.
    findings: List[Dict[str, Any]] = []
    for game_id, game_result in scan["games"].items():
        for check_name in ("duration", "score_margin"):
            check = game_result.get(check_name) or {}
            for anomaly in check.get("anomalies", []):
                findings.append({
                    "game_id": game_id,
                    "check": check_name,
                    **anomaly,
                })
    scan["findings"] = findings
    # The score-margin series appends exactly one sample per match, so its
    # z-score sample_size equals the number of matches scanned for that game.
    scan["matches_scanned"] = sum(
        (game_result.get("score_margin") or {}).get("sample_size") or 0
        for game_result in scan["games"].values()
        if isinstance(game_result, dict)
    )
    scan["matches_scanned_note"] = (
        "matches_scanned sums the per-game score-margin sample sizes; each "
        "match contributes exactly one score-margin sample per game."
    )
    analytics_store.cache_set(ANOMALY_CACHE_KEY, scan, 300)
    elapsed = (time.monotonic() - started) * 1000
    esports_metrics.record_analytics_job("anomaly_scan", elapsed)
    return {"total_findings": total, "elapsed_ms": round(elapsed, 3)}


async def cleanup() -> Dict[str, Any]:
    started = time.monotonic()
    removed = analytics_store.prune()
    elapsed = (time.monotonic() - started) * 1000
    esports_metrics.record_analytics_job("cleanup", elapsed)
    return {"cache_rows_pruned": removed, "elapsed_ms": round(elapsed, 3)}


async def run_analytics_loop() -> None:
    """Infinite loop; interval from ESPORTS_WORKER_INTERVAL_SECONDS."""
    interval = max(int(getattr(settings, "esports_worker_interval_seconds", 60)), 15)
    logger.info("esports analytics worker started (interval %ds)", interval)
    # Warm once shortly after boot so a first visitor gets cached analytics.
    await asyncio.sleep(5)
    while True:
        started = time.monotonic()
        for name, job in (
            ("trending", refresh_trending),
            ("aggregation", warm_team_aggregates),
            ("anomaly", anomaly_scan),
            ("cleanup", cleanup),
        ):
            try:
                await job()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                esports_metrics.record_error()
                logger.warning("esports analytics job '%s' failed: %s", name, exc)
        elapsed = time.monotonic() - started
        try:
            await asyncio.sleep(max(interval - elapsed, 5))
        except asyncio.CancelledError:
            logger.info("esports analytics worker stopping")
            raise


async def run_startup_pass() -> Dict[str, Any]:
    """One immediate pass used at boot (and by tests)."""
    results: Dict[str, Any] = {}
    for name, job in (("aggregation", warm_team_aggregates), ("anomaly", anomaly_scan)):
        try:
            results[name] = await job()
        except Exception as exc:
            results[name] = {"error": str(exc)}
    return results
