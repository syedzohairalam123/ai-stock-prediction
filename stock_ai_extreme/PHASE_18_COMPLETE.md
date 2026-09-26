# Phase 18 — Political & Geopolitical Data Mapping / Forecast Visualization

**Status: complete.** Backend + frontend both run on localhost against real,
live external sources. Nothing was removed from the application; this pass only
added the Phase 18 module (and fixed real bugs, see below).

> This phase is **informational and neutral**. The application relays
> measurements that external sources actually published. It does not predict
> elections, endorse or rank candidates, infer user preferences or recommend
> any political outcome. No probability is ever invented, averaged or imputed
> by this codebase.

---

## Task memory — what this work was

The brief (Phase 18) asked for a neutral, source-driven political/geopolitical
visualization module sitting on top of a complete Phases 1–17 application:

* an interactive **map** (zoom / pan / hover / click / search / tooltip /
  legend / data timestamp) with a region **detail panel**;
* region states `AVAILABLE / NO_DATA / OUTDATED / CONTESTED / RESOLVED` —
  never a party colour, never data invented for a state;
* measurement families kept strictly separate: `POLL / FORECAST / MODEL /
  HISTORICAL_RESULT`;
* uncertainty only when the source published it;
* a neutral **head-to-head** view with no winner/ranking/recommendation;
* a **geopolitical timeline** and event calendar;
* a provider-adapter architecture (`PoliticalDataProvider`);
* filters (election / country / state / date / source / measurement type);
* responsive layout (desktop map + side panel, tablet collapsible, mobile map
  first → details);
* honest error handling when geometry, measurements or a source is missing or
  when sources disagree;
* geographic boundaries from an authoritative dataset.

---

## What already existed vs. what this pass added

A prior revision had already written the **backend** module under
`backend/app/political/`. It was, however, **un-importable** (see bugs below) —
so `app.main` could not start and Phase 18 never actually ran. This pass:

1. **Fixed the startup-blocking bugs** (below) so the backend imports and serves.
2. Added the entire **frontend** for the module (data layer, hooks, components,
   page, route, nav, responsive CSS). Nothing existing was removed.
3. Added **40 backend tests** (`backend/tests/test_political.py`).
4. Fixed a pre-existing failing test unrelated to Phase 18 (see bugs).
5. Verified end-to-end on localhost with **real live data** (below).

---

## Real bugs found and fixed

1. **Backend refused to start — relative import beyond top-level package.**
   `app/political/engine.py` and `app/political/routes.py` imported the logger
   with `from ...logging_config import ...` (three dots). From
   `app/political/*` the correct level is two dots. This raised
   `ImportError: attempted relative import beyond top-level package` on
   `import app.main`, so **the whole API failed to boot**. Now `app.main`
   imports cleanly.

2. **Conflict threshold compared against the wrong scale.**
   `conflict_threshold` is a fraction of 1.0 (default `0.05`, validated
   `le=1.0`), but the engine compared it directly against a 0–100 percentage
   gap, so the effective threshold was 0.05 of a *point* and almost any two
   sources were flagged `CONTESTED`. The engine now converts to percentage
   points (`threshold * 100`), so the default really means “five points”.

3. **Bare two-letter state codes matched ordinary English words.**
   `detect_us_state` matched codes against the *uppercased* text, so the words
   “in”, “or”, “me” became Indiana/Oregon/Maine. A live Polymarket market
   (“… prime minister of **Eth**iopia”) was being mapped to `us-state:IN`.
   Codes are now matched **case-sensitively** in the original text (full state
   names are still matched case-insensitively). GDELT's affected-region
   detection had the same flaw and was fixed the same way.

4. **`detect_country` returned a display name instead of an ISO-3 code.**
   It produced region ids like `country:Ethiopia`, which match no region in the
   registry (keys are `country:ETH`). It now returns the ISO-3 code, so
   measurements actually attach to a country on the map.

5. **The FEC election calendar was always empty.**
   The live `/election-dates/` response contains **no `trc_election_id`**, but
   the normalizer required it and therefore discarded **every** row. The
   normalizer now derives a stable id from the row’s own facts (office, state,
   year, type, district, date). A live 2026 row now becomes a sourced event.

6. **A rate limit on page 2 threw away page 1’s data.**
   With the shared `DEMO_KEY`, OpenFEC 429s after the first page. The code
   raised and discarded all already-collected rows. It now stops paginating on
   a non-403 error but **keeps the rows it already has**, and reports the real
   reason (rate limit vs. bad key) instead of a misleading generic message.

7. **The map was unusably slow on first load.**
   `regions_bundle` fetched World Bank population context for ~95 countries
   **sequentially**; measured at >300 s (timed out). It now fetches them
   concurrently with a bounded semaphore — measured **~40 s** on a cold cache
   and instant thereafter (24 h TTL).

8. **Pre-existing failing test (unrelated to Phase 18).**
   `tests/test_jobs.py::test_rate_limiter_cleanup_drops_idle_buckets` staked
   its “stale” timestamp on `window*4` (240 s) while `RateLimiter.cleanup`
   floors the idle timeout at 300 s, landing exactly on the boundary. Corrected
   the test to use the same `max(window*4, 300)` rule. Full suite is now green.

