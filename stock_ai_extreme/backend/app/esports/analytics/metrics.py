"""
Phase 21C §1–§5, §10 — descriptive esports analytics.

Pure functions over the Phase 21A provider models. Real statistical tooling is
used for real analytical purposes only:

  * pandas  — tidy frames, rolling windows, time-series aggregation
  * numpy   — means, variance, standard deviation, z-scores
  * scipy   — robust z-scores (MAD) for outlier detection
  * sklearn — IsolationForest, used only where the sample genuinely justifies it

Every metric reports the three things the spec demands: **sample size**,
**date range** and **source**, plus an explicit data-quality label. A metric the
data cannot support is returned with ``available: false`` and a reason — never a
fabricated number, and never a statistic forced from an incompatible game.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from app.esports.providers.base import GameEvent, Match, MatchStatus, Player, Team, per_game_records

#: The exact label the spec requires on a detected outlier (§10).
ANOMALY_LABEL = "ANOMALY DETECTED"

#: Below this many observations an IsolationForest is not statistically
#: justified — a z-score is reported instead (spec §10, §2).
ISOLATION_FOREST_MIN_SAMPLES = 20


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status(match: Match) -> str:
    return match.status.value if isinstance(match.status, MatchStatus) else str(match.status)


def _is_finished(match: Match) -> bool:
    return _status(match) == MatchStatus.COMPLETED.value


def infer_winner(match: Match) -> Optional[str]:
    """
    The winning team id, from the provider's ``winner_id`` when present.

    Finished matches from some sources publish the score but not the winner; in
    that case the winner is read off the score the source did publish. A tie or
    a missing score yields ``None`` rather than a guess.
    """
    if match.winner_id:
        return match.winner_id
    if not _is_finished(match):
        return None
    if match.score_a > match.score_b:
        return match.team_a_id
    if match.score_b > match.score_a:
        return match.team_b_id
    return None


def team_games(matches: Sequence[Match], team_id: str, *, finished_only: bool = True) -> List[Match]:
    rows = [
        m
        for m in matches
        if team_id in (m.team_a_id, m.team_b_id) and (not finished_only or _is_finished(m))
    ]
    rows.sort(key=lambda m: _aware(m.scheduled_at) or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def _opponent(match: Match, team_id: str) -> str:
    return match.team_b_id if match.team_a_id == team_id else match.team_a_id


def _team_score(match: Match, team_id: str) -> int:
    return match.score_a if match.team_a_id == team_id else match.score_b


def _opp_score(match: Match, team_id: str) -> int:
    return match.score_b if match.team_a_id == team_id else match.score_a


def _date_range(matches: Sequence[Match]) -> Dict[str, Optional[str]]:
    stamps = [s for s in (_aware(m.scheduled_at) for m in matches) if s is not None]
    if not stamps:
        return {"from": None, "to": None}
    return {"from": min(stamps).isoformat(), "to": max(stamps).isoformat()}


def _sources(matches: Sequence[Match]) -> List[str]:
    return sorted({m.source for m in matches if m.source})


def quality_label(sample_size: int, min_sample: int, completeness: float = 1.0) -> str:
    """
    HIGH / MEDIUM / LOW.

    LOW when the sample is too small to conclude anything; MEDIUM when it clears
    the floor but the underlying records are incomplete or only marginally sized.
    """
    if sample_size <= 0:
        return "UNAVAILABLE"
    if sample_size < min_sample:
        return "LOW"
    if completeness < 0.8 or sample_size < min_sample * 2:
        return "MEDIUM"
    return "HIGH"


def _metric_block(
    value: Any,
    *,
    sample_size: int,
    matches: Sequence[Match],
    completeness: float = 1.0,
    min_sample: int = 3,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    block = {
        "value": value,
        "sample_size": sample_size,
        "date_range": _date_range(matches),
        "sources": _sources(matches),
        "data_quality": quality_label(sample_size, min_sample, completeness),
    }
    if extra:
        block.update(extra)
    return block


# ---------------------------------------------------------------------------
# §3 — recent team form
# ---------------------------------------------------------------------------

def calculate_team_form(
    matches: Sequence[Match],
    team_id: str,
    *,
    limit: int = 10,
    min_sample: int = 3,
) -> Dict[str, Any]:
    """
    Recent form from actual historical results.

    Returns the last ``limit`` results plus the sample size, so a "70% win rate"
    is always shown next to the number of matches it was computed from.
    """
    rows = team_games(matches, team_id)[-limit:]
    results: List[Dict[str, Any]] = []
    wins = losses = 0
    for match in rows:
        winner = infer_winner(match)
        if winner == team_id:
            outcome = "win"
            wins += 1
        elif winner is None:
            outcome = "draw_or_unknown"
        else:
            outcome = "loss"
            losses += 1
        results.append(
            {
                "match_id": match.id,
                "opponent_id": _opponent(match, team_id),
                "opponent_name": (match.meta_data or {}).get("team_names", {}).get(_opponent(match, team_id)),
                "outcome": outcome,
                "score": f"{_team_score(match, team_id)}-{_opp_score(match, team_id)}",
                "tournament": (match.meta_data or {}).get("league") or (match.meta_data or {}).get("event"),
                "played_at": (_aware(match.scheduled_at).isoformat() if match.scheduled_at else None),
            }
        )
    decided = wins + losses
    win_rate = (wins / decided) if decided else None
    return {
        "team_id": team_id,
        "form": results,
        **_metric_block(
            {"wins": wins, "losses": losses, "win_rate": win_rate, "streak": _current_streak(results)},
            sample_size=len(rows),
            matches=rows,
            min_sample=min_sample,
            extra={"decided_matches": decided, "undecided_matches": len(rows) - decided},
        ),
    }


def _current_streak(form: Sequence[Dict[str, Any]]) -> Optional[str]:
    """e.g. "W3" / "L1" — the running streak from the most recent match back."""
    if not form:
        return None
    last = form[-1]["outcome"][0].upper()
    if last not in ("W", "L"):
        return None
    count = 0
    for entry in reversed(form):
        if entry["outcome"][0].upper() != last:
            break
        count += 1
    return f"{last}{count}"


# ---------------------------------------------------------------------------
# §4 — map analytics (where valid historical data exists)
# ---------------------------------------------------------------------------

def _game_winner_side(match: Match, game: Dict[str, Any]) -> Optional[str]:
    """'a' / 'b' / None for one map/game record, published or score-derived."""
    if isinstance(game.get("radiant_win"), bool):
        return "a" if game["radiant_win"] else "b"
    if game.get("winner_side") in ("a", "b"):
        return game["winner_side"]
    a, b = game.get("team_a_score"), game.get("team_b_score")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a != b:
        return "a" if a > b else "b"
    return None


def calculate_map_analytics(
    matches: Sequence[Match],
    team_id: str,
    *,
    recent_window: int = 5,
    min_sample: int = 3,
) -> Dict[str, Any]:
    """
    Per-map win/loss rate for a team, from the per-map records the source
    publishes. Only maps with a determinable winner and a published map identity
    are counted; anything else lowers the reported data quality instead of being
    silently included.
    """
    rows = team_games(matches, team_id)
    records: List[Dict[str, Any]] = []
    incomplete = 0
    total_games = 0
    played_matches: List[Match] = []

    for match in rows:
        # CS2 publishes per-map records under ``maps``; Dota/LoL under ``games``.
        games = per_game_records(match.meta_data)
        if not games:
            continue
        played_matches.append(match)
        for game in games:
            total_games += 1
            name = game.get("name")
            side = _game_winner_side(match, game)
            if not name or side is None:
                incomplete += 1
                continue
            team_side = "a" if match.team_a_id == team_id else "b"
            records.append({"map": name, "won": side == team_side, "match": match})

    if not records:
        return {
            "available": False,
            "reason": "The provider does not publish per-map identities/winners for this team.",
            "maps": [],
            "sample_size": 0,
            "date_range": _date_range(played_matches),
            "sources": _sources(played_matches),
            "data_quality": "UNAVAILABLE",
        }

    frame = pd.DataFrame([{"map": r["map"], "won": r["won"], "match_index": i} for i, r in enumerate(records)])
    grouped = frame.groupby("map")
    maps: List[Dict[str, Any]] = []
    for map_name, group in grouped:
        played = int(len(group))
        wins = int(group["won"].sum())
        losses = played - wins
        recent = group.tail(recent_window)["won"].tolist()
        maps.append(
            {
                "map": map_name,
                "played": played,
                "wins": wins,
                "losses": losses,
                "win_rate": (wins / played) if played else None,
                "loss_rate": (losses / played) if played else None,
                "recent_form": ["W" if won else "L" for won in recent],
                "recent_win_rate": (sum(recent) / len(recent)) if recent else None,
                "sample_size": played,
                "data_quality": quality_label(played, min_sample, 1.0),
            }
        )
    maps.sort(key=lambda m: (-m["sample_size"], m["map"]))
    completeness = 1.0 - (incomplete / total_games) if total_games else 0.0
    return {
        "available": True,
        "reason": None,
        "maps": maps,
        "sample_size": len(records),
        "incomplete_records": incomplete,
        "date_range": _date_range(played_matches),
        "sources": _sources(played_matches),
        "data_quality": quality_label(len(records), min_sample, completeness),
    }


# ---------------------------------------------------------------------------
# series win rate, duration, score progression, consistency (§1)
# ---------------------------------------------------------------------------

def calculate_series_win_rate(
    matches: Sequence[Match], team_id: str, *, min_sample: int = 3
) -> Dict[str, Any]:
    rows = team_games(matches, team_id)
    wins = sum(1 for m in rows if infer_winner(m) == team_id)
    losses = sum(1 for m in rows if infer_winner(m) not in (None, team_id))
    decided = wins + losses
    return _metric_block(
        {"wins": wins, "losses": losses, "win_rate": (wins / decided) if decided else None},
        sample_size=decided,
        matches=rows,
        min_sample=min_sample,
    )


def calculate_match_duration_stats(
    matches: Sequence[Match], team_id: Optional[str] = None, *, min_sample: int = 3
) -> Dict[str, Any]:
    """
    Duration distribution (seconds) from the per-game durations a source
    publishes. pandas aggregates; NumPy gives mean/std; SciPy is not needed here.
    """
    rows = team_games(matches, team_id) if team_id else list(matches)
    durations: List[float] = []
    for match in rows:
        for game in per_game_records(match.meta_data):
            value = game.get("duration")
            if isinstance(value, (int, float)) and value > 0:
                durations.append(float(value))
    if not durations:
        return _metric_block(
            None, sample_size=0, matches=rows, min_sample=min_sample,
            extra={"available": False, "reason": "No published game durations."},
        )
    series = pd.Series(durations)
    return {
        "available": True,
        "reason": None,
        **_metric_block(
            {
                "mean_seconds": float(series.mean()),
                "median_seconds": float(series.median()),
                "std_seconds": float(series.std(ddof=0)) if len(series) > 1 else 0.0,
                "min_seconds": float(series.min()),
                "max_seconds": float(series.max()),
                "rolling_mean_seconds": [float(v) for v in series.rolling(window=min(5, len(series)), min_periods=1).mean()],
            },
            sample_size=len(durations),
            matches=rows,
            min_sample=min_sample,
        ),
    }


def calculate_score_progression(
    matches: Sequence[Match], team_id: str, *, min_sample: int = 3
) -> Dict[str, Any]:
    """Rolling mean of the team's score differential across recent matches."""
    rows = team_games(matches, team_id)
    if not rows:
        return _metric_block(None, sample_size=0, matches=[], min_sample=min_sample)
    diffs = np.array([_team_score(m, team_id) - _opp_score(m, team_id) for m in rows], dtype=float)
    rolling = pd.Series(diffs).rolling(window=min(5, len(diffs)), min_periods=1).mean()
    return {
        **_metric_block(
            {
                "differential_mean": float(np.mean(diffs)),
                "differential_std": float(np.std(diffs)),
                "rolling_differential": [float(v) for v in rolling],
                "trend": _trend(diffs),
            },
            sample_size=len(rows),
            matches=rows,
            min_sample=min_sample,
        ),
    }


