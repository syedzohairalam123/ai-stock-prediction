"""
Polymarket provider — live prediction-market probabilities from the public
Gamma API (https://gamma-api.polymarket.com), the same keyless endpoint Phase
14 already uses. Here the markets are normalized into *regional measurements*
of type ``MODEL`` with the market name in ``methodology`` so nobody can mistake
them for polls.

Honesty rules encoded here:

* ``probability`` is the market's own YES price — relayed verbatim.
* ``uncertainty`` stays ``None``: the source publishes no interval, so none
  may appear.
* Real activity figures (volume, liquidity, 24h volume) are relayed under
  ``activity`` — they are market volumes, never "support".
* A market that cannot be mapped to a region stays national (``region_id`` is
  ``None``); it is never forced onto a state.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .base import PoliticalDataProvider, ProviderResult
from ..config import political_settings
from ...logging_config import get_logger
from ..schemas import ForecastMeasurementSchema, MeasurementType
from .. import regions as region_registry

logger = get_logger("neural_market.political.providers.polymarket")

ELECTION_TOKENS = (
    "election", "senate", "house race", "governor", "midterm", "primary",
    "referendum", "parliament", "president of", "prime minister", "general election",
    "nomination", "runoff", "ballot",
)

#: Office detection → election_id naming (mirrors the FEC ids).
_OFFICE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bsenate\b", "SENATE"),
    (r"\bhouse\b|\bcongressional\b", "HOUSE"),
    (r"\bgovernor", "GOVERNOR"),
    (r"\bpresident\b", "PRESIDENT"),
    (r"\bparliament\b", "PARLIAMENT"),
    (r"\breferendum\b", "REFERENDUM"),
)


def _parse_array(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fips_note(state_code: str) -> str:
    identity = region_registry.BY_CODE.get(state_code)
    return identity.name if identity else state_code


def detect_us_state(text: str) -> Optional[str]:
    """USPS code of a US state explicitly named in ``text`` (name or code).

    A pure string join against the identity registry — never a guess: a state
    is matched only on its full official name (case-insensitive, word-bounded)
    or a word-bounded two-letter code followed by a word boundary.
    """
    upper = text.upper()
    for code, identity in region_registry.BY_CODE.items():
        if re.search(rf"\b{re.escape(identity.name.upper())}\b", upper):
            return code
    for code in region_registry.BY_CODE:
        if re.search(rf"\b{re.escape(code)}\b", upper):
            return code
    return None


def detect_country(text: str) -> Optional[str]:
    """ISO-3 code of a registry country explicitly named in ``text``."""
    upper = text.upper()
    for name in region_registry.COUNTRY_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", upper):
            return region_registry.COUNTRY_NAMES[name]
    return None


def derive_election_id(question: str, state_code: Optional[str], country_iso3: Optional[str]) -> Optional[str]:
    """Best-effort election key from the market's own words.

    Uses only what the question says (office keyword + 4-digit year + the
    mapped jurisdiction). When the question does not state a year the id keeps
    ``NA`` rather than guessing the current cycle.
    """
    text = question.lower()
    office = next((name for pattern, name in _OFFICE_PATTERNS if re.search(pattern, text)), None)
    if office is None:
        return None
    year_match = re.search(r"\b(19|20)\d{2}\b", question)
    year = year_match.group(0) if year_match else "NA"
    jurisdiction = state_code or country_iso3 or "US"
    is_us = state_code is not None or country_iso3 in (None, "USA")
    prefix = "US-" if is_us else ""
    return f"{prefix}{office}-{jurisdiction}-{year}"


def normalize_market(
    raw: Dict[str, Any],
    fetched_at: datetime,
    politics_only: bool = True,
) -> Optional[ForecastMeasurementSchema]:
    """One Gamma market → a MODEL measurement (or None when unusable/off-topic)."""
    outcomes = _parse_array(raw.get("outcomes"))
    prices = _parse_array(raw.get("outcomePrices"))
    if len(outcomes) < 2 or len(prices) < 2:
        return None
    indexed = {str(o).strip().upper(): _number(p) for o, p in zip(outcomes, prices)}
    yes = indexed.get("YES")
    if yes is None or not (0.0 <= yes <= 1.0):
        return None

    question = str(raw.get("question") or raw.get("groupItemTitle") or "").strip()
    market_id = str(raw.get("id") or "").strip()
    if not question or not market_id:
        return None

    description = str(raw.get("description") or "")
    haystack = f"{question} {str(raw.get('title') or '')} {description[:400]}"
    if politics_only and not any(token in haystack.lower() for token in ELECTION_TOKENS):
        return None

    slug = str(raw.get("slug") or "").strip()
    source_url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
    updated_at = _parse_dt(raw.get("updatedAt")) or fetched_at
    created_at = _parse_dt(raw.get("createdAt"))
    closed = bool(raw.get("closed"))
    resolved = closed and (
        (yes == 1.0 and _number(indexed.get("NO")) == 0.0)
        or (_number(indexed.get("NO")) == 1.0 and yes == 0.0)
    )

    state_code = detect_us_state(haystack)
    country_iso3 = None if state_code else detect_country(haystack)
    if state_code:
        region_id = f"us-state:{state_code}"
        jurisdiction_note = f"Matched to {_fips_note(state_code)} from the market's own wording."
    elif country_iso3:
        region_id = f"country:{country_iso3}"
        jurisdiction_note = f"Matched to country {country_iso3} from the market's own wording."
    else:
        region_id = None
        jurisdiction_note = "No jurisdiction matched; shown as national/global only."

    volume = _number(raw.get("volumeNum") if raw.get("volumeNum") is not None else raw.get("volume"))
    liquidity = _number(raw.get("liquidityNum") if raw.get("liquidityNum") is not None else raw.get("liquidity"))
    volume_24h = _number(raw.get("volume24hr"))
    activity: Dict[str, Any] = {}
    if volume is not None:
        activity["volume_usd"] = round(volume, 2)
    if liquidity is not None:
        activity["liquidity_usd"] = round(liquidity, 2)
    if volume_24h is not None:
        activity["volume_24h_usd"] = round(volume_24h, 2)
    activity["activity_basis"] = "Prediction-market trading volume reported by the source."

    candidate = str(raw.get("groupItemTitle") or "").strip() or question
    election_id = derive_election_id(question, state_code, country_iso3)

    return ForecastMeasurementSchema(
        id=f"polymarket:{market_id}",
        region_id=region_id,
        election_id=election_id,
        candidate_or_outcome=candidate,
        probability=round(yes * 100.0, 2),
        measurement_type=MeasurementType.MODEL,
        source="Polymarket (prediction market)",
        source_id="polymarket",
        source_url=source_url,
        measured_at=updated_at,
        updated_at=updated_at,
        retrieved_at=fetched_at,
        methodology=(
            "Implied probability read from prediction-market prices (YES token). "
            "A market price reflects trading activity, not opinion polling."
        ),
        population=None,
        sample_size=None,
        uncertainty=None,
        activity=activity or None,
        is_current=not closed,
        notes=(
            f"Market status: {'RESOLVED' if resolved else 'OPEN' if not closed else 'CLOSED'}. "
            f"{jurisdiction_note}"
        ),
    )


class PolymarketProvider(PoliticalDataProvider):
    """Prediction-market implied probabilities (measurement type MODEL)."""

    provider_id = "polymarket"
    name = "Polymarket public market data"
    kind = "Prediction market API"
    source_url = "https://gamma-api.polymarket.com/markets"
    description = "Live implied probabilities from a public prediction market, mapped to jurisdictions where the market names one."
    attribution = "Market data from Polymarket's public Gamma API."
    capabilities = frozenset({PoliticalDataProvider.CAP_REGIONAL_MEASUREMENTS, PoliticalDataProvider.CAP_SOURCES})

    def __init__(self) -> None:
        super().__init__()
        self._settings = political_settings

    async def get_regional_measurements(self) -> ProviderResult[ForecastMeasurementSchema]:
        async def _call() -> ProviderResult[ForecastMeasurementSchema]:
            return await self._fetch_markets()
        return await self.fetch(_call)

    async def _fetch_markets(self) -> ProviderResult[ForecastMeasurementSchema]:
        params = {
            "active": "true",
            "closed": "false",
            "limit": min(int(self._settings.polymarket_market_limit), 500),
            "order": "volumeNum",
            "ascending": "false",
        }
        fetched_at = datetime.now(timezone.utc)
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            headers={"User-Agent": self._settings.user_agent},
        ) as client:
            response = await client.get(f"{self._settings.polymarket_base_url}/markets", params=params)
            response.raise_for_status()
            payload = response.json()
        rows = payload if isinstance(payload, list) else (payload or {}).get("markets") or []

        measurements: List[ForecastMeasurementSchema] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = normalize_market(row, fetched_at)
            if normalized is not None:
                measurements.append(normalized)

        if not measurements:
            return ProviderResult(
                status=self.status,
                error="No election-related markets were open at fetch time.",
                fetched_at=fetched_at,
            )
        return ProviderResult(items=measurements, status=self.status, fetched_at=fetched_at)
