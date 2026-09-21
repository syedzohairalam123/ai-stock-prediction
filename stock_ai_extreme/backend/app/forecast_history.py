"""
Phase 14.1 — real probability history for forecast markets.

Problem this solves
--------------------
`forecast_markets.normalize_market()` can only see one observation (the
current gamma price), so every market's `history` was a single point and
`updateCount` was always 1. The detail-page chart drew one dot.

What this module does
---------------------
Polymarket's Gamma payload carries `clobTokenIds` (the on-chain outcome-token
ids for a binary market; index 0 is YES). The public CLOB REST API then serves
the *real* traded price series for that token:

    GET {CLOB}/prices-history?market=<token_id>&interval=<window>&fidelity=<min>

Each row is ``{"t": <unix seconds>, "p": <price in 0..1>}`` — the actual
probability the market was pricing at that instant. This module fetches those
rows, normalizes them to the app's `{timestamp, yesProbability, noProbability}`
shape, downsamples when a window would exceed the point budget, and caches per
(token, interval, fidelity) for a short TTL.

Honesty rules
-------------
* A market with no `clobTokenIds`, or whose token has no traded history, returns
  an empty list — the caller must treat that as "history unavailable", never as
  "fill in a plausible curve".
* Prices outside `[0, 1]`, non-numeric rows and duplicate timestamps are
  dropped rather than coerced.
* No synthetic points are ever produced. `source` is always the real CLOB URL.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import settings
from .logging_config import get_logger

logger = get_logger("neural_market.forecast_history")

#: Base CLOB REST host (the prices-history path hangs off it).
CLOB_BASE_URL = "https://clob.polymarket.com"
CLOB_HISTORY_PATH = "/prices-history"

#: Range key -> CLOB `interval` window. `MAX`/`FULL` map to the full series.
RANGE_TO_INTERVAL: dict[str, str] = {
    "1D": "1d",
    "7D": "1w",
    "1M": "1m",
    "MAX": "max",
    "FULL": "max",
}

#: Upper bound on CLOB fidelity (minutes) so a huge window cannot ask for a
#: million rows. The API itself caps fidelity, but we clamp defensively.
_MAX_FIDELITY = 1440

#: (token_id, interval, fidelity) -> (expires_at_monotonic, points)
_cache: dict[str, tuple[float, list[dict[str, float]]]] = {}
_cache_lock = asyncio.Lock()


def _clob_base() -> str:
    return (settings.forecast_clob_url or CLOB_BASE_URL).rstrip("/")


def parse_array(value: Any) -> list[Any]:
    """Parse a gamma JSON-array-or-string field without ever raising."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def clob_token_ids(market: dict[str, Any] | None) -> list[str]:
    """The outcome token ids for a normalized market, or `[]` when absent."""
    if not market:
        return []
    return [str(token).strip() for token in parse_array(market.get("clobTokenIds")) if str(token).strip()]


def yes_token_id(market: dict[str, Any] | None) -> str | None:
    """First outcome token (YES for every binary market this app ingests)."""
    tokens = clob_token_ids(market)
    return tokens[0] if tokens else None


def _range_spec(range_key: str, fidelity_override: int | None) -> tuple[str, int]:
    """Resolve a range key to (CLOB interval, fidelity in minutes).

    Fidelity is chosen so each window stays readable: intraday asks for a fine
    grid, the full series for a coarse one. An explicit override always wins
    (clamped to the API's accepted range).
    """
    key = (range_key or "FULL").upper()
    interval = RANGE_TO_INTERVAL.get(key, "max")
    if fidelity_override is not None:
        fidelity = int(fidelity_override)
    elif interval == "1d":
        fidelity = min(settings.forecast_history_fidelity, 30)
    elif interval == "1w":
        fidelity = settings.forecast_history_fidelity
    elif interval == "1m":
        fidelity = min(settings.forecast_history_fidelity * 2, 240)
    else:
        fidelity = max(settings.forecast_history_fidelity, 180)
    return interval, max(1, min(fidelity, _MAX_FIDELITY))


