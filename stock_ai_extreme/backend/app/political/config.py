"""
Configuration for Phase 18 — Political & Geopolitical Data Mapping /
Forecast Visualization.

This phase is strictly **informational and neutral**: the backend only relays
measurements that an external source actually published. Every threshold here
governs *presentation* (freshness, conflict labelling, cache lifetimes) — none
of them can manufacture a political number.

Environment variables are prefixed with ``POLITICAL_`` (e.g.
``POLITICAL_FEC_API_KEY=...``). All network sources are public; the FEC key
defaults to the documented ``DEMO_KEY`` and can be upgraded to a personal
api.data.gov key without any code change.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PoliticalSettings(BaseSettings):
    """Settings for the Phase 18 political/geopolitical visualization module."""

    model_config = SettingsConfigDict(
        env_prefix="POLITICAL_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Provider toggles (each can be switched off independently)
    # ------------------------------------------------------------------
    enable_fec: bool = True
    enable_polymarket: bool = True
    enable_medsl_history: bool = True
    enable_gdelt: bool = True
    enable_population_context: bool = True

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    request_timeout_seconds: float = Field(default=20.0, ge=2.0, le=120.0)
    #: OpenFEC requires an api.data.gov key; DEMO_KEY is the documented public
    #: fallback with a low rate limit. Set POLITICAL_FEC_API_KEY for production.
    fec_api_key: str = "DEMO_KEY"
    fec_base_url: str = "https://api.open.fec.gov/v1"
    polymarket_base_url: str = "https://gamma-api.polymarket.com"
    #: MEDSL "U.S. President 1976–2024" on Harvard Dataverse (MIT Election Data
    #: and Science Lab). The concrete file id is resolved at runtime through the
    #: Dataverse API — never baked in.
    medsl_dataset_doi: str = "doi:10.7910/DVN/42MVDX"
    medsl_dataverse_base_url: str = "https://dataverse.harvard.edu/api"
    medsl_expected_filename: str = "1976-2024-president.csv"
    #: GDELT DOC 2.0 API asks for no more than one request every 5 seconds.
    gdelt_doc_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_min_request_interval_seconds: float = Field(default=5.5, ge=1.0, le=120.0)
    gdelt_max_records: int = Field(default=75, ge=5, le=250)
    gdelt_timespan_days: int = Field(default=3, ge=1, le=30)
    #: Default GDELT query. Purely a *retrieval* filter: it decides which
    #: coverage is downloaded, never what an article says.
    gdelt_default_query: str = (
        '(election OR referendum OR parliament OR "government" OR "policy") sourcelang:eng'
    )
    worldbank_population_url: str = "https://api.worldbank.org/v2/country"
    #: Optional U.S. Census API key — needed only for state-level population
    #: context (the Census API rejects keyless traffic; absence is reported,
    #: never estimated around).
    census_api_key: Optional[str] = None
    census_base_url: str = "https://api.census.gov"
    user_agent: str = "NeuralMarket/2.3 political-visualization (informational)"

    # ------------------------------------------------------------------
    # Caches (measurements change slowly; we still stay bounded)
    # ------------------------------------------------------------------
    events_cache_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    measurements_cache_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    historical_cache_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    timeline_cache_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    regions_cache_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    population_cache_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    medsl_disk_cache_hours: int = Field(default=168, ge=1, le=2160)
    medsl_cache_dir: str = "data/political"

    # ------------------------------------------------------------------
    # Freshness / staleness presentation (map data states)
    # ------------------------------------------------------------------
    #: A measurement younger than this keeps a region AVAILABLE.
    freshness_window_days: int = Field(default=14, ge=1, le=365)
    #: A measurement older than this is presented as outdated.
    stale_after_days: int = Field(default=45, ge=1, le=730)

    # ------------------------------------------------------------------
    # Conflict presentation
    # ------------------------------------------------------------------
    #: Two sources describing the same region/election/outcome with a larger
    #: gap than this are flagged CONTESTED — both are still shown side by side.
    conflict_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    #: Maximum measurements returned per region detail panel.
    max_measurements_per_region: int = Field(default=200, ge=10, le=2000)
    max_events: int = Field(default=200, ge=10, le=2000)
    max_timeline_events: int = Field(default=150, ge=10, le=1000)
    #: How many Polymarket markets are inspected per refresh (bounded fetch).
    polymarket_market_limit: int = Field(default=200, ge=10, le=1000)
    #: Election cycles considered "current" for the default view (e.g. 2026).
    current_cycles: List[int] = Field(default_factory=lambda: [2026])

    # ------------------------------------------------------------------
    # GDELT category rules (rule-based classification, always labelled)
    # ------------------------------------------------------------------
    event_category_rules: dict = Field(
        default_factory=lambda: {
            "ELECTION": ("election", "ballot", "midterm", "primary", "poll", "vote", "parliament", "senate", "governor"),
            "REFERENDUM": ("referendum", "plebiscite", "ballot measure", "initiative"),
            "GOVERNMENT": ("parliament", "cabinet", "minister", "government", "coalition", "legislature", "senate passes", "house passes"),
            "POLICY": ("policy", "sanction", "treaty", "regulation", "law", "bill", "executive order", "tariff"),
            "INTERNATIONAL": ("nato", "united nations", "summit", "diplomat", "embassy", "bilateral", "un security"),
            "CONFLICT": ("war", "ceasefire", "military", "strike", "border", "conflict", "troops"),
        }
    )


political_settings = PoliticalSettings()
