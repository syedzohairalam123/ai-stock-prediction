"""
Region registry for Phase 18 — the 50 US states + DC + the national level.

This module contains **identity data only** (codes, names, FIPS, statute-based
election dates). It contains **no political numbers of any kind**: no leanings,
no rankings, no forecast values, no colours. Identity facts (USPS codes, FIPS
codes, statutory election dates) come from public government references:

* USPS state codes / FIPS: U.S. Census Bureau state FIPS reference.
* Presidential/vice-presidential general election day: 3 U.S.C. §1 ("The
  Tuesday next after the first Monday in November").
* Inauguration day: 20th Amendment of the U.S. Constitution.
* Senate class cycle structure: U.S. Constitution, Article I, §3 (one third of
  senators chosen every second year, six-year terms).

Population context is NOT stored here — it is fetched live from the World Bank
API by the population provider, so this file can never go stale with numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass(frozen=True)
class StateIdentity:
    """Static identity facts for one US state (no political content)."""

    code: str          # USPS code, e.g. "OH"
    name: str          # official name, e.g. "Ohio"
    fips: str          # Census FIPS, e.g. "39"
    senate_class: int  # which class was last elected in 2024 (1, 2 or 3)
    governor_office: bool = True


#: USPS code → FIPS, and the Senate class most recently contested in 2024.
#: Senate classes: class 1 up in 2024+2030, class 2 in 2026+2032, class 3 in
#: 2028+2034 (staggered six-year terms per Art. I §3).
STATES: tuple[StateIdentity, ...] = (
    StateIdentity("AL", "Alabama", "01", 2),
    StateIdentity("AK", "Alaska", "02", 3),
    StateIdentity("AZ", "Arizona", "04", 1),
    StateIdentity("AR", "Arkansas", "05", 3),
    StateIdentity("CA", "California", "06", 1),
    StateIdentity("CO", "Colorado", "08", 3),
    StateIdentity("CT", "Connecticut", "09", 1),
    StateIdentity("DE", "Delaware", "10", 2),
    StateIdentity("FL", "Florida", "12", 1),
    StateIdentity("GA", "Georgia", "13", 3),
    StateIdentity("HI", "Hawaii", "15", 3),
    StateIdentity("ID", "Idaho", "16", 3),
    StateIdentity("IL", "Illinois", "17", 3),
    StateIdentity("IN", "Indiana", "18", 1),
    StateIdentity("IA", "Iowa", "19", 3),
    StateIdentity("KS", "Kansas", "20", 3),
    StateIdentity("KY", "Kentucky", "21", 2),
    StateIdentity("LA", "Louisiana", "22", 3),
    StateIdentity("ME", "Maine", "23", 1),
    StateIdentity("MD", "Maryland", "24", 1),
    StateIdentity("MA", "Massachusetts", "25", 1),
    StateIdentity("MI", "Michigan", "26", 2),
    StateIdentity("MN", "Minnesota", "27", 2),
    StateIdentity("MS", "Mississippi", "28", 1),
    StateIdentity("MO", "Missouri", "29", 1),
    StateIdentity("MT", "Montana", "30", 1),
    StateIdentity("NE", "Nebraska", "31", 1),
    StateIdentity("NV", "Nevada", "32", 3),
    StateIdentity("NH", "New Hampshire", "33", 3),
    StateIdentity("NJ", "New Jersey", "34", 2),
    StateIdentity("NM", "New Mexico", "35", 1),
    StateIdentity("NY", "New York", "36", 1),
    StateIdentity("NC", "North Carolina", "37", 3),
    StateIdentity("ND", "North Dakota", "38", 1),
    StateIdentity("OH", "Ohio", "39", 1),
    StateIdentity("OK", "Oklahoma", "40", 3),
    StateIdentity("OR", "Oregon", "41", 3),
    StateIdentity("PA", "Pennsylvania", "42", 1),
    StateIdentity("RI", "Rhode Island", "44", 1),
    StateIdentity("SC", "South Carolina", "45", 2),
    StateIdentity("SD", "South Dakota", "46", 3),
    StateIdentity("TN", "Tennessee", "47", 1),
    StateIdentity("TX", "Texas", "48", 1),
    StateIdentity("UT", "Utah", "49", 1),
    StateIdentity("VT", "Vermont", "50", 1),
    StateIdentity("VA", "Virginia", "51", 1),
    StateIdentity("WA", "Washington", "53", 1),
    StateIdentity("WV", "West Virginia", "54", 1),
    StateIdentity("WI", "Wisconsin", "55", 1),
    StateIdentity("WY", "Wyoming", "56", 1),
    StateIdentity("DC", "District of Columbia", "11", 2),
)

BY_CODE: Dict[str, StateIdentity] = {s.code: s for s in STATES}
BY_FIPS: Dict[str, StateIdentity] = {s.fips: s for s in STATES}
BY_NAME: Dict[str, StateIdentity] = {s.name.upper(): s for s in STATES}


def senate_class_up_for_election(year: int) -> int:
    """Which Senate class faces election in ``year``.

    Classes rotate with six-year terms: class 2 in 2026, class 1 in 2024/2030,
    class 3 in 2028/2034. Derived arithmetically so any year works.
    """
    return {0: 2, 2: 1, 4: 3}.get((int(year) - 2026) % 6, 2)


def general_election_day(year: int) -> Optional[date]:
    """US general election day: the Tuesday after the first Monday in
    November (3 U.S.C. §1). Computed, not guessed."""
    import datetime as _dt

    if year < 1845:
        return None
    first_monday = _dt.date(year, 11, 1)
    while first_monday.weekday() != 0:  # Monday == 0
        first_monday += _dt.timedelta(days=1)
    return first_monday + _dt.timedelta(days=1)


def is_midterm(year: int) -> bool:
    """Even years that are not presidential cycles are midterms."""
    return year % 2 == 0 and (year - 2024) % 4 != 0


def senate_states_up(year: int) -> List[str]:
    """USPS codes of the states whose class-2/3 seat faces election in ``year``."""
    wanted = {2026: 2, 2028: 3, 2030: 1, 2032: 2, 2034: 3, 2036: 1}.get(year, 2)
    return [s.code for s in STATES if s.senate_class == wanted]


def house_seats_by_state() -> Dict[str, int]:
    """Voting seats per state after the 2020 apportionment (Census 2020
    apportionment results — fixed until the 2030 census)."""
    return {
        "AL": 7, "AK": 1, "AZ": 9, "AR": 4, "CA": 52, "CO": 8, "CT": 5, "DE": 1,
        "FL": 28, "GA": 14, "HI": 2, "ID": 2, "IL": 17, "IN": 9, "IA": 4, "KS": 4,
        "KY": 6, "LA": 6, "ME": 2, "MD": 8, "MA": 9, "MI": 13, "MN": 8, "MS": 4,
        "MO": 8, "MT": 2, "NE": 3, "NV": 4, "NH": 2, "NJ": 12, "NM": 3, "NY": 26,
        "NC": 14, "ND": 1, "OH": 15, "OK": 5, "OR": 6, "PA": 17, "RI": 2, "SC": 7,
        "SD": 1, "TN": 9, "TX": 38, "UT": 4, "VT": 1, "VA": 11, "WA": 10, "WV": 2,
        "WI": 8, "WY": 1,
    }


def electoral_votes_by_state() -> Dict[str, int]:
    """Electoral votes for 2024–2028 (2020 census apportionment + DC's
    23rd-Amendment allocation). Identity arithmetic, not politics."""
    base = house_seats_by_state()
    votes = {code: seats + 2 for code, seats in base.items()}
    votes["DC"] = 3
    return votes


@dataclass(frozen=True)
class CountryIdentity:
    """Identity facts for one country shown on the geopolitical map."""

    iso3: str
    iso2: str
    name: str


#: Countries renderable by Plotly's built-in Natural Earth country geometry.
COUNTRIES: tuple[CountryIdentity, ...] = (
    CountryIdentity("USA", "US", "United States"),
    CountryIdentity("CAN", "CA", "Canada"),
    CountryIdentity("MEX", "MX", "Mexico"),
    CountryIdentity("GBR", "GB", "United Kingdom"),
    CountryIdentity("FRA", "FR", "France"),
    CountryIdentity("DEU", "DE", "Germany"),
    CountryIdentity("ITA", "IT", "Italy"),
    CountryIdentity("ESP", "ES", "Spain"),
    CountryIdentity("PRT", "PT", "Portugal"),
    CountryIdentity("NLD", "NL", "Netherlands"),
    CountryIdentity("BEL", "BE", "Belgium"),
    CountryIdentity("CHE", "CH", "Switzerland"),
    CountryIdentity("AUT", "AT", "Austria"),
    CountryIdentity("SWE", "SE", "Sweden"),
    CountryIdentity("NOR", "NO", "Norway"),
    CountryIdentity("DNK", "DK", "Denmark"),
    CountryIdentity("FIN", "FI", "Finland"),
    CountryIdentity("IRL", "IE", "Ireland"),
    CountryIdentity("POL", "PL", "Poland"),
    CountryIdentity("CZE", "CZ", "Czechia"),
    CountryIdentity("SVK", "SK", "Slovakia"),
    CountryIdentity("HUN", "HU", "Hungary"),
    CountryIdentity("ROU", "RO", "Romania"),
    CountryIdentity("BGR", "BG", "Bulgaria"),
    CountryIdentity("GRC", "GR", "Greece"),
    CountryIdentity("TUR", "TR", "Turkey"),
    CountryIdentity("UKR", "UA", "Ukraine"),
    CountryIdentity("RUS", "RU", "Russia"),
    CountryIdentity("BLR", "BY", "Belarus"),
    CountryIdentity("MDA", "MD", "Moldova"),
    CountryIdentity("LTU", "LT", "Lithuania"),
    CountryIdentity("LVA", "LV", "Latvia"),
    CountryIdentity("EST", "EE", "Estonia"),
    CountryIdentity("SRB", "RS", "Serbia"),
    CountryIdentity("HRV", "HR", "Croatia"),
    CountryIdentity("BIH", "BA", "Bosnia and Herzegovina"),
    CountryIdentity("SVN", "SI", "Slovenia"),
    CountryIdentity("MKD", "MK", "North Macedonia"),
    CountryIdentity("ALB", "AL", "Albania"),
    CountryIdentity("MNE", "ME", "Montenegro"),
    CountryIdentity("CHN", "CN", "China"),
    CountryIdentity("IND", "IN", "India"),
    CountryIdentity("PAK", "PK", "Pakistan"),
    CountryIdentity("BGD", "BD", "Bangladesh"),
    CountryIdentity("LKA", "LK", "Sri Lanka"),
    CountryIdentity("NPL", "NP", "Nepal"),
    CountryIdentity("AFG", "AF", "Afghanistan"),
    CountryIdentity("IRN", "IR", "Iran"),
    CountryIdentity("IRQ", "IQ", "Iraq"),
    CountryIdentity("ISR", "IL", "Israel"),
    CountryIdentity("PSE", "PS", "Palestine"),
    CountryIdentity("JOR", "JO", "Jordan"),
    CountryIdentity("SYR", "SY", "Syria"),
    CountryIdentity("LBN", "LB", "Lebanon"),
    CountryIdentity("SAU", "SA", "Saudi Arabia"),
    CountryIdentity("ARE", "AE", "United Arab Emirates"),
    CountryIdentity("QAT", "QA", "Qatar"),
    CountryIdentity("KWT", "KW", "Kuwait"),
    CountryIdentity("OMN", "OM", "Oman"),
    CountryIdentity("YEM", "YE", "Yemen"),
    CountryIdentity("EGY", "EG", "Egypt"),
    CountryIdentity("LBY", "LY", "Libya"),
    CountryIdentity("TUN", "TN", "Tunisia"),
    CountryIdentity("DZA", "DZ", "Algeria"),
    CountryIdentity("MAR", "MA", "Morocco"),
    CountryIdentity("NGA", "NG", "Nigeria"),
    CountryIdentity("ETH", "ET", "Ethiopia"),
    CountryIdentity("KEN", "KE", "Kenya"),
    CountryIdentity("ZAF", "ZA", "South Africa"),
    CountryIdentity("BRA", "BR", "Brazil"),
    CountryIdentity("ARG", "AR", "Argentina"),
    CountryIdentity("CHL", "CL", "Chile"),
    CountryIdentity("COL", "CO", "Colombia"),
    CountryIdentity("PER", "PE", "Peru"),
    CountryIdentity("VEN", "VE", "Venezuela"),
    CountryIdentity("ECU", "EC", "Ecuador"),
    CountryIdentity("BOL", "BO", "Bolivia"),
    CountryIdentity("URY", "UY", "Uruguay"),
    CountryIdentity("PRY", "PY", "Paraguay"),
    CountryIdentity("AUS", "AU", "Australia"),
    CountryIdentity("NZL", "NZ", "New Zealand"),
    CountryIdentity("JPN", "JP", "Japan"),
    CountryIdentity("KOR", "KR", "South Korea"),
    CountryIdentity("PRK", "KP", "North Korea"),
    CountryIdentity("IDN", "ID", "Indonesia"),
    CountryIdentity("MYS", "MY", "Malaysia"),
    CountryIdentity("SGP", "SG", "Singapore"),
    CountryIdentity("PHL", "PH", "Philippines"),
    CountryIdentity("THA", "TH", "Thailand"),
    CountryIdentity("VNM", "VN", "Vietnam"),
    CountryIdentity("MMR", "MM", "Myanmar"),
    CountryIdentity("KAZ", "KZ", "Kazakhstan"),
    CountryIdentity("UZB", "UZ", "Uzbekistan"),
    CountryIdentity("TWN", "TW", "Taiwan"),
)

BY_ISO3: Dict[str, CountryIdentity] = {c.iso3: c for c in COUNTRIES}
COUNTRY_NAMES: Dict[str, str] = {c.name.upper(): c.name for c in COUNTRIES}


def population_region_id_for_country(iso3: str) -> str:
    return f"country:{iso3}"


__all__ = [
    "StateIdentity",
    "STATES",
    "BY_CODE",
    "BY_FIPS",
    "BY_NAME",
    "senate_class_up_for_election",
    "general_election_day",
    "is_midterm",
    "senate_states_up",
    "house_seats_by_state",
    "electoral_votes_by_state",
    "CountryIdentity",
    "COUNTRIES",
    "BY_ISO3",
    "COUNTRY_NAMES",
    "population_region_id_for_country",
]
