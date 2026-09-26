"""Live, non-monetary forecast-market data from a public prediction source."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .logging_config import get_logger

logger = get_logger("neural_market.forecast_markets")


GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
SOURCE_NAME = "Polymarket public market data"
CATEGORIES = ("Politics", "Sports", "Crypto", "Esports", "Finance", "Geopolitics", "Tech", "Culture", "Economy")


def _parse_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0 <= result <= 1 else None


def _float_or_none(value: Any) -> float | None:
    """Plain float passthrough for non-probability numbers (volumes)."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _category(question: str, tags: list[Any]) -> str:
    text = f"{question} {' '.join(str(tag) for tag in tags)}".lower()
    rules = (
        (
            "Sports",
            (
                "sport", "match", "league", "tournament", "team", "championship",
                "world cup", "nba", "nfl", "cricket", "football", "soccer",
                "tennis", "golf", "grand prix", "super bowl", "ashes",
            ),
        ),
        ("Crypto", ("crypto", "bitcoin", "ethereum", "token", "defi")),
        ("Esports", ("esport", "gaming", "counter-strike", "league of legends")),
        (
            "Geopolitics",
            (
                "war", "ceasefire", "nato", "ukraine", "gaza", "diplomatic",
                "blockade", "strait", "missile", "sanction", "sanctions",
                "military", "troops", "invasion", "conflict", "geopolit",
                "cease-fire", "border",
            ),
        ),
        ("Politics", ("election", "elections", "president", "congress", "parliament", "prime minister", "vote", "senate", "governor")),
        ("Economy", ("inflation", "gdp", "interest rate", "jobs", "unemployment", "recession")),
        ("Tech", ("ai", "technology", "software", "iphone", "product launch", "semiconductor")),
        ("Culture", ("movie", "music", "film", "award", "celebrity")),
    )
    # Word-boundary matching, not substring: the old ``"ai" in text`` rule
    # filed "Strait of Hormuz …" (and any "train", "paint", "email") under
    # Tech, while real geopolitics questions fell through to the Finance
    # fallback. A category decides which discovery feed an event lands in, so
    # it has to mean what it says.
    # `s?` so "sport" also matches "sports" and "match" matches "matches":
    # a word-boundary check with no plural tolerance silently missed every
    # plural tag the source actually publishes.
    for category, keywords in rules:
        if any(re.search(rf"\b{re.escape(keyword)}s?\b", text) for keyword in keywords):
            return category
    return "Finance"


def normalize_market(raw: dict[str, Any], fetched_at: datetime | None = None) -> dict[str, Any] | None:
    outcomes = _parse_array(raw.get("outcomes"))
    prices = _parse_array(raw.get("outcomePrices"))
    if len(outcomes) < 2 or len(prices) < 2:
        return None
    indexed = {str(outcome).strip().upper(): _number(price) for outcome, price in zip(outcomes, prices)}
    yes = indexed.get("YES")
    no = indexed.get("NO")
    if yes is None or no is None:
        return None

    question = str(raw.get("question") or raw.get("title") or "").strip()
    market_id = str(raw.get("id") or raw.get("conditionId") or "").strip()
    if not question or not market_id:
        return None
    observed_at = str(raw.get("updatedAt") or raw.get("createdAt") or (fetched_at or datetime.now(timezone.utc)).isoformat())
    source_url = str(raw.get("url") or raw.get("marketUrl") or "").strip()
    if not source_url:
        slug = str(raw.get("slug") or "").strip()
        source_url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
    closed = bool(raw.get("closed"))
    status = "CLOSED" if closed else "OPEN"
    resolution = raw.get("resolution") if raw.get("resolution") in ("YES", "NO") else None
    # Gamma sometimes reports the resolved outcome via `outcomePrices` (a fully
    # settled YES/NO price of 1/0) before `resolution` is populated. Reading it
    # lets a market show RESOLVED even when the explicit field lags.
    if resolution is None and closed:
        if indexed.get("YES") == 1.0 and indexed.get("NO") == 0.0:
            resolution = "YES"
        elif indexed.get("NO") == 1.0 and indexed.get("YES") == 0.0:
            resolution = "NO"
    if resolution:
        status = "RESOLVED"
    fetched_iso = (fetched_at or datetime.now(timezone.utc)).isoformat()
    # Phase 14.1 — the on-chain outcome-token ids. Index 0 is YES for a binary
    # market; the CLOB price-history API is keyed on these. Kept as a list of
    # strings; empty when gamma omits them (history is then unavailable rather
    # than guessed).
    clob_token_ids = [str(token) for token in _parse_array(raw.get("clobTokenIds")) if str(token).strip()]
    condition_id = str(raw.get("conditionId") or raw.get("condition_id") or "").strip()
    traders = raw.get("uniquePseudonymousTraders")
    participant_count = int(traders) if str(traders or "").isdigit() else None
    yes_percent = round(yes * 100, 2)
    no_percent = round(no * 100, 2)

    return {
        "id": market_id, "title": question,
        "description": str(raw.get("description") or "Probability observed from a public forecast market.").strip(),
        "category": _category(question, _parse_array(raw.get("tags"))), "status": status,
        "yesProbability": yes_percent, "noProbability": no_percent,
        "history": [{"timestamp": observed_at, "yesProbability": yes_percent, "noProbability": no_percent}],
        "closeTime": str(raw.get("endDate") or raw.get("end_date") or observed_at),
        "resolution": resolution,
        "sources": [{"name": SOURCE_NAME, "url": source_url, "publishedAt": observed_at, "verifiedAt": fetched_iso}],
        "createdAt": str(raw.get("createdAt") or observed_at), "updatedAt": observed_at,
        "dataMode": "LIVE", "updateCount": 1, "participantCount": participant_count,
        # Phase 19 — additive: the source's own 24h volume, kept as measured
        # (None when Gamma does not publish one — never defaulted to 0).
        "volume24hr": _float_or_none(raw.get("volume24hr")),
        "resolutionSource": None, "resolutionDate": str(raw.get("closedTime") or "") or None,
        # Phase 14.1/14.2 — additive fields the history + resolution engines use.
        "clobTokenIds": clob_token_ids, "conditionId": condition_id,
    }


