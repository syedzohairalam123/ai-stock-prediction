"""
Phase 21C §11 — Data Quality Engine.

Evaluates a match feed on five axes and returns HIGH / MEDIUM / LOW with the
individual component scores and the reasons behind any deduction, so a "LOW"
label always comes with an explanation instead of a bare grade:

  * freshness           — age of the newest provider timestamp
  * completeness        — share of the expected fields actually published
  * sequence integrity  — monotonic, unique event sequencing
  * source reliability  — provider error rate
  * provider health      — the provider's own reported status
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.esports.providers.base import GameEvent, Match, MatchStatus

#: The fields a "complete" match record is expected to publish. A missing one
#: only lowers the score; it never blocks the record from being shown.
EXPECTED_FIELDS = (
    "team_a_id",
    "team_b_id",
    "scheduled_at",
    "tournament_id",
    "source",
)

FRESHNESS_LIVE_SECONDS = 60
FRESHNESS_STALE_SECONDS = 1800


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status(match: Match) -> str:
    return match.status.value if isinstance(match.status, MatchStatus) else str(match.status)


def _freshness_score(match: Match, now: datetime) -> (float, Optional[float]):
    reference = _aware(match.source_timestamp) or _aware(match.received_at)
    if reference is None:
        return 0.0, None
    age = max(0.0, (now - reference).total_seconds())
    status = _status(match)
    if status in (MatchStatus.LIVE.value, MatchStatus.MAP_BREAK.value, MatchStatus.PAUSED.value):
        if age <= FRESHNESS_LIVE_SECONDS:
            return 1.0, age
        if age >= FRESHNESS_STALE_SECONDS:
            return 0.0, age
        return max(0.0, 1.0 - (age - FRESHNESS_LIVE_SECONDS) / (FRESHNESS_STALE_SECONDS - FRESHNESS_LIVE_SECONDS)), age
    # Finished/scheduled data is judged against its own freshness mode: a source
    # refreshed daily is not "stale" merely because the match ended yesterday.
    mode = str((match.meta_data or {}).get("data_mode") or "").upper()
    if mode == "LIVE":
        return (1.0 if age < 3600 else 0.5), age
    return (1.0 if age < 86400 else 0.6), age


def _completeness_score(match: Match) -> (float, List[str]):
    missing = [field for field in EXPECTED_FIELDS if not getattr(match, field, None)]
    meta = match.meta_data or {}
    names = meta.get("team_names") or {}
    if not names.get(match.team_a_id) or not names.get(match.team_b_id):
        missing.append("team_names")
    if match.best_of in (None, 0):
        missing.append("best_of")
    total = len(EXPECTED_FIELDS) + 2
    return max(0.0, 1.0 - len(missing) / total), missing


def _sequence_score(events: Sequence[GameEvent]) -> (Optional[float], List[str]):
    if not events:
        return None, []
    issues: List[str] = []
    ids = [e.id for e in events]
    if len(set(ids)) != len(ids):
        issues.append("duplicate_event_ids")
    ordered = sorted(events, key=lambda e: e.sequence)
    strictly_increasing = all(
        ordered[i].sequence < ordered[i + 1].sequence for i in range(len(ordered) - 1)
    )
    if not strictly_increasing:
        issues.append("non_monotonic_sequence")
    gapped = any(
        ordered[i + 1].sequence - ordered[i].sequence > 5 for i in range(len(ordered) - 1)
    )
    if gapped:
        issues.append("sequence_gaps")
    score = 1.0 - 0.34 * len(issues)
    return max(0.0, score), issues


def _provider_scores(providers: Optional[Sequence[Dict[str, Any]]], source: Optional[str]) -> (Optional[float], Optional[float], Optional[str]):
    if not providers:
        return None, None, None
    match_provider = next((p for p in providers if p.get("name") == source), None) or (
        providers[0] if len(providers) == 1 else None
    )
    if match_provider is None:
        return None, None, None
    status = str(match_provider.get("status") or "UNKNOWN").upper()
    health = {"AVAILABLE": 1.0, "DEGRADED": 0.5, "DOWN": 0.0}.get(status, 0.25)
    requests = int(match_provider.get("request_count") or 0)
    errors = int(match_provider.get("error_count") or 0)
    reliability = 1.0 if requests == 0 else max(0.0, 1.0 - errors / requests)
    return health, reliability, status


def evaluate_data_quality(
    match: Match,
    *,
    events: Optional[Sequence[GameEvent]] = None,
    providers: Optional[Sequence[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Evaluate one match's data quality end to end."""
    now = now or datetime.now(timezone.utc)
    freshness, age = _freshness_score(match, now)
    completeness, missing_fields = _completeness_score(match)
    sequence, sequence_issues = _sequence_score(events or [])
    health, reliability, provider_status = _provider_scores(providers, match.source)

    components: Dict[str, Optional[float]] = {
        "freshness": round(freshness, 4),
        "completeness": round(completeness, 4),
        "sequence_integrity": round(sequence, 4) if sequence is not None else None,
        "source_reliability": round(reliability, 4) if reliability is not None else None,
        "provider_health": round(health, 4) if health is not None else None,
    }
    # Weight only the components that were actually measurable, renumerating the
    # weights so a missing axis lowers confidence rather than the score.
    base_weights = {
        "freshness": 0.3,
        "completeness": 0.25,
        "sequence_integrity": 0.2,
        "source_reliability": 0.15,
        "provider_health": 0.1,
    }
    available = {k: w for k, w in base_weights.items() if components.get(k) is not None}
    weight_sum = sum(available.values())
    score = sum(components[k] * w for k, w in available.items()) / weight_sum if weight_sum else 0.0

    if score >= 0.8:
        label = "HIGH"
    elif score >= 0.5:
        label = "MEDIUM"
    else:
        label = "LOW"

    # Phase 21C §25: a provider that is not delivering cannot produce a HEALTHY
    # grade, however fresh and complete the last record it sent looked. Without
    # this cap a DOWN provider still scored HIGH, which would tell a reader the
    # opposite of the truth. Provider health is the one axis that overrides.
    if provider_status == "DOWN":
        label = "LOW"
    elif provider_status == "DEGRADED" and label == "HIGH":
        label = "MEDIUM"

    reasons: List[str] = []
    if missing_fields:
        reasons.append(f"missing fields: {', '.join(missing_fields)}")
    if sequence_issues:
        reasons.append(f"sequence issues: {', '.join(sequence_issues)}")
    if provider_status and provider_status != "AVAILABLE":
        reasons.append(f"provider {match.source} is {provider_status}")
    if age is None:
        reasons.append("no provider timestamp")
    elif age > FRESHNESS_STALE_SECONDS:
        reasons.append(f"data age {int(age)}s exceeds the stale threshold")

    return {
        "match_id": match.id,
        "game_id": match.game_id,
        "score": round(score, 4),
        "label": label,
        "components": components,
        "weights_used": available,
        "data_age_seconds": round(age, 2) if age is not None else None,
        "missing_fields": missing_fields,
        "sequence_issues": sequence_issues,
        "provider_status": provider_status,
        "source": match.source,
        "reasons": reasons,
        "evaluated_at": now.isoformat(),
    }