def calculate_historical_consistency(values: Sequence[float]) -> Optional[float]:
    """
    1 - coefficient of variation, clamped to [0, 1].

    A team whose results barely vary scores near 1; a wildly inconsistent one
    approaches 0. Returns None when there is nothing to measure.
    """
    array = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    if array.size < 2:
        return None
    mean = float(np.mean(np.abs(array)))
    if mean == 0:
        return None
    cv = float(np.std(array)) / mean
    return max(0.0, min(1.0, 1.0 - cv))


def _trend(series: np.ndarray) -> Optional[str]:
    """RISING / FALLING / STABLE from the slope of a linear fit."""
    if series.size < 3:
        return None
    x = np.arange(series.size, dtype=float)
    slope = float(np.polyfit(x, series, 1)[0])
    spread = float(np.std(series)) or 1.0
    if abs(slope) < 0.05 * spread:
        return "STABLE"
    return "RISING" if slope > 0 else "FALLING"


# ---------------------------------------------------------------------------
# §5 — player analytics (game-specific metrics only)
# ---------------------------------------------------------------------------

#: Which provider-supplied statistics are legitimate per game. CS2 publishes
#: rating/ADR/KAST; Dota publishes games/wins; LoL's public gateway publishes no
#: per-player statistics at all, so the metric set is empty by design.
PLAYER_METRIC_SCHEMA: Dict[str, List[str]] = {
    "cs2": ["rating", "adr", "kast", "k", "d", "kd_ratio"],
    "dota2": ["games_played", "wins"],
    "lol": [],
}