async def _fetch_rows(token_id: str, interval: str, fidelity: int) -> list[dict[str, float]]:
    """Raw CLOB rows for one token/window, cached for the configured TTL."""
    cache_key = f"{token_id}|{interval}|{fidelity}"
    now = time.monotonic()

    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

    params = {"market": token_id, "interval": interval, "fidelity": str(fidelity)}
    url = f"{_clob_base()}{CLOB_HISTORY_PATH}"
    async with httpx.AsyncClient(
        timeout=settings.forecast_history_timeout_seconds,
        headers={"User-Agent": "NeuralMarket/2.3 forecast-history"},
    ) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    raw_rows = payload.get("history", []) if isinstance(payload, dict) else []
    cleaned: list[dict[str, float]] = []
    seen: set[int] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        try:
            ts = int(float(row.get("t")))
            price = float(row.get("p"))
        except (TypeError, ValueError):
            continue
        if ts <= 0 or ts in seen:
            continue
        if not 0.0 <= price <= 1.0:
            continue
        seen.add(ts)
        cleaned.append({"t": ts, "p": price})

    cleaned.sort(key=lambda r: r["t"])

    async with _cache_lock:
        _cache[cache_key] = (now + settings.forecast_history_cache_ttl_seconds, cleaned)
    return cleaned


def build_points(
    rows: list[dict[str, float]],
    *,
    max_points: int | None = None,
) -> list[dict[str, Any]]:
    """Normalize raw CLOB rows into the app's probability-point shape.

    Downsampling is deterministic (evenly spaced indices, last point always
    kept) so the same window always renders the same chart.
    """
    if not rows:
        return []

    budget = max_points if max_points is not None else settings.forecast_history_max_points
    budget = max(2, int(budget))

    selected = rows
    if len(rows) > budget:
        stride = (len(rows) - 1) / (budget - 1)
        picked: list[dict[str, float]] = []
        last_index = -1
        for i in range(budget):
            index = int(round(i * stride))
            if index == last_index:
                continue
            picked.append(rows[index])
            last_index = index
        if picked and picked[-1] is not rows[-1]:
            picked[-1] = rows[-1]
        selected = picked

    points: list[dict[str, Any]] = []
    for row in selected:
        yes = round(row["p"] * 100.0, 4)
        no = round((1.0 - row["p"]) * 100.0, 4)
        points.append(
            {
                "timestamp": datetime.fromtimestamp(row["t"], tz=timezone.utc).isoformat(),
                "yesProbability": yes,
                "noProbability": no,
            }
        )
    return points


async def fetch_market_history(
    market: dict[str, Any],
    *,
    range_key: str = "FULL",
    fidelity_override: int | None = None,
) -> dict[str, Any] | None:
    """Real traded probability series for one normalized market.

    Returns a payload the route can serialize directly, or `None` when the
    market carries no tradable token / the source is unreachable. An *empty
    point list* is a valid, honest answer (token exists but never traded).
    """
    token_id = yes_token_id(market)
    if not token_id:
        return None

    interval, fidelity = _range_spec(range_key, fidelity_override)
    try:
        rows = await _fetch_rows(token_id, interval, fidelity)
    except Exception as exc:  # network / 4xx / malformed payload
        logger.warning("clob history fetch failed for token %s: %s", token_id, exc)
        return None

    points = build_points(rows)
    generated_at = datetime.now(timezone.utc).isoformat()
    markets_url = str(market.get("sources", [{}])[0].get("url") or "") if market.get("sources") else ""
    return {
        "marketId": market.get("id"),
        "tokenId": token_id,
        "range": (range_key or "FULL").upper(),
        "interval": interval,
        "fidelityMinutes": fidelity,
        "points": points,
        "updateCount": len(points),
        "dataMode": "LIVE" if points else "UNAVAILABLE",
        "source": {
            "name": "Polymarket CLOB trade history",
            "url": f"{_clob_base()}{CLOB_HISTORY_PATH}?market={token_id}&interval={interval}&fidelity={fidelity}",
            "marketUrl": markets_url,
            "verifiedAt": generated_at,
        },
        "generatedAt": generated_at,
    }


def cache_key(token_id: str, interval: str, fidelity: int) -> str:
    return f"{token_id}|{interval}|{fidelity}"


async def purge_cache() -> int:
    """Drop expired cache entries. Called from the background maintenance loop."""
    now = time.monotonic()
    async with _cache_lock:
        expired = [key for key, (expires, _) in _cache.items() if expires <= now]
        for key in expired:
            _cache.pop(key, None)
    return len(expired)


def clear_cache() -> None:
    """Test helper — wipe the in-memory cache."""
    _cache.clear()
