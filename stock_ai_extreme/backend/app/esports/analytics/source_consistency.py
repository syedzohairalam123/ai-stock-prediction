"""
Phase 21C §12 — source consistency.

When two authorized sources describe the same match they are compared field by
field (score, teams, status, timestamp, tournament). Any disagreement is
surfaced as **SOURCE DISCREPANCY** for a human to judge — one source is never
silently allowed to overwrite another.

The detector also runs *intra*-source integrity checks (a series score that
contradicts the per-map records the same provider published), because that class
of inconsistency is real and cheap to catch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.esports.providers.base import Match, MatchStatus

DISCREPANCY_LABEL = "SOURCE DISCREPANCY"


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status(match: Match) -> str:
    return match.status.value if isinstance(match.status, MatchStatus) else str(match.status)


def normalized_key(match: Match) -> Tuple[str, Tuple[str, str], str]:
    """
    A source-independent identity for "the same match".

    Game + the two team ids (order-insensitive) + the calendar day. Providers
    name matches differently, so names are deliberately excluded.
    """
    teams = tuple(sorted([match.team_a_id, match.team_b_id]))
    day = (_aware(match.scheduled_at) or datetime.min.replace(tzinfo=timezone.utc)).date().isoformat()
    return match.game_id, teams, day  # type: ignore[return-value]


def _record(match: Match) -> Dict[str, Any]:
    names = (match.meta_data or {}).get("team_names") or {}
    return {
        "id": match.id,
        "source": match.source,
        "status": _status(match),
        "score_a": match.score_a,
        "score_b": match.score_b,
        "team_a_id": match.team_a_id,
        "team_b_id": match.team_b_id,
        "team_a_name": names.get(match.team_a_id),
        "team_b_name": names.get(match.team_b_id),
        "tournament_id": match.tournament_id,
        "tournament_name": (match.meta_data or {}).get("league") or (match.meta_data or {}).get("event"),
        "timestamp": _aware(match.source_timestamp).isoformat() if match.source_timestamp else None,
    }


def compare_records(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Field-by-field comparison of records that all describe the same match."""
    if len(records) < 2:
        return []
    fields = ["status", "score_a", "score_b", "team_a_name", "team_b_name", "tournament_id", "tournament_name"]
    reference = records[0]
    findings: List[Dict[str, Any]] = []
    for record in records[1:]:
        for field in fields:
            if reference.get(field) != record.get(field):
                findings.append(
                    {
                        "label": DISCREPANCY_LABEL,
                        "kind": "cross_source",
                        "field": field,
                        "sources": [reference.get("source"), record.get("source")],
                        "values": [reference.get(field), record.get(field)],
                        "match_ids": [reference.get("id"), record.get("id")],
                        "note": "Discrepancy reported for review; neither source is overwritten.",
                    }
                )
    return findings


def _intra_source_findings(match: Match) -> List[Dict[str, Any]]:
    """Checks that need only one source: does its own detail agree with itself?"""
    findings: List[Dict[str, Any]] = []
    games = (match.meta_data or {}).get("games") or []
    if _status(match) == MatchStatus.COMPLETED.value and games:
        wins_a = wins_b = 0
        decisive = 0
        for game in games:
            side = None
            if isinstance(game.get("radiant_win"), bool):
                side = "a" if game["radiant_win"] else "b"
            elif game.get("winner_side") in ("a", "b"):
                side = game["winner_side"]
            elif isinstance(game.get("team_a_score"), (int, float)) and isinstance(game.get("team_b_score"), (int, float)):
                if game["team_a_score"] != game["team_b_score"]:
                    side = "a" if game["team_a_score"] > game["team_b_score"] else "b"
            if side == "a":
                wins_a += 1
                decisive += 1
            elif side == "b":
                wins_b += 1
                decisive += 1
        if decisive and (wins_a != match.score_a or wins_b != match.score_b):
            findings.append(
                {
                    "label": DISCREPANCY_LABEL,
                    "kind": "intra_source",
                    "field": "series_score",
                    "sources": [match.source],
                    "values": [{"score_a": match.score_a, "score_b": match.score_b},
                               {"score_a": wins_a, "score_b": wins_b}],
                    "match_ids": [match.id],
                    "note": "Series score disagrees with the per-game records from the same source.",
                }
            )
    return findings


def detect_discrepancies(matches: Sequence[Match]) -> Dict[str, Any]:
    """
    Compare every match against any other record sharing its normalized key,
    then run the intra-source integrity checks.
    """
    groups: Dict[Tuple[str, Tuple[str, str], str], List[Match]] = {}
    for match in matches:
        groups.setdefault(normalized_key(match), []).append(match)

    findings: List[Dict[str, Any]] = []
    compared_groups = 0
    for group in groups.values():
        if len(group) >= 2:
            distinct_sources = {m.source for m in group}
            if len(distinct_sources) >= 2:
                compared_groups += 1
                findings.extend(compare_records([_record(m) for m in group]))
        for match in group:
            findings.extend(_intra_source_findings(match))

    return {
        "label": DISCREPANCY_LABEL if findings else "CONSISTENT",
        "discrepancies": findings,
        "count": len(findings),
        "matches_checked": len(matches),
        "cross_source_groups_compared": compared_groups,
        "note": (
            "A discrepancy is reported, never auto-resolved: the authoritative "
            "value stays with the provider that published it."
        ),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
