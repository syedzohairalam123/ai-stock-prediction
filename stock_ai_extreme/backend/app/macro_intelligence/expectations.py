"""
Phase 23A — Real, sourced market-implied policy expectations.

Reads the live prediction-market prices for a central bank's upcoming policy
decision from Polymarket's public Gamma API (keyless) — the same public source
the forecast engine (``app.forecast_markets``) already reads. The traded price
of each directional contract *is* the market-implied probability: it is an
observed price, not a number generated from AI text or an arbitrary formula
(spec §2, §7).

For each bank the adapter finds its nearest open ``"<Bank> Decision in
<Month>?"`` event, aggregates the Yes prices of the directional contracts into
HIKE / CUT / UNCHANGED, and returns them with the observation timestamp, the
methodology and a source link. When no open market exists the caller keeps the
honest ``"Market-implied expectations unavailable."`` state — nothing is
invented.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("neural_market.macro_intelligence.expectations")

GAMMA_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
SOURCE_NAME = "Polymarket"

#: Per-bank search phrase and the event-title shape that identifies its
#: decision market. Kept here (not in a route) so the adapter is configurable
#: and independently testable.
BANK_MARKETS: dict[str, dict[str, str]] = {
    "FED": {
        "query": "fed decision",
        "title": r"(?:fed|federal reserve)\s+decision\s+in\s+\w+",
    },
    "BOJ": {
        "query": "bank of japan decision",
        "title": r"bank of japan\s+decision\s+in\s+\w+",
    },
}

# Word stems, not whole words: contracts are worded in the third person
# ("... increases/decreases interest rates ..."), so an exact \b increase \b
# test silently classified the Bank of Japan's hike contracts as neither.
_HIKE_RE = re.compile(r"\b(increas\w*|hik\w*|rais\w*)")
_CUT_RE = re.compile(r"\b(decreas\w*|cut\w*|lower\w*|reduc\w*)")
_HOLD_RE = re.compile(r"\b(no change|unchanged|hold\w*)")


@dataclass
class SourcedPolicyExpectation:
    """One real, source-reported market-implied expectation snapshot."""

    central_bank_id: str
    meeting_scheduled_at: datetime
    source: str
    observed_at: datetime
    expected_outcome: Optional[str]
    probability_hike: Optional[float]
    probability_cut: Optional[float]
    probability_unchanged: Optional[float]
    methodology: str
    source_url: str
    event_title: str


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


def _yes_price(raw: dict) -> Optional[float]:
    """The 'Yes' traded price (0–1) of a binary market, or None."""
    outcomes = _parse_array(raw.get("outcomes"))
    prices = _parse_array(raw.get("outcomePrices"))
    for outcome, price in zip(outcomes, prices):
        if str(outcome).strip().lower() == "yes":
            try:
                value = float(price)
            except (TypeError, ValueError):
                return None
            return value if 0.0 <= value <= 1.0 else None
    # Only when outcomes are unlabelled: fall back to the first price.
    if prices:
        try:
            value = float(prices[0])
        except (TypeError, ValueError):
            return None
        return value if 0.0 <= value <= 1.0 else None
    return None


def _classify(question: str) -> Optional[str]:
    """Map a contract's wording to a policy direction, or None if unclear."""
    text = question.lower()
    if _HOLD_RE.search(text):
        return "UNCHANGED"
    if _CUT_RE.search(text):
        return "CUT"
    if _HIKE_RE.search(text):
        return "HIKE"
    return None


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def aggregate_event(
    event: dict[str, Any], bank_id: str
) -> Optional[SourcedPolicyExpectation]:
    """Aggregate one decision event's contracts into a sourced expectation.

    Pure and offline-testable: it reads a Gamma event payload, never the
    network. Probability is the sum of the directional contracts' traded Yes
    prices in percent; no other outcome is added.
    """
    markets = [m for m in (event.get("markets") or []) if isinstance(m, dict)]
    hike = cut = unchanged = 0.0
    found = False
    for market in markets:
        direction = _classify(str(market.get("question") or ""))
        if direction is None:
            continue
        price = _yes_price(market)
        if price is None:
            continue
        found = True
        percent = price * 100.0
        if direction == "HIKE":
            hike += percent
        elif direction == "CUT":
            cut += percent
        else:
            unchanged += percent
    if not found:
        return None

    # The market's resolution date is the decision day.
    meeting_at = _parse_dt(event.get("endDate")) or datetime.now(timezone.utc)
    observed_at = _parse_dt(event.get("updatedAt")) or datetime.now(timezone.utc)

    totals = {"HIKE": hike, "CUT": cut, "UNCHANGED": unchanged}
    expected = max(totals, key=totals.get) if any(totals.values()) else None

    slug = str(event.get("slug") or "").strip()
    source_url = (
        f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
    )

    return SourcedPolicyExpectation(
        central_bank_id=bank_id,
        meeting_scheduled_at=meeting_at,
        source=SOURCE_NAME,
        observed_at=observed_at,
        expected_outcome=expected,
        probability_hike=round(hike, 4),
        probability_cut=round(cut, 4),
        probability_unchanged=round(unchanged, 4),
        methodology=(
            "Traded probability (Yes price) of each directional contract on "
            "Polymarket's public market; the central bank's official statement "
            "is named as the resolution source."
        ),
        source_url=source_url,
        event_title=str(event.get("title") or ""),
    )


async def _search_events(query: str, timeout: float) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "NeuralMarket/2.3 macro-intelligence"},
    ) as client:
        response = await client.get(
            GAMMA_SEARCH_URL, params={"q": query, "limit_per_type": 20}
        )
        response.raise_for_status()
        payload = response.json()
    events = payload.get("events") if isinstance(payload, dict) else None
    return [event for event in (events or []) if isinstance(event, dict)]


def select_nearest_event(
    events: list[dict[str, Any]], title_pattern: str, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """The nearest still-relevant open decision event, or None.

    ``now`` is injectable so the selection rule is unit-testable.
    """
    pattern = re.compile(title_pattern, re.IGNORECASE)
    now = now or datetime.now(timezone.utc)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for event in events:
        if event.get("closed"):
            continue
        if not pattern.search(str(event.get("title") or "")):
            continue
        end = _parse_dt(event.get("endDate"))
        if end is None:
            continue
        # Keep the nearest upcoming decision; allow a small grace window so a
        # market closing a few hours after the decision is still usable.
        if end < now - timedelta(days=3):
            continue
        candidates.append((end, event))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


async def fetch_policy_expectations(
    bank_id: str, timeout: float = 20.0
) -> list[SourcedPolicyExpectation]:
    """Nearest open decision market for ``bank_id`` as sourced expectations.

    Returns an empty list when the bank is not configured or no open market is
    reachable — never a fabricated probability.
    """
    config = BANK_MARKETS.get(bank_id.upper())
    if not config:
        return []
    try:
        events = await _search_events(config["query"], timeout)
    except Exception as exc:
        logger.warning("Polymarket search failed for %s: %s", bank_id, exc)
        return []

    event = select_nearest_event(events, config["title"])
    if event is None:
        logger.info("No open Polymarket decision market for %s", bank_id)
        return []

    expectation = aggregate_event(event, bank_id.upper())
    return [expectation] if expectation else []
