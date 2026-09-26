"""
OpenFEC provider — the Federal Election Commission's public REST API
(https://api.open.fec.gov). Works with the documented ``DEMO_KEY`` and honours
a personal api.data.gov key when configured (``POLITICAL_FEC_API_KEY``).

What this provider contributes (all real, all attributed):

* ``get_events()`` — the official federal election calendar
  (``/election-dates/``): one row per state/office/election-type with the FEC's
  own date. No date is ever guessed; when the FEC row has no date the event
  carries ``election_date=None`` and the UI says "date unavailable".

The provider never looks at candidates' positions, parties' prospects or any
poll-like quantity — it is a calendar, nothing more.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .base import PoliticalDataProvider, ProviderResult
from ..config import political_settings
from ...logging_config import get_logger
from ..schemas import PoliticalCategory, PoliticalEventSchema, SourceStatus
from .. import regions as region_registry

logger = get_logger("neural_market.political.providers.openfec")

OFFICE_NAMES = {"P": "Presidential", "S": "Senate", "H": "House"}


def _parse_date(value: Any) -> Optional[datetime]:
    """FEC returns plain dates (``2026-11-03``) — parsed as UTC midnight."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(text.split("T")[0] if "T" in text and fmt != "%Y-%m-%dT%H:%M:%S" else text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def normalize_election_date_row(row: Dict[str, Any], retrieved_at: datetime) -> Optional[PoliticalEventSchema]:
    """One ``/election-dates/`` row → a calendar event (or None if unusable).

    Identity note: the live production API's ``/election-dates/`` rows do **not**
    carry a ``trc_election_id`` (an earlier code revision required it, which
    silently dropped every row and left the calendar permanently empty). A
    stable id is therefore derived from the row's own facts instead, falling
    back to the API id only when one is actually present.
    """
    trc_id = str(row.get("trc_election_id") or row.get("election_id") or "").strip()
    office = str(row.get("office_sought") or row.get("office") or "").strip().upper()
    state = str(row.get("election_state") or "").strip().upper()
    year = row.get("election_year")
    election_type = str(
        row.get("election_type_full")
        or row.get("election_type")
        or row.get("election_description")
        or row.get("election_type_id")
        or ""
    ).strip()
    district = str(row.get("election_district") or "").strip()
    election_date = _parse_date(row.get("election_date"))

    if office not in OFFICE_NAMES:
        return None

    identity = trc_id or "|".join([
        office,
        state or "US",
        str(year or "NA"),
        election_type or "NA",
        district or "NA",
        election_date.isoformat() if election_date else "no-date",
    ])

    office_name = OFFICE_NAMES[office]
    state_name = region_registry.BY_CODE.get(state).name if state in region_registry.BY_CODE else (state or None)
    year_text = str(year or "").strip()
    title_parts = [part for part in (f"{year_text} US" if year_text else "US", election_type.title() if election_type else "General", f"{office_name} election") if part]
    name = " — ".join([" ".join(title_parts), state_name]) if state_name else " ".join(title_parts)

    status = "SCHEDULED"
    if election_date is not None and election_date < datetime.now(timezone.utc):
        status = "RESOLVED"

    election_id = f"US-{office_name.upper()}-{state or 'US'}-{year_text or 'NA'}"

    return PoliticalEventSchema(
        id=f"fec:{identity}",
        name=name,
        jurisdiction=state or None,
        jurisdiction_type="STATE" if state else "NATIONAL",
        election_date=election_date,
        election_date_basis="FEC official election dates (api.open.fec.gov /election-dates/)",
        category=PoliticalCategory.ELECTION,
        source="Federal Election Commission (OpenFEC)",
        source_id="fec",
        source_url=f"{political_settings.fec_base_url}/election-dates/",
        updated_at=_parse_date(row.get("update_date")) or _parse_date(row.get("create_date")),
        retrieved_at=retrieved_at,
        status=status,
        office=office_name,
        election_id=election_id,
        country="US",
        region_ids=[f"us-state:{state}"] if state else [],
        notes=str(row.get("election_notes") or "").strip() or None,
    )


class OpenFECProvider(PoliticalDataProvider):
    """Federal election calendar straight from the FEC."""

    provider_id = "fec"
    name = "Federal Election Commission (OpenFEC)"
    kind = "Government API"
    source_url = "https://api.open.fec.gov/developers/"
    description = "Official US federal election dates and offices from the FEC."
    attribution = "Federal Election Commission, api.open.fec.gov (public domain / U.S. Government work)"
    requires_key = True
    capabilities = frozenset({PoliticalDataProvider.CAP_EVENTS, PoliticalDataProvider.CAP_SOURCES})

    def __init__(self) -> None:
        super().__init__()
        self._settings = political_settings

    def key_configured(self) -> bool:
        return bool(self._settings.fec_api_key)

    async def get_events(self) -> ProviderResult[PoliticalEventSchema]:
        async def _call() -> ProviderResult[PoliticalEventSchema]:
            return await self._fetch_calendar()
        return await self.fetch(_call)

    async def _fetch_calendar(self) -> ProviderResult[PoliticalEventSchema]:
        params: Dict[str, Any] = {
            "api_key": self._settings.fec_api_key,
            "sort": "election_date",
            "per_page": 100,
        }
        events: List[PoliticalEventSchema] = []
        seen: set[str] = set()
        fetched_at = datetime.now(timezone.utc)
        last_error: Optional[str] = None

        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            headers={"User-Agent": self._settings.user_agent},
        ) as client:
            for cycle in self._settings.current_cycles:
                page = 1
                while page <= 5:  # bounded pagination: 5 pages x 100 rows is plenty
                    try:
                        response = await client.get(
                            f"{self._settings.fec_base_url}/election-dates/",
                            params={**params, "election_year": cycle, "page": page},
                        )
                        response.raise_for_status()
                        payload = response.json()
                    except httpx.HTTPStatusError as exc:
                        code = exc.response.status_code
                        if code == 403:
                            return ProviderResult(
                                status=SourceStatus.UNAVAILABLE,
                                error=(
                                    "FEC API rejected the key (403). Set "
                                    "POLITICAL_FEC_API_KEY to a personal api.data.gov key."
                                ),
                                fetched_at=fetched_at,
                            )
                        # 429 (DEMO_KEY is heavily rate-limited) or any other
                        # upstream error: stop paginating but keep the rows we
                        # already collected — a 429 on page 2 must not discard
                        # page 1's real calendar rows.
                        last_error = (
                            f"FEC rate-limited or errored (HTTP {code}) with the configured key; "
                            "set POLITICAL_FEC_API_KEY for a higher quota."
                        )
                        break
                    results = (payload or {}).get("results") or []
                    if not results:
                        break
                    for row in results:
                        if not isinstance(row, dict):
                            continue
                        event = normalize_election_date_row(row, fetched_at)
                        if event is not None and event.id not in seen:
                            seen.add(event.id)
                            events.append(event)
                    pagination = (payload or {}).get("pagination") or {}
                    total_pages = int(pagination.get("pages") or 1)
                    if page >= total_pages:
                        break
                    page += 1

        if not events:
            return ProviderResult(
                status=SourceStatus.UNAVAILABLE if last_error else self.status,
                error=last_error or (
                    "FEC returned no usable election-date rows for the configured cycles."
                ),
                fetched_at=fetched_at,
            )
        events.sort(key=lambda e: (e.election_date is None, e.election_date or datetime.max.replace(tzinfo=timezone.utc), e.name))
        return ProviderResult(items=events, status=self.status, fetched_at=fetched_at)