PLAYER_METRIC_LABELS: Dict[str, str] = {
    "rating": "Rating",
    "adr": "ADR",
    "kast": "KAST %",
    "k": "Kills",
    "d": "Deaths",
    "kd_ratio": "K/D",
    "games_played": "Games",
    "wins": "Wins",
}


def player_analytics(players: Sequence[Player], game_id: str, *, min_sample: int = 1) -> Dict[str, Any]:
    """
    Per-player metrics using only the game's own statistics — CS2 numbers are
    never forced onto a Dota 2 player.
    """
    schema = PLAYER_METRIC_SCHEMA.get(game_id, [])
    if not schema:
        return {
            "available": False,
            "reason": f"The {game_id} provider publishes no per-player statistics.",
            "game_id": game_id,
            "players": [],
            "sample_size": 0,
            "data_quality": "UNAVAILABLE",
        }
    rows: List[Dict[str, Any]] = []
    for player in players:
        meta = player.meta_data or {}
        metrics: List[Dict[str, Any]] = []
        for key in schema:
            value = meta.get(key)
            if value is None and key == "kd_ratio":
                kills, deaths = meta.get("k"), meta.get("d")
                if isinstance(kills, (int, float)) and isinstance(deaths, (int, float)) and deaths:
                    value = round(float(kills) / float(deaths), 3)
            if isinstance(value, (int, float)):
                metrics.append({"key": key, "label": PLAYER_METRIC_LABELS.get(key, key), "value": value})
        if not metrics:
            continue
        rows.append(
            {
                "id": player.id,
                "name": player.name,
                "handle": player.handle,
                "role": player.role,
                "country": player.country,
                "avatar_url": meta.get("avatar_url"),
                "team_id": player.team_id,
                "metrics": metrics,
                "metric_count": len(metrics),
            }
        )
    return {
        "available": bool(rows),
        "reason": None if rows else "No player carried a published statistic.",
        "game_id": game_id,
        "players": rows,
        "sample_size": len(rows),
        "metric_schema": schema,
        "data_quality": quality_label(len(rows), min_sample, 1.0),
    }


