"""
Event impact analytics — the honest version of "politics prediction".

Nothing here predicts elections, wars, or policy outcomes (nothing can, and
this project's ground rules forbid pretending otherwise). What this module
DOES deliver, entirely from data the app already fetches:

  1. Historical event-study: "what did this asset actually do after similar
     past events?" — measured on real price windows around real event dates.
  2. A Geopolitical/Market Stress Score built from real news headlines
     (volume of conflict/geopolitics keywords + news sentiment), clearly
     labeled as a risk indicator, never an outcome forecast.

Both are deterministic statistics over fetched data — testable with
synthetic frames, no network needed for the math itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# Keywords that mark a headline as geopolitically/policy salient. Deliberately
# conservative — a word like "election" alone doesn't make news "risk news".
GEOPOLITICAL_KEYWORDS = {
    "war", "conflict", "sanctions", "strike", "strikes", "attack", "attacks",
    "invasion", "military", "troops", "ceasefire", "treaty", "tariff", "tariffs",
    "trade war", "embargo", "escalation", "escalates", "nuclear", "missile",
    "election", "elections", "vote", "senate", "congress", "parliament",
    "policy", "regulation", "regulator", "ban", "bans", "shutdown",
    "impeach", "coup", "protest", "protests", "unrest", "crisis",
}

_OIL_SENSITIVE = {"CL=F", "BZ=F", "NG=F", "XOM", "CVX", "OXY"}
_GOLD_SENSITIVE = {"GC=F", "SI=F", "GLD", "IAU"}


@dataclass
class EventStudyResult:
    event_label: str
    sample_size: int
    avg_move_1d_pct: float
    avg_move_5d_pct: float
    avg_move_20d_pct: float
    positive_1d_rate: float
    worst_5d_pct: float
    best_5d_pct: float
    dates_used: list[str]


def _pct_window(closes: pd.Series, event_pos: int, horizon: int) -> float | None:
    """% move from the event-day close to close+horizon bars. None when the
    window runs off the end of the data (never truncated silently)."""
    end = event_pos + horizon
    if end >= len(closes):
        return None
    base, later = float(closes.iloc[event_pos]), float(closes.iloc[end])
    if base == 0:
        return None
    return round((later - base) / base * 100.0, 4)


def event_study(df: pd.DataFrame, event_dates: list[str], label: str,
                horizons: tuple[int, ...] = (1, 5, 20)) -> EventStudyResult:
    """Average real price behavior after past events. `event_dates` are the
    dates of PAST events of one category (e.g. past FOMC decisions, past
    elections); the study measures what actually happened next in this
    asset's own history. Sample size is reported honestly — 2 events is
    anecdote, and the response says so."""
    closes = df["Close"]
    index = pd.to_datetime(closes.index)
    positions: list[int] = []
    for raw in event_dates:
        ts = pd.Timestamp(raw)
        matches = (index >= ts.normalize()).nonzero()[0]
        if len(matches):
            pos = int(matches[0])
            # The first bar at/after the event date must be CLOSE to it —
            # otherwise a 1950 date would "match" bar 0 and poison the study.
            gap_days = (index[pos] - ts.normalize()).days
            if gap_days <= 7 and pos not in positions and pos < len(closes) - min(horizons):
                positions.append(pos)
    if not positions:
        raise ValueError(f"No usable event dates inside the loaded history for '{label}'.")

    moves = {h: [_pct_window(closes, p, h) for p in positions] for h in horizons}
    clean = {h: [m for m in vals if m is not None] for h, vals in moves.items()}
    one_d = clean.get(horizons[0], [])
    if not one_d:
        raise ValueError("Not enough post-event history to measure even the shortest horizon.")

    def avg(h: int) -> float:
        vals = clean.get(h, [])
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return EventStudyResult(
        event_label=label,
        sample_size=len(positions),
        avg_move_1d_pct=avg(1),
        avg_move_5d_pct=avg(5),
        avg_move_20d_pct=avg(20),
        positive_1d_rate=round(sum(1 for m in one_d if m > 0) / len(one_d), 4),
        worst_5d_pct=round(min(clean.get(5, [0.0])), 4),
        best_5d_pct=round(max(clean.get(5, [0.0])), 4),
        dates_used=[pd.Timestamp(index[p]).date().isoformat() for p in positions],
    )


def event_study_to_dict(r: EventStudyResult) -> dict:
    d = {
        "event_label": r.event_label, "sample_size": r.sample_size,
        "avg_move_1d_pct": r.avg_move_1d_pct, "avg_move_5d_pct": r.avg_move_5d_pct,
        "avg_move_20d_pct": r.avg_move_20d_pct, "positive_1d_rate": r.positive_1d_rate,
        "worst_5d_pct": r.worst_5d_pct, "best_5d_pct": r.best_5d_pct,
        "dates_used": r.dates_used,
        "reliability": "anecdotal" if r.sample_size < 5 else "suggestive" if r.sample_size < 12 else "meaningful_sample",
    }
    return d


# ---------------------------------------------------------------------------
# Geopolitical / market stress score
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def geopolitical_score(headlines: list[dict]) -> dict:
    """0-100 stress gauge from REAL recent headlines: how many carry
    geopolitics/policy keywords, plus their sentiment tilt (from the Phase 10
    lexicon). A risk *indicator* — explicitly not an outcome forecast."""
    from .news import score_text  # reuse the existing sentiment heuristic

    if not headlines:
        return {"score": None, "level": "unavailable", "headline_count": 0,
                "geopolitical_share": 0.0, "top_keywords": [],
                "note": "No headlines available — score not computed rather than guessed."}

    geo_count = 0
    sentiment_sum = 0.0
    keyword_hits: dict[str, int] = {}
    for item in headlines:
        title = (item.get("title") or "").lower()
        tokens = set(_tokens(title))
        # multi-word phrases checked on the raw string
        hit = any(k in tokens or k in title for k in GEOPOLITICAL_KEYWORDS)
        if hit:
            geo_count += 1
            for k in GEOPOLITICAL_KEYWORDS:
                if k in tokens or k in title:
                    keyword_hits[k] = keyword_hits.get(k, 0) + 1
        sentiment_sum += score_text(item.get("title") or "")["score"]

    n = len(headlines)
    geo_share = geo_count / n
    avg_sentiment = sentiment_sum / n
    # Map to 0-100: share of geopolitically salient headlines drives it,
    # negative sentiment among them pushes it higher.
    raw = geo_share * 60 + max(0.0, -avg_sentiment) * 40
    score = round(min(100.0, max(0.0, raw)), 1)
    level = "low" if score < 25 else "elevated" if score < 50 else "high" if score < 75 else "severe"
    top = sorted(keyword_hits.items(), key=lambda kv: -kv[1])[:8]
    return {
        "score": score, "level": level, "headline_count": n,
        "geopolitical_share": round(geo_share, 4),
        "average_news_sentiment": round(avg_sentiment, 4),
        "top_keywords": [k for k, _ in top],
        "note": "Risk indicator from real headline volume/sentiment — NOT a prediction of political outcomes.",
    }


def affected_assets(score_level: str) -> dict[str, list[str]]:
    """Which tracked asset groups historically react to geopolitical stress —
    a static, honest reference map, not a forecast."""
    return {
        "often_rises_on_stress": sorted(_GOLD_SENSITIVE),
        "often_falls_on_stress": ["equities (broad index)", "high-yield credit"],
        "energy_sensitive": sorted(_OIL_SENSITIVE),
        "note": "Historical tendencies only; individual events can break these patterns.",
    } if score_level in ("elevated", "high", "severe") else {
        "note": "Stress level low — no stress-asset rotation signal.",
    }