async def _gamma_rows(params: dict[str, Any], timeout_seconds: float) -> list[dict[str, Any]]:
    """One Gamma request, normalized to a list of dict rows."""
    async with httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": "NeuralMarket/2.3 forecast-analysis"}) as client:
        response = await client.get(GAMMA_MARKETS_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("markets", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


async def fetch_markets(limit: int, timeout_seconds: float) -> list[dict[str, Any]]:
    params = {"active": "true", "closed": "false", "limit": max(1, min(limit, 100)), "order": "volume24hr", "ascending": "false"}
    rows = await _gamma_rows(params, timeout_seconds)
    fetched_at = datetime.now(timezone.utc)
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        market = normalize_market(raw, fetched_at)
        if market is not None:
            normalized.append(market)
    return normalized


async def fetch_market_by_id(market_id: str, timeout_seconds: float) -> dict[str, Any] | None:
    """Resolve one market directly from Gamma by id (then condition id, then slug).

    The active list is capped and only contains open markets, so a *closed*
    market's history or resolution could not be reached by scanning it. This
    queries Gamma by identity instead, which works for open and closed markets
    alike. Returns the normalized market, or None when nothing matches.
    """
    cleaned = str(market_id or "").strip()
    if not cleaned:
        return None
    fetched_at = datetime.now(timezone.utc)
    for params in (
        {"id": cleaned, "limit": 5},
        {"condition_ids": cleaned, "limit": 5},
        {"slug": cleaned, "limit": 5},
    ):
        try:
            rows = await _gamma_rows(params, timeout_seconds)
        except Exception as exc:
            logger.debug("gamma lookup %s failed: %s", params, exc)
            continue
        for raw in rows:
            market = normalize_market(raw, fetched_at)
            if market is not None and market.get("id") == cleaned:
                return market
        # Fall back to the first normalized row when Gamma returns a near match
        # (e.g. the id we stored was the conditionId while the row id differs).
        for raw in rows:
            market = normalize_market(raw, fetched_at)
            if market is not None:
                return market
    return None


async def fetch_closed_markets(limit: int, timeout_seconds: float) -> list[dict[str, Any]]:
    """Recently CLOSED/RESOLVED markets, newest first.

    Phase 14.2: the open-market query deliberately filters `closed=false`, so
    resolutions were never visible. This is the separate, lightweight query
    that sees them. `closed=true` markets carry `closedTime` and (usually)
    `resolution` once Gamma has settled them.
    """
    params = {
        "closed": "true",
        "limit": max(1, min(int(limit), 500)),
        "order": "closedTime",
        "ascending": "false",
    }
    rows = await _gamma_rows(params, timeout_seconds)
    fetched_at = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for raw in rows:
        market = normalize_market(raw, fetched_at)
        if market is not None:
            out.append(market)
    return out