# ---------------------------------------------------------------------------
# §10 — anomaly detection (descriptive, labelled, never speculative)
# ---------------------------------------------------------------------------

def zscore_anomalies(
    values: Sequence[float],
    *,
    z_threshold: float = 3.0,
    labels: Optional[Sequence[str]] = None,
    method: str = "zscore",
) -> Dict[str, Any]:
    """
    Outliers measured by z-score. Returns an empty finding list when the sample
    is too small to say anything — an anomaly is never declared from 2 points.
    """
    array = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    if array.size < 4:
        return {"available": False, "reason": "Insufficient sample for outlier detection.", "method": method,
                "sample_size": int(array.size), "anomalies": [], "mean": None, "std": None}
    mean = float(np.mean(array))
    std = float(np.std(array))
    if std == 0:
        return {"available": True, "reason": None, "method": method, "sample_size": int(array.size),
                "mean": mean, "std": 0.0, "anomalies": []}
    z = (array - mean) / std
    findings: List[Dict[str, Any]] = []
    for index, value in enumerate(z):
        if abs(float(value)) >= z_threshold:
            findings.append(
                {
                    "label": ANOMALY_LABEL,
                    "method": method,
                    "index": index,
                    "reference": (labels[index] if labels and index < len(labels) else None),
                    "value": float(array[index]),
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                    "z_score": round(float(value), 4),
                    "direction": "high" if value > 0 else "low",
                }
            )
    return {
        "available": True,
        "reason": None,
        "method": method,
        "sample_size": int(array.size),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "threshold": z_threshold,
        "anomalies": findings,
    }


