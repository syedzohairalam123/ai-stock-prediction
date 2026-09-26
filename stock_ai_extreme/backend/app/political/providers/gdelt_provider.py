"""
GDELT provider — geopolitical event coverage from the GDELT Project's DOC 2.0
API (https://api.gdeltproject.org/api/v2/doc/doc), a free, keyless global news
index.

What arrives here is *coverage*: title, publisher domain, publication
timestamp and the source country GDELT attaches to each article. The provider
normalizes those verbatim and is explicit about what is derived:

* ``category`` — rule-based keyword classification, always disclosed via
  ``classification_basis="RULE_BASED"``.
* ``location`` — GDELT's own ``sourcecountry`` field, disclosed via
  ``location_basis="SOURCE_FIELD"`` (it is the country of the publisher, and
  the UI labels it exactly that way — it is not claimed to be the event site).
* ``affected_regions`` — word-bounded mention detection against the region
  registry, disclosed as rule-based.

The API allows one request every ~5 seconds: an asyncio lock + monotonic
timestamp enforces the published limit, and 429s back off instead of hammering.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import PoliticalDataProvider, ProviderResult
from ..config import political_settings
from ...logging_config import get_logger
from ..schemas import PoliticalCategory, TimelineEventSchema
from .. import regions as region_registry

logger = get_logger("neural_market.political.providers.gdelt")

_SEENDATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$")


def parse_seen_date(value: Any) -> Optional[datetime]:
    """GDELT's ``seendate`` format: ``20260920T114500Z``."""
    if not value:
        return None
    match = _SEENDATE_RE.match(str(value).strip())
    if not match:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None


def classify_category(title: str) -> PoliticalCategory:
    """Rule-based keyword classification from the module's configured rules."""
    lowered = (title or "").lower()
    for category_name, keywords in political_settings.event_category_rules.items():
        if any(keyword in lowered for keyword in keywords):
            try:
                return PoliticalCategory(category_name)
            except ValueError:
                continue
    return PoliticalCategory.OTHER


def detect_affected_regions(text: str) -> List[str]:
    """Region ids for jurisdictions explicitly named in ``text``.

    Word-bounded matching against the identity registries — the same honest
    join the Polymarket provider uses, never a fuzzy guess.
    """
    upper = f" {text.upper()} "
    found: List[str] = []
    for code, identity in region_registry.BY_CODE.items():
        # The two-letter code must be genuinely uppercase in the source text;
        # matching the uppercased copy would tag every "in"/"or"/"me" as a US
        # state and pollute the affected-regions list with false positives.
        if re.search(rf"\b{re.escape(identity.name.upper())}\b", upper) or re.search(rf"\b{re.escape(code)}\b", text):
            found.append(f"us-state:{code}")
    for name in region_registry.COUNTRY_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", upper):
            iso3 = next(c.iso3 for c in region_registry.COUNTRIES if c.name == region_registry.COUNTRY_NAMES[name])
            found.append(f"country:{iso3}")
    return found


def normalize_article(
    row: Dict[str, Any],
    fetched_at: datetime,
) -> Optional[TimelineEventSchema]:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    seen = parse_seen_date(row.get("seendate")) or fetched_at
    if not title or not url:
        return None
    domain = str(row.get("domain") or "").strip()
    source_country = str(row.get("sourcecountry") or "").strip()
    event_id = hashlib.sha1(f"{url}|{row.get('seendate') or ''}".encode("utf-8", "replace")).hexdigest()[:24]
    category = classify_category(title)
    affected = detect_affected_regions(title)
    return TimelineEventSchema(
        id=f"gdelt:{event_id}",
        timestamp=seen,
        title=title,
        url=url,
        source=domain or "Unknown publisher (GDELT index)",
        source_url=url,
        category=category,
        classification_basis="RULE_BASED",
        location=source_country or None,
        location_basis="SOURCE_FIELD" if source_country else None,
        affected_regions=affected,
        language=str(row.get("language") or "").strip() or None,
        notes=(
            "Coverage located by GDELT's source-country field; region mentions "
            "detected by word match are labelled rule-based."
        ),
    )


class GdeltProvider(PoliticalDataProvider):
    """Global political/geopolitical coverage timeline (GDELT DOC 2.0)."""

    provider_id = "gdelt"
    name = "GDELT Project — DOC 2.0 API"
    kind = "News index API"
    source_url = "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/"
    description = "Global news coverage of elections, referendums, governments and policy, with publisher and timestamp."
    attribution = "The GDELT Project (gdeltproject.org) — coverage index used for informational timelines."
    capabilities = frozenset({PoliticalDataProvider.CAP_TIMELINE, PoliticalDataProvider.CAP_SOURCES})

    def __init__(self) -> None:
        super().__init__()
        self._settings = political_settings
        self._rate_lock = asyncio.Lock()
        self._last_request_monotonic: float = 0.0

    async def _respect_rate_limit(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_monotonic
            minimum = self._settings.gdelt_min_request_interval_seconds
            if elapsed < minimum:
                await asyncio.sleep(minimum - elapsed)
            self._last_request_monotonic = time.monotonic()

    async def get_timeline(self, query: Optional[str] = None) -> ProviderResult[TimelineEventSchema]:
        async def _call() -> ProviderResult[TimelineEventSchema]:
            return await self._fetch_timeline(query)
        return await self.fetch(_call)

    async def _fetch_timeline(self, query: Optional[str]) -> ProviderResult[TimelineEventSchema]:
        fetched_at = datetime.now(timezone.utc)
        timespan = f"{self._settings.gdelt_timespan_days}d"
        await self._respect_rate_limit()
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            headers={"User-Agent": self._settings.user_agent},
        ) as client:
            response = await client.get(
                self._settings.gdelt_doc_url,
                params={
                    "query": query or self._settings.gdelt_default_query,
                    "mode": "artlist",
                    "maxrecords": self._settings.gdelt_max_records,
                    "format": "json",
                    "timespan": timespan,
                    "sort": "datedesc",
                },
            )
            if response.status_code == 429:
                return ProviderResult(
                    status=self.status,
                    error="GDELT rate limit hit (429); retry after the published 5-second interval.",
                    fetched_at=fetched_at,
                )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                return ProviderResult(
                    status=self.status,
                    error="GDELT returned a non-JSON body (likely a rate-limit notice).",
                    fetched_at=fetched_at,
                )

        rows = (payload or {}).get("articles") if isinstance(payload, dict) else None
        if rows is None and isinstance(payload, list):
            rows = payload
        events: List[TimelineEventSchema] = []
        seen_ids: set[str] = set()
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            event = normalize_article(row, fetched_at)
            if event is not None and event.id not in seen_ids:
                seen_ids.add(event.id)
                events.append(event)
        if not events:
            return ProviderResult(
                status=self.status,
                error="GDELT returned no parseable coverage for the query window.",
                fetched_at=fetched_at,
            )
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return ProviderResult(items=events, status=self.status, fetched_at=fetched_at)

    async def get_sources(self) -> List[Dict[str, Any]]:
        """Publishers actually present in the last fetch (real domains only)."""
        return []
