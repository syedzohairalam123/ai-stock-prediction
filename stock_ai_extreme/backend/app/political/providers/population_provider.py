"""
Population context provider (spec §5: show "population where available").

Real sources only:

* **Countries** — World Bank API v2, indicator ``SP.POP.TOTL`` (keyless).
* **US states** — U.S. Census Bureau Population Estimates API, *only* when a
  key is configured (``POLITICAL_CENSUS_API_KEY``); the Census API rejects
  keyless traffic, and pretending otherwise would mean showing nothing and
  calling it data.

When no source is available the context reports ``source="unavailable"`` with
the reason — a missing number is shown as missing, never estimated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import httpx

from ..config import political_settings
from ...logging_config import get_logger
from ..schemas import PopulationContextSchema

logger = get_logger("neural_market.political.providers.population")

_WORLDBANK_NAMES: Dict[str, str] = {
    "USA": "United States",
    "CAN": "Canada",
    "MEX": "Mexico",
    "GBR": "United Kingdom",
    "FRA": "France",
    "DEU": "Germany",
    "ITA": "Italy",
    "ESP": "Spain",
    "NLD": "Netherlands",
    "BEL": "Belgium",
    "CHE": "Switzerland",
    "AUT": "Austria",
    "SWE": "Sweden",
    "NOR": "Norway",
    "DNK": "Denmark",
    "FIN": "Finland",
    "IRL": "Ireland",
    "POL": "Poland",
    "CZE": "Czechia",
    "SVK": "Slovakia",
    "HUN": "Hungary",
    "ROU": "Romania",
    "BGR": "Bulgaria",
    "GRC": "Greece",
    "TUR": "Turkey",
    "UKR": "Ukraine",
    "RUS": "Russia",
    "BLR": "Belarus",
    "MDA": "Moldova",
    "LTU": "Lithuania",
    "LVA": "Latvia",
    "EST": "Estonia",
    "SRB": "Serbia",
    "HRV": "Croatia",
    "BIH": "Bosnia and Herzegovina",
    "SVN": "Slovenia",
    "MKD": "North Macedonia",
    "ALB": "Albania",
    "MNE": "Montenegro",
    "CHN": "China",
    "IND": "India",
    "PAK": "Pakistan",
    "BGD": "Bangladesh",
    "LKA": "Sri Lanka",
    "NPL": "Nepal",
    "AFG": "Afghanistan",
    "IRN": "Iran",
    "IRQ": "Iraq",
    "ISR": "Israel",
    "PSE": "Palestine",
    "JOR": "Jordan",
    "SYR": "Syria",
    "LBN": "Lebanon",
    "SAU": "Saudi Arabia",
    "ARE": "United Arab Emirates",
    "QAT": "Qatar",
    "KWT": "Kuwait",
    "OMN": "Oman",
    "YEM": "Yemen",
    "EGY": "Egypt",
    "LBY": "Libya",
    "TUN": "Tunisia",
    "DZA": "Algeria",
    "MAR": "Morocco",
    "NGA": "Nigeria",
    "ETH": "Ethiopia",
    "KEN": "Kenya",
    "ZAF": "South Africa",
    "BRA": "Brazil",
    "ARG": "Argentina",
    "CHL": "Chile",
    "COL": "Colombia",
    "PER": "Peru",
    "VEN": "Venezuela",
    "ECU": "Ecuador",
    "BOL": "Bolivia",
    "URY": "Uruguay",
    "PRY": "Paraguay",
    "AUS": "Australia",
    "NZL": "New Zealand",
    "JPN": "Japan",
    "KOR": "South Korea",
    "PRK": "North Korea",
    "IDN": "Indonesia",
    "MYS": "Malaysia",
    "SGP": "Singapore",
    "PHL": "Philippines",
    "THA": "Thailand",
    "VNM": "Vietnam",
    "MMR": "Myanmar",
    "KAZ": "Kazakhstan",
    "UZB": "Uzbekistan",
    "TWN": "Taiwan",
}


def unavailable(reason: str) -> PopulationContextSchema:
    return PopulationContextSchema(
        population=None,
        as_of=None,
        source="unavailable",
        source_url=None,
        note=reason,
    )


class PopulationProvider:
    """Population context with per-source TTL caching and honest gaps."""

    def __init__(self) -> None:
        self._settings = political_settings
        self._country_cache: Dict[str, Tuple[datetime, PopulationContextSchema]] = {}
        self._state_cache: Dict[str, Tuple[datetime, PopulationContextSchema]] = {}

    # ------------------------------------------------------------------
    # World Bank (countries)
    # ------------------------------------------------------------------
    async def country_population(self, iso3: str) -> PopulationContextSchema:
        iso3 = (iso3 or "").upper()
        if not self._settings.enable_population_context:
            return unavailable("Population context disabled by configuration.")
        cached = self._country_cache.get(iso3)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < self._settings.population_cache_ttl_seconds:
            return cached[1]
        if iso3 not in _WORLDBANK_NAMES:
            context = unavailable(f"No World Bank population mapping for {iso3 or 'unknown country'}.")
            self._country_cache[iso3] = (datetime.now(timezone.utc), context)
            return context

        url = f"{self._settings.worldbank_population_url}/{iso3}/indicator/SP.POP.TOTL"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_seconds,
                headers={"User-Agent": self._settings.user_agent},
            ) as client:
                response = await client.get(url, params={"format": "json", "per_page": 5, "mrnev": 1})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            context = unavailable(f"World Bank API unavailable: {type(exc).__name__}")
            logger.debug("worldbank population failed for %s: %s", iso3, exc)
            self._country_cache[iso3] = (datetime.now(timezone.utc), context)
            return context

        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        context = unavailable("World Bank returned no population value.")
        for row in rows:
            if not isinstance(row, dict) or row.get("value") is None:
                continue
            try:
                value = int(float(row["value"]))
            except (TypeError, ValueError):
                continue
            context = PopulationContextSchema(
                population=value,
                as_of=str(row.get("date") or "") or None,
                source="World Bank Open Data (SP.POP.TOTL)",
                source_url="https://data.worldbank.org/indicator/SP.POP.TOTL",
                note=None,
            )
            break
        self._country_cache[iso3] = (datetime.now(timezone.utc), context)
        return context

    # ------------------------------------------------------------------
    # Census PEP (US states, key required)
    # ------------------------------------------------------------------
    async def state_population(self, fips: str) -> PopulationContextSchema:
        if not self._settings.enable_population_context:
            return unavailable("Population context disabled by configuration.")
        cached = self._state_cache.get(fips)
        if cached and (datetime.now(timezone.utc) - cached[0]).total_seconds() < self._settings.population_cache_ttl_seconds:
            return cached[1]
        context = await self._census_state_population(fips)
        self._state_cache[fips] = (datetime.now(timezone.utc), context)
        return context

    async def _census_state_population(self, fips: str) -> PopulationContextSchema:
        if not self._settings.census_api_key:
            return unavailable(
                "State population needs a U.S. Census API key (POLITICAL_CENSUS_API_KEY); "
                "no estimate is shown without one."
            )
        url = f"{self._settings.census_base_url}/data/2023/pep/population"
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.request_timeout_seconds,
                headers={"User-Agent": self._settings.user_agent},
            ) as client:
                response = await client.get(
                    url,
                    params={
                        "get": "NAME,POP_20230101,DATE_DESC",
                        "for": f"state:{fips}",
                        "key": self._settings.census_api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.debug("census population failed for fips %s: %s", fips, exc)
            return unavailable(f"Census API unavailable: {type(exc).__name__}")

        if not isinstance(payload, list) or len(payload) < 2:
            return unavailable("Census API returned no population row.")
        header = [str(column).upper() for column in payload[0]]
        pop_index = header.index("POP_20230101") if "POP_20230101" in header else None
        date_index = header.index("DATE_DESC") if "DATE_DESC" in header else None
        if pop_index is None:
            return unavailable("Census API response missing the expected population variable.")
        row = payload[1]
        try:
            value = int(float(row[pop_index]))
        except (TypeError, ValueError, IndexError):
            return unavailable("Census API population value unreadable.")
        return PopulationContextSchema(
            population=value,
            as_of=str(row[date_index]) if date_index is not None and row[date_index] else None,
            source="U.S. Census Bureau Population Estimates (PEP)",
            source_url="https://www.census.gov/programs-surveys/popest.html",
            note=None,
        )


__all__ = ["PopulationProvider", "unavailable", "_WORLDBANK_NAMES"]