---

## Architecture

```
backend/app/political/
  config.py                 typed settings (POLITICAL_* env)
  schemas.py                Pydantic contract; no field can express an opinion
  regions.py                identity-only registry: 50 states + DC + 94 countries
  engine.py                 neutral aggregation, region-state classification,
                            conflict detection (keeps BOTH sides), TTL caches
  routes.py                 /api/political/* endpoints
  providers/
    base.py                 PoliticalDataProvider interface + honest failures
    openfec_provider.py     FEC official election calendar        (events)
    polymarket_provider.py  prediction-market probabilities       (MODEL)
    medsl_provider.py       MIT MEDSL certified returns           (HISTORICAL_RESULT)
    gdelt_provider.py       GDELT DOC 2.0 coverage                (timeline)
    population_provider.py  World Bank / US Census population context

frontend/src/
  lib/political.ts                  types + PoliticalService + display metadata
  hooks/usePoliticalQueries.ts      React Query hooks
  pages/PoliticalPage.tsx           route /political
  components/political/
    PoliticalMap.tsx                Plotly choropleth (US states + world)
    RegionDetailPanel.tsx           region detail (measurements by family)
    MeasurementCard.tsx             one measurement with full provenance
    HeadToHeadView.tsx              neutral side-by-side, no winner
    PoliticalTimeline.tsx           GDELT coverage timeline
    SourceRegistryPanel.tsx         source health + attribution
  index.css                         Phase 18 styles (add-only)
```

Map geometry comes from **Plotly’s bundled authoritative topojson**
(Natural Earth / US Census derived) — the app never draws borders itself. Map
colour encodes **data availability**, never a party, candidate or outcome.

---

## Data sources (all real, all attributed, all keyless-friendly)

| Source | Contributes | Measurement type | Key |
|---|---|---|---|
| Federal Election Commission (OpenFEC) | official election calendar | — (events) | `DEMO_KEY` default; `POLITICAL_FEC_API_KEY` for quota |
| Polymarket Gamma API | live implied probabilities | `MODEL` | none |
| MIT Election Data & Science Lab (Harvard Dataverse) | state presidential returns 1976–2024 | `HISTORICAL_RESULT` | none |
| GDELT DOC 2.0 | global political coverage | — (timeline) | none |
| World Bank / U.S. Census | population context | — | Census needs `POLITICAL_CENSUS_API_KEY` |

A source that is unreachable is reported as unavailable **with its reason** —
never hidden, never replaced by a fabricated value.

---

## Verified live on localhost

* Backend: `uvicorn app.main:app` → `http://127.0.0.1:8000`
* Frontend: `npm run dev` → `http://localhost:5173` (proxies `/api`)
* `GET /api/political/meta` → 4 measurement families, 5 region states.
* `GET /api/political/measurements?measurement_type=MODEL` → **90 real
  Polymarket measurements**; `country:ETH`, `country:BRA`, `country:USA`,
  `country:RUS` — the earlier false `us-state:*` mappings are gone.
* `GET /api/political/regions` → **145 regions** (51 states/DC + 94 countries),
  **92 countries with live World Bank population**; classification
  `NO_DATA ×90, RESOLVED ×51 (MEDSL history), AVAILABLE ×4`.
* `GET /api/political/overview` → 145 regions, 51 region states, 90
  measurements, 4 sources, in ~4 s once the region cache is warm.
* Head-to-head response contains **no** `winner` / `ranking` /
  `recommendation` field.
* Frontend render check (headless Chrome, `/political`): title, interactive
  Plotly map (`geolayer`/`plot-container` rendered), legend with all five data
  states, region detail empty-state, head-to-head, calendar, measurements
  browser with real measurement cards, timeline and source registry all
  present; **no React error-boundary fallback**.

## Honest limitations

* OpenFEC’s shared `DEMO_KEY` is heavily rate-limited, so the calendar may show
  fewer rows (or none) in a shared environment. Set `POLITICAL_FEC_API_KEY`
  for a personal quota.
* GDELT enforces ~1 request / 5 s and may 429 on a busy network; the timeline
  then reports “no coverage in this window” with the real reason.
* US **state** population context needs `POLITICAL_CENSUS_API_KEY`; without it
  the UI shows “not provided by any source” rather than an estimate.
* Head-to-head compares **current** sourced measurements; historical results
  appear in the region detail panel’s `HISTORICAL_RESULT` section.

---

## Testing

```bash
cd stock_ai_extreme/backend
./.venv/Scripts/python.exe -m pytest tests/test_political.py   # 40 passed
./.venv/Scripts/python.exe -m pytest -q                        # 838 passed
```

`tests/test_political.py` covers: the four measurement families; probability
bounds; uncertainty absent unless sourced; the statute-based election day; all
five region classifications; conflict detection; every provider normalizer
(including the live FEC row shape, the rate-limit partial-success path, the
word-boundary/ISO-3 regressions); and every route including the neutral
head-to-head contract.

Frontend: `npx tsc --noEmit` clean, `npm run build` succeeds.
