"""
Phase 10 — news + headline sentiment.

Fetches recent headlines through the provider layer (yfinance's news feed,
the same channel as price data) and scores them with a small, dependency-free
lexicon. This is a deliberate, documented heuristic: it counts how many
positive/negative finance words appear in each headline and reports a score
in [-1, 1] plus a bullish/bearish/neutral label.

It is NOT a transformer/LLM sentiment model and is labelled as such in the
API response and UI — useful as a quick pulse check, not as a substitute
for proper NLP. Keep it dependency-free on purpose: nltk/vader/spacy are
heavy installs for a headline counter.
"""
from __future__ import annotations

import re

# Finance-flavoured word lists. Kept intentionally modest and unambiguous —
# a word like "cut" only counts in negative contexts here; words that are
# genuinely neutral in finance ("report", "quarter") are excluded entirely.
POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "surged", "soar", "soars", "soared",
    "rally", "rallies", "rallied", "gain", "gains", "gained", "rise", "rises",
    "rose", "jump", "jumps", "jumped", "climb", "climbs", "climbed", "up",
    "higher", "high", "record", "records", "best", "strong", "stronger",
    "strongest", "growth", "grow", "grows", "grew", "profit", "profits",
    "profitable", "earnings", "beat", "upgrade", "upgrades", "upgraded",
    "outperform", "outperforms", "outperformed", "bullish", "positive",
    "optimism", "optimistic", "recovery", "recover", "recovers", "recovered",
    "expansion", "expand", "expands", "expanded", "momentum", "opportunity",
    "opportunities", "win", "wins", "won", "winner", "boost", "boosts",
    "boosted", "improve", "improves", "improved", "improvement", "partnership",
    "partners", "launch", "launches", "launched", "milestone", "milestones",
    "breakthrough", "accelerate", "accelerates", "accelerated", "solid",
    "healthy", "robust", "buy", "buys", "bought", "double", "doubles",
    "doubled", "dividend", "dividends", "buyback", "buybacks", "raise",
    "raises", "raised", "guidance", "top", "tops", "topped", "breakout",
    "all-time", "highs", "highs", "growth", "impressive", "exceed", "exceeds",
    "exceeded", "record-high", "surging", "soaring", "jump", "jumps",
}

NEGATIVE_WORDS = {
    "fall", "falls", "fell", "fallen", "drop", "drops", "dropped", "plunge",
    "plunges", "plunged", "plummet", "plummets", "plummeted", "slump",
    "slumps", "slumped", "tumble", "tumbles", "tumbled", "crash", "crashes",
    "crashed", "decline", "declines", "declined", "down", "lower", "low",
    "lowest", "weak", "weaker", "weakest", "weakness", "miss", "misses",
    "missed", "downgrade", "downgrades", "downgraded", "sell", "sells",
    "sold", "bearish", "negative", "pessimism", "pessimistic", "loss",
    "losses", "lost", "lose", "lawsuit", "lawsuits", "sues", "sued", "sue",
    "probe", "probes", "investigation", "investigate", "investigated",
    "probe", "fine", "fines", "penalty", "penalties", "layoff", "layoffs",
    "fired", "fire", "cut", "cuts", "cutting", "reduced", "reduce", "reduces",
    "shrink", "shrinks", "shrank", "debt", "debts", "default", "defaults",
    "defaulted", "bankruptcy", "bankrupt", "fraud", "fraudulent", "risk",
    "risks", "risky", "warn", "warns", "warned", "warning", "warnings",
    "concern", "concerns", "worried", "worry", "worries", "uncertainty",
    "recession", "inflation", "correction", "volatile", "volatility",
    "trouble", "troubles", "struggle", "struggles", "struggled", "sluggish",
    "disappoint", "disappoints", "disappointed", "disappointing", "underperform",
    "underperforms", "underperformed", "worst", "collapse", "collapses",
    "collapsed", "halt", "halts", "halted", "suspend", "suspends", "suspended",
    "delist", "delisted", "violation", "violations", "violates", "charges",
    "charged", "indictment", "indicted", "scandal", "scandals", "shortfall",
    "shortfalls", "headwind", "headwinds", "drag", "drags", "dragged",
    "fear", "fears", "panic", "selloff", "sell-offs", "bloodbath",
}

_WORD_RE = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def score_text(text: str) -> dict:
    """Sentiment of one headline: score in [-1, 1] (positive share minus
    negative share), a label, and the raw word counts. 0.0 when the text
    contains no lexicon words — reported as neutral, not as an error."""
    tokens = _tokens(text)
    pos = sum(1 for t in tokens if t in POSITIVE_WORDS)
    neg = sum(1 for t in tokens if t in NEGATIVE_WORDS)
    denom = pos + neg
    score = round((pos - neg) / denom, 4) if denom else 0.0
    label = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
    return {"score": score, "label": label, "positive_words": pos, "negative_words": neg}


def analyze_news(items: list[dict]) -> dict:
    """Score every headline and roll up an aggregate. `items` are the
    normalized headlines from the provider layer. Always returns a well-formed
    structure, even for an empty feed (aggregate all zeros, no items)."""
    scored = [{**item, "sentiment": score_text(item.get("title") or "")} for item in items]
    total = len(scored)
    if total == 0:
        aggregate = {
            "total": 0, "average_score": 0.0, "label": "neutral",
            "bullish_count": 0, "bearish_count": 0, "neutral_count": 0,
        }
    else:
        labels = [s["sentiment"]["label"] for s in scored]
        average = round(sum(s["sentiment"]["score"] for s in scored) / total, 4)
        aggregate = {
            "total": total,
            "average_score": average,
            "label": "bullish" if average > 0.15 else "bearish" if average < -0.15 else "neutral",
            "bullish_count": labels.count("bullish"),
            "bearish_count": labels.count("bearish"),
            "neutral_count": labels.count("neutral"),
        }
    return {
        "items": scored,
        "aggregate": aggregate,
        "disclaimer": "Lexicon-based headline sentiment heuristic, not a professional NLP model and not investment advice.",
    }