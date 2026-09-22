"""
MEDSL provider — historical US presidential returns by state from the MIT
Election Data and Science Lab dataset "U.S. President 1976–2024" on Harvard
Dataverse (doi:10.7910/DVN/42MVDX).

This is the ``HISTORICAL_RESULT`` measurement family:

* The concrete CSV file is **resolved at runtime** through the Dataverse API
  (dataset metadata → file id by filename) — no file id is baked in, so the
  dataset can be versioned upstream without breaking this provider.
* The CSV is cached on disk under ``POLITICAL_MEDSL_CACHE_DIR`` for
  ``POLITICAL_MEDSL_DISK_CACHE_HOURS``; a stale/expired cache is refetched and
  a corrupt one is discarded (never parsed as if it were valid).
* Vote shares are real divisions of the dataset's own columns
  (``candidatevotes / totalvotes``). Nothing is estimated, and rows whose
  denominator is missing are dropped, not imputed.

Spec §16: this is the pandas-based cleaning/aggregation/historical-analysis
component of the phase.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .base import PoliticalDataProvider, ProviderResult
from ..config import political_settings
from ...logging_config import get_logger
from ..schemas import ForecastMeasurementSchema, MeasurementType
from .. import regions as region_registry

logger = get_logger("neural_market.political.providers.medsl")

PRESIDENTIAL_YEARS = tuple(range(1976, 2029, 4))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _general_election_day(year: int) -> Optional[datetime]:
    day = region_registry.general_election_day(year)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) if day else None


class MedslProvider(PoliticalDataProvider):
    """Official historical returns compiled by the MIT Election Data and Science Lab."""

    provider_id = "medsl"
    name = "MIT Election Data and Science Lab — U.S. President 1976–2024"
    kind = "Academic dataset (Harvard Dataverse)"
    source_url = "https://doi.org/10.7910/DVN/42MVDX"
    description = "State-level certified presidential returns; the HISTORICAL_RESULT measurement family."
    attribution = (
        "MIT Election Data and Science Lab, 2025, \"U.S. President 1976–2024\", "
        "https://doi.org/10.7910/DVN/42MVDX — CC BY 4.0."
    )
    capabilities = frozenset({PoliticalDataProvider.CAP_HISTORICAL_MEASUREMENTS, PoliticalDataProvider.CAP_SOURCES})

    def __init__(self) -> None:
        super().__init__()
        self._settings = political_settings
        self._cache_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # disk cache
    # ------------------------------------------------------------------
    def _cache_file(self) -> Path:
        if self._cache_path is None:
            root = Path(self._settings.medsl_cache_dir)
            root.mkdir(parents=True, exist_ok=True)
            self._cache_path = root / "medsl-president-1976-2024.csv"
        return self._cache_path

    def _cache_is_fresh(self) -> bool:
        path = self._cache_file()
        if not path.exists():
            return False
        age_hours = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
        return age_hours <= self._settings.medsl_disk_cache_hours

    # ------------------------------------------------------------------
    # download / resolve
    # ------------------------------------------------------------------
    async def _resolve_file_id(self, client: httpx.AsyncClient) -> Optional[int]:
        """Find the datafile id for the expected CSV via the Dataverse API."""
        url = f"{self._settings.medsl_dataverse_base_url}/datasets/:persistentId/"
        response = await client.get(url, params={"persistentId": self._settings.medsl_dataset_doi})
        response.raise_for_status()
        payload = response.json() or {}
        files = (((payload.get("data") or {}).get("latestVersion")) or {}).get("files") or []
        for entry in files:
            datafile = entry.get("dataFile") or {}
            filename = str(datafile.get("filename") or "")
            if filename.lower() == self._settings.medsl_expected_filename.lower():
                return int(datafile.get("id"))
        # Fallback: first CSV in the dataset (filename may be re-versioned).
        for entry in files:
            datafile = entry.get("dataFile") or {}
            if str(datafile.get("filename") or "").lower().endswith(".csv"):
                logger.warning(
                    "MEDSL dataset layout changed; using first CSV %s instead of %s",
                    datafile.get("filename"), self._settings.medsl_expected_filename,
                )
                return int(datafile.get("id"))
        return None

    async def _load_csv_text(self) -> Tuple[str, str]:
        """Return (csv_text, provenance) — from disk cache or a fresh download."""
        if self._cache_is_fresh():
            return self._cache_file().read_text(encoding="utf-8", errors="replace"), "disk-cache"

        async with httpx.AsyncClient(
            timeout=max(self._settings.request_timeout_seconds, 45.0),
            headers={"User-Agent": self._settings.user_agent},
            follow_redirects=True,
        ) as client:
            file_id = await self._resolve_file_id(client)
            if file_id is None:
                raise RuntimeError(
                    f"Dataset {self._settings.medsl_dataset_doi} has no CSV file matching "
                    f"{self._settings.medsl_expected_filename!r}; refusing to guess."
                )
            response = await client.get(
                f"{self._settings.medsl_dataverse_base_url}/access/datafile/{file_id}",
                params={"format": "original"},
            )
            response.raise_for_status()
            text = response.text

        # Sanity-check before caching: a real MEDSL row has these headers.
        header = text.splitlines()[0].lower() if text else ""
        required = ("year", "state_po", "candidate", "candidatevotes", "totalvotes")
        if not all(column in header for column in required):
            raise RuntimeError("Downloaded MEDSL file does not match the expected schema; discarding.")
        try:
            self._cache_file().write_text(text, encoding="utf-8")
        except OSError as exc:  # cache write failure must never break the fetch
            logger.warning("could not persist MEDSL cache: %s", exc)
        return text, "download"

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    @staticmethod
    def parse_measurements(csv_text: str, retrieved_at: datetime) -> List[ForecastMeasurementSchema]:
        """CSV text → HISTORICAL_RESULT measurements for the top two vote-getters
        per state-year (a faithful, bounded subset of a large public dataset)."""
        reader = csv.DictReader(io.StringIO(csv_text))
        measurements: List[ForecastMeasurementSchema] = []
        dataset_source = "MIT Election Data and Science Lab (Harvard Dataverse)"
        dataset_url = MedslProvider.source_url

        # (year, state) -> rows, then rank by real votes.
        grouped: Dict[Tuple[int, str], List[Dict[str, str]]] = {}
        for row in reader:
            try:
                year = int(str(row.get("year") or "").strip())
            except (TypeError, ValueError):
                continue
            if year not in PRESIDENTIAL_YEARS:
                continue
            state = str(row.get("state_po") or "").strip().upper()
            if not state:
                continue
            grouped.setdefault((year, state), []).append(row)

        for (year, state), rows in sorted(grouped.items()):
            identity = region_registry.BY_CODE.get(state)
            if identity is None:
                continue
            valid: List[Tuple[int, int, Dict[str, str]]] = []
            total_votes = 0
            for row in rows:
                if str(row.get("writein") or "").strip().lower() == "true":
                    continue
                try:
                    candidate_votes = int(float(str(row.get("candidatevotes") or "").strip()))
                    state_total = int(float(str(row.get("totalvotes") or "").strip()))
                except (TypeError, ValueError):
                    continue
                if candidate_votes < 0 or state_total <= 0:
                    continue
                valid.append((candidate_votes, state_total, row))
            if not valid:
                continue
            total_votes = valid[0][1]
            valid.sort(key=lambda item: item[0], reverse=True)

            for candidate_votes, state_total, row in valid[:2]:
                share = candidate_votes / state_total * 100.0
                candidate = str(row.get("candidate") or "").strip() or "Unknown candidate"
                party = str(row.get("party_simplified") or row.get("party_detailed") or "").strip()
                label = f"{candidate} ({party})" if party else candidate
                measured_at = _general_election_day(year)
                election_day = measured_at.strftime("%Y-%m-%d") if measured_at else "unknown"
                measurements.append(ForecastMeasurementSchema(
                    id=f"medsl:{year}:{state}:{_slug(candidate)}",
                    region_id=f"us-state:{state}",
                    election_id=f"US-PRESIDENT-{year}",
                    candidate_or_outcome=label,
                    probability=round(share, 2),
                    measurement_type=MeasurementType.HISTORICAL_RESULT,
                    source=dataset_source,
                    source_id="medsl",
                    source_url=dataset_url,
                    measured_at=measured_at,
                    updated_at=None,
                    retrieved_at=retrieved_at,
                    methodology=(
                        f"Certified returns compiled by MEDSL: share = candidatevotes / totalvotes "
                        f"({candidate_votes:,} of {state_total:,} votes). Election day {election_day}."
                    ),
                    population=None,
                    sample_size=state_total,
                    uncertainty=None,
                    activity={"total_votes_cast": state_total, "candidate_votes": candidate_votes,
                              "activity_basis": "Votes cast — reported by the source dataset."},
                    is_current=False,
                    notes=f"Historical result for the {year} US presidential election in {identity.name}.",
                ))
        return measurements

    # ------------------------------------------------------------------
    # capability
    # ------------------------------------------------------------------
    async def get_historical_measurements(self) -> ProviderResult[ForecastMeasurementSchema]:
        async def _call() -> ProviderResult[ForecastMeasurementSchema]:
            return await self._fetch_history()
        return await self.fetch(_call)

    async def _fetch_history(self) -> ProviderResult[ForecastMeasurementSchema]:
        fetched_at = datetime.now(timezone.utc)
        try:
            csv_text, provenance = await self._load_csv_text()
        except Exception as exc:
            return ProviderResult(
                status=self.status,
                error=f"Historical dataset unavailable: {type(exc).__name__}: {exc}",
                fetched_at=fetched_at,
            )
        measurements = self.parse_measurements(csv_text, fetched_at)
        if not measurements:
            return ProviderResult(
                status=self.status,
                error="Historical dataset parsed but produced no usable state-year rows.",
                fetched_at=fetched_at,
            )
        logger.info(
            "MEDSL history loaded (%s): %d state-year measurements",
            provenance, len(measurements),
        )
        return ProviderResult(items=measurements, status=self.status, fetched_at=fetched_at)

    async def get_sources(self) -> List[Dict[str, Any]]:
        return [{
            "id": self.provider_id,
            "name": self.name,
            "url": self.source_url,
            "license": self.attribution,
            "dataset": self._settings.medsl_dataset_doi,
            "cache_dir": os.path.abspath(self._cache_file().as_posix()) if self._cache_file().exists() else str(self._cache_file()),
        }]