def robust_zscore_anomalies(
    values: Sequence[float], *, z_threshold: float = 3.5, labels: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    """
    Median-absolute-deviation z-scores (SciPy), robust to the very outliers we
    are trying to find — used alongside the plain z-score, not instead of it.
    """
    from scipy import stats

    array = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    if array.size < 5:
        return {"available": False, "reason": "Insufficient sample for robust detection.",
                "method": "modified_zscore", "sample_size": int(array.size), "anomalies": []}
    median = float(np.median(array))
    # SciPy's median absolute deviation (the robust spread measure itself).
    mad = float(stats.median_abs_deviation(array, scale=1.0))
    if mad == 0:
        return {"available": True, "reason": None, "method": "modified_zscore",
                "sample_size": int(array.size), "median": median, "mad": 0.0, "anomalies": []}
    scores = (array - median) / (1.4826 * mad)
    findings: List[Dict[str, Any]] = []
    for index, score in enumerate(np.asarray(scores, dtype=float)):
        if abs(float(score)) >= z_threshold:
            findings.append(
                {
                    "label": ANOMALY_LABEL,
                    "method": "modified_zscore",
                    "index": index,
                    "reference": (labels[index] if labels and index < len(labels) else None),
                    "value": float(array[index]),
                    "median": round(median, 4),
                    "z_score": round(float(score), 4),
                    "direction": "high" if score > 0 else "low",
                }
            )
    return {
        "available": True,
        "reason": None,
        "method": "modified_zscore",
        "sample_size": int(array.size),
        "median": round(median, 4),
        "mad": round(mad, 4),
        "threshold": z_threshold,
        "anomalies": findings,
    }


def isolation_forest_anomalies(
    feature_matrix: Sequence[Sequence[float]],
    *,
    labels: Optional[Sequence[str]] = None,
    contamination: float = 0.1,
    random_state: int = 42,
) -> Dict[str, Any]:
    """
    Multivariate outliers via scikit-learn's IsolationForest.

    Only run when the sample genuinely justifies it (>= 20 rows, >= 2 features,
    no gaps); otherwise the caller falls back to a z-score and this reports why.
    """
    rows = [list(map(float, row)) for row in feature_matrix if row is not None]
    if len(rows) < ISOLATION_FOREST_MIN_SAMPLES:
        return {
            "available": False,
            "reason": f"IsolationForest needs at least {ISOLATION_FOREST_MIN_SAMPLES} observations; using z-score instead.",
            "method": "isolation_forest",
            "sample_size": len(rows),
            "anomalies": [],
        }
    width = min(len(r) for r in rows)
    if width < 2:
        return {"available": False, "reason": "IsolationForest needs at least 2 features.", "method": "isolation_forest",
                "sample_size": len(rows), "anomalies": []}
    matrix = np.asarray([row[:width] for row in rows], dtype=float)
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(contamination=min(max(contamination, 0.01), 0.5), random_state=random_state)
    predictions = model.fit_predict(matrix)
    scores = model.decision_function(matrix)
    findings: List[Dict[str, Any]] = []
    for index, prediction in enumerate(predictions):
        if int(prediction) == -1:
            findings.append(
                {
                    "label": ANOMALY_LABEL,
                    "method": "isolation_forest",
                    "index": index,
                    "reference": (labels[index] if labels and index < len(labels) else None),
                    "score": round(float(scores[index]), 4),
                    "features": [round(float(v), 4) for v in matrix[index]],
                }
            )
    return {
        "available": True,
        "reason": None,
        "method": "isolation_forest",
        "sample_size": len(rows),
        "features": width,
        "anomalies": findings,
    }


# ---------------------------------------------------------------------------
# event frequency (§1)
# ---------------------------------------------------------------------------

def calculate_event_frequency(
    events: Sequence[GameEvent], *, window_minutes: float = 60.0, min_sample: int = 3
) -> Dict[str, Any]:
    """Events per minute, overall and by type, from the real event stream."""
    if not events:
        return {"available": False, "reason": "No events recorded.", "by_type": {}, "sample_size": 0,
                "data_quality": "UNAVAILABLE", "date_range": {"from": None, "to": None}, "sources": []}
    stamps = [_aware(e.timestamp) for e in events if e.timestamp]
    span_minutes = ((max(stamps) - min(stamps)).total_seconds() / 60.0) if len(stamps) > 1 else 0.0
    frame = pd.DataFrame({"type": [e.type.value for e in events], "timestamp": stamps})
    by_type = frame.groupby("type").size().to_dict()
    span = max(span_minutes, window_minutes if span_minutes == 0 else span_minutes)
    return {
        "available": True,
        "reason": None,
        "total_events": len(events),
        "span_minutes": round(span_minutes, 3),
        "events_per_minute": round(len(events) / span, 4) if span > 0 else None,
        "by_type": {k: int(v) for k, v in by_type.items()},
        "by_type_per_minute": ({k: round(int(v) / span, 4) for k, v in by_type.items()} if span > 0 else {}),
        "sample_size": len(events),
        "date_range": {
            "from": min(stamps).isoformat() if stamps else None,
            "to": max(stamps).isoformat() if stamps else None,
        },
        "sources": sorted({e.source for e in events if e.source}),
        "data_quality": quality_label(len(events), min_sample, 1.0),
    }


def build_series_frame(matches: Sequence[Match]) -> pd.DataFrame:
    """A tidy one-row-per-match frame used by the trend/anomaly aggregations."""
    rows = [
        {
            "match_id": m.id,
            "game_id": m.game_id,
            "tournament_id": m.tournament_id,
            "status": _status(m),
            "scheduled_at": _aware(m.scheduled_at),
            "score_a": m.score_a,
            "score_b": m.score_b,
            "margin": abs(m.score_a - m.score_b),
            "total_maps": m.map_number,
            "best_of": m.best_of,
            "duration_seconds": max(
                [g.get("duration") or 0 for g in per_game_records(m.meta_data)], default=0
            ),
            "source": m.source,
        }
        for m in matches
    ]
    if not rows:
        return pd.DataFrame(
            columns=["match_id", "game_id", "status", "scheduled_at", "score_a", "score_b", "margin",
                     "total_maps", "best_of", "duration_seconds", "source"]
        )
    frame = pd.DataFrame(rows)
    frame["scheduled_at"] = pd.to_datetime(frame["scheduled_at"], utc=True, errors="coerce")
    return frame.sort_values("scheduled_at")