class DataQualityEngine:
    """
    Object wrapper around :func:`evaluate_data_quality` (spec §11).

    Holds the tunable thresholds so callers can construct a differently
    configured engine (e.g. in tests) without touching module globals.
    """

    #: Component weights — the single place they are defined.
    WEIGHTS: Dict[str, float] = {
        "freshness": 0.3,
        "completeness": 0.25,
        "sequence_integrity": 0.2,
        "source_reliability": 0.15,
        "provider_health": 0.1,
    }

    def __init__(self, fresh_seconds: int = FRESHNESS_LIVE_SECONDS, stale_seconds: int = FRESHNESS_STALE_SECONDS):
        self.fresh_seconds = fresh_seconds
        self.stale_seconds = stale_seconds

    def evaluate(
        self,
        match: Match,
        *,
        events: Optional[Sequence[GameEvent]] = None,
        providers: Optional[Sequence[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return evaluate_data_quality(match, events=events, providers=providers, now=now)

    def aggregate(self, results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        return aggregate_quality(results)


def aggregate_quality(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll per-match quality up to one feed-level grade."""
    if not results:
        return {"label": "UNAVAILABLE", "score": None, "evaluated": 0}
    score = sum(float(r["score"]) for r in results) / len(results)
    label = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.5 else "LOW"
    counts: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for result in results:
        counts[result["label"]] = counts.get(result["label"], 0) + 1
    return {"label": label, "score": round(score, 4), "evaluated": len(results), "counts": counts}
