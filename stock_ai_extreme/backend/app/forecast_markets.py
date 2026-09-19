"""Live, non-monetary forecast-market data from a public prediction source."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx


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


def _category(question: str, tags: list[Any]) -> str:
    text = f"{question} {' '.join(str(tag) for tag in tags)}".lower()
    rules = (
        ("Sports", ("sport", "match", "league", "tournament", "team", "championship")),
        ("Crypto", ("crypto", "bitcoin", "ethereum", "token", "defi")),
        ("Esports", ("esport", "gaming", "counter-strike", "league of legends")),
        ("Geopolitics", ("war", "ceasefire", "nato", "ukraine", "gaza", "diplomatic")),
        ("Politics", ("election", "president", "congress", "parliament", "prime minister", "vote")),
        ("Economy", ("inflation", "gdp", "interest rate", "jobs", "unemployment", "recession")),
        ("Tech", ("ai", "technology", "software", "iphone", "product launch")),
        ("Culture", ("movie", "music", "film", "award", "celebrity")),
    )
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
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
    if resolution:
        status = "RESOLVED"
    fetched_iso = (fetched_at or datetime.now(timezone.utc)).isoformat()
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
        "resolutionSource": None, "resolutionDate": str(raw.get("closedTime") or "") or None,
    }


async def fetch_markets(limit: int, timeout_seconds: float) -> list[dict[str, Any]]:
    params = {"active": "true", "closed": "false", "limit": max(1, min(limit, 100)), "order": "volume24hr", "ascending": "false"}
    async with httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": "NeuralMarket/2.3 forecast-analysis"}) as client:
        response = await client.get(GAMMA_MARKETS_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("markets", []) if isinstance(payload, dict) else []
    fetched_at = datetime.now(timezone.utc)
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if isinstance(raw, dict):
            market = normalize_market(raw, fetched_at)
            if market is not None:
                normalized.append(market)
    return normalized