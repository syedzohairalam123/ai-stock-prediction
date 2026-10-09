# PHASE 23A — CENTRAL BANK POLICY & MACROECONOMIC INTELLIGENCE REPORT

**Method:** the existing Phase 23A module was inspected end-to-end, audited
against the spec, then extended **additively** — nothing was removed, no working
service was rewritten, and no duplicate data layer was created.

---

## What already existed (verified, reused — not rewritten)

| Spec | Status | Where |
|---|---|---|
| §2 Real sources | PASS | `FederalReserveSource` (FOMC calendar scrape + FRED `DFF` decision detection + official-records fallback), `BankOfJapanSource` (MPM schedule), `FREDSource` (observations + ALFRED vintages for revisions) — all keyless, no fabricated values |
| §3 Data model | PASS | `CentralBankInfo`, `PolicyMeetingInfo`, `PolicyDecisionInfo`, `PolicyExpectationInfo`, `MacroSeriesInfo` + Pydantic response models; DB tables `central_banks`, `policy_meetings`, `policy_decisions`, `policy_expectations`, `macro_series` |
| §4 Fed engine | PASS | bps **always calculated** `((new-prev)*100)`, direction derived (HIKE/CUT/UNCHANGED), official FOMC calendar URL as source document |
| §5 BOJ engine | PASS | same architecture, BOJ's own calendar/instruments respected |
| §6 Meeting cards | PASS | `get_upcoming_meetings()` computes countdowns from real tz-aware timestamps; no fixed countdowns |
| §8 Macro indicators | PASS | FRED series with **observation date ≠ release date**, revision counter + `previous_value` |
| §11 Ingestion architecture | PASS | Sources → validation → normalization → DB → API → UI; per-source failure isolation (a dead source returns `[]` + log, never a fabricated row) |
| §12 Versioned API | PASS | `/api/v1/macro/central-banks`, `/meetings[/{bank}]`, `/policy/{bank}`, `/series[/{id}]`, `/analytics/policy|trend|regime`, `/health` — server-side `Query` validation throughout |
| §13 Data quality | PASS | `determine_data_freshness()` (LIVE/RECENT/DELAYED/HISTORICAL/STALE/UNAVAILABLE) driven by the **release date**, so an old observation is never labelled LIVE just because the API was just called; FRED key stays server-side |

## What this pass ADDED (the gaps)

| Spec | Added | File |
|---|---|---|
| §7 Expectation snapshots API | `GET /api/v1/macro/expectations/{bank}` + `POST /expectations/refresh/{bank}` — append-only sourced snapshots, probability totals validated (0–100, ~100% sum within rounding tolerance, partial distributions labelled rather than completed) | `macro_intelligence/routes.py`, `service.py` |
| §7 Honest gap | When no configured source publishes machine-readable probabilities (CME FedWatch needs a data agreement) the API and UI state **"Market-implied expectations unavailable."** — never a fabricated number | same |
| §10 Event-window analysis | `GET /api/v1/macro/event-window/{bank}?ticker=&lookback_decisions=&windows=` — 1D/3D/5D/10D/20D market observations around completed decisions, computed from the **same real provider path** as every other chart (bound via `configure_market_data`, no second data service); explicitly labelled a historical observation, never causation | `service.py`, `routes.py`, `main.py` (one wiring line) |
| §14 UI | Two new panels on the Macro Intelligence page: **Market-Implied Policy Expectations** (attribution + methodology + probability note, honest unavailable state) and **Event-Window Analysis** (decision table with Δbps and window returns, market source + history range) | `pages/MacroIntelligencePage.tsx` |
| §14 Tests | `tests/test_macro_phase23a_additions.py` — 10 tests: empty-history honesty, snapshot attribution + probability validation (full and partial distributions), event-window requires decisions / requires fetcher / computes windows from a stubbed market frame / fails gracefully, route validation (400 on bad windows), route serving | `tests/test_macro_phase23a_additions.py` |

## Real bugs found & fixed (pre-existing)

1. **`analyze_policy_rates` was order-dependent** — `current_rate` read the
   **oldest** decision (the frame is sorted ascending) and `total_bps_change`
   was sign-flipped. Fixed: newest row is the current rate; total change is
   `newest - oldest`, always. Verified by the previously-failing
   `test_mixed_decisions`.
2. **`TestMacroAPIEndpoints` could never run** — the `client` fixture did not
   exist and the tests `await` requests. Added an async ASGI client fixture
   (`httpx.AsyncClient` + `ASGITransport`) with explicit `init_db()`, so the
   four Phase 23A endpoint tests now actually execute and pass.
3. **`test_main_app::test_root_and_health` asserted a stale `/health` shape** —
   Phase 22 added a real crypto health block; the test now asserts
   `status == "ok"` **and** that the crypto snapshot is present.

## Verification

| Check | Result |
|---|---|
| `pytest tests/test_macro_intelligence.py tests/test_macro_phase23a_additions.py` | **37 passed** (was 27 passing + 4 erroring + 1 failing) |
| `pytest tests/test_main_app.py test_new_routes.py test_macro.py` + macro files | **91 passed** |
| `pytest app/crypto/tests/test_api_integration.py` | **24 passed** (no regression from the `main.py` wiring) |
| `npm run typecheck` | **clean** |
| `npm run build` | **success** |
| Live `GET /api/v1/macro/event-window/FED` | `status LIVE`, 4 decisions × real ^GSPC windows (e.g. 2025-12-17 CUT −25bps → 1D −0.37%, 5D +1.94%, 20D +2.06%), `market_source yfinance` |
| Live `GET/POST /api/v1/macro/expectations/FED` | honest `"Market-implied expectations unavailable."` (no fabrication) |
| Live `GET /api/v1/macro/event-window/FED?windows=1,x` | **400** (server-side validation) |
| Headless-Chrome CDP on `/macro-intelligence` | navbar link present · both panels render · expectations panel shows the honest unavailable statement · event-window table has 4 real rows · historical-observation note visible · **0 uncaught errors** |
| Localhost | backend `:8000` 200, frontend `:5173` 200 |

## Remaining limitations (honest)

- Market-implied expectations come from Polymarket's public prediction markets.
  Coverage depends on an open market existing for that bank's next meeting;
  when none is reachable the API/UI show the explicit unavailable state.
- The keyless FRED CSV endpoint does not publish FRED's release/vintage stamp,
  so keyless rows mirror the observation date and are flagged
  `release_date_estimated`. Setting `FRED_API_KEY` upgrades every series to
  true release dates (and the flag turns off) with no other change.
- Event-window results are historical observations, never a causation claim.
- Phase 23B was **not** started (spec: STOP AFTER PHASE 23A).

---

# PASS 2 — real-data completion (additive; nothing removed)

Pass 1 left two honest gaps: macro data needed a FRED API key, and market-implied
expectations were permanently unavailable. This pass closes both with real,
keyless sources, and fixes the calendar/date bugs that surfaced once upcoming
meetings actually existed.

## Evidence — every displayed value is real

| Panel | Source | Live value observed |
|---|---|---|
| Fed target range (§4) | FRED `DFEDTARL` / `DFEDTARU` (keyless CSV) | **3.75% – 4.00%**, LIVE |
| Fed decisions (§4) | FRED `DFEDTARU` stepwise changes | latest **2026-09-17 +25 bps HIKE → 4.00%** |
| FOMC calendar (§2/§6) | federalreserve.gov calendar markup | next **2026-10-28 18:00 UTC**, UPCOMING |
| BOJ calendar (§5/§6) | boj.or.jp MPM schedule tables | next **2026-10-30 03:00 UTC**, UPCOMING |
| Macro indicators (§8) | FRED keyless CSV | 15 series: DFF 3.88%, UNRATE 4.2%, DGS10 5.31%, VIX 15.52%, … |
| Fed expectations (§7) | Polymarket public market | UNCHANGED **82.5%**, HIKE 16.85%, CUT 0.65%, total 100.0% |
| BOJ expectations (§7) | Polymarket public market | UNCHANGED **96.5%**, HIKE 3.8%, CUT 0.1% |
| Event window (§10) | same provider path as every chart (yfinance) | status LIVE, real ^GSPC 1D/3D/5D/10D/20D |

## What this pass ADDED / FIXED

| Item | Change | File |
|---|---|---|
| Keyless FRED | `fetch_series` now falls back to the public `fredgraph.csv` endpoint when no key is set (and when a key errors), so macro data works on a fresh install. Units derived from the series catalogue, frequency inferred from observation spacing. | `macro_intelligence/sources.py` |
| Real expectations | New `PolymarketPolicyExpectationSource` adapter: finds the nearest open `<Bank> Decision in <Month>?` event, aggregates directional contract Yes prices into HIKE/CUT/UNCHANGED with source, timestamp and methodology. | `macro_intelligence/expectations.py` (new) |
| Snapshot attribution | New nullable `policy_expectations.source_url` column (auto-migrated by `db._ensure_additive_columns`), carrying the exact source market link. | `app/models.py`, `service.py` |
| Fed decisions | Switched from `DFF` (daily effective rate, drifts 1 bp between meetings and produced phantom decisions) to the stepwise `DFEDTARU` target bound. | `sources.py` |
| Labels bounds | `GET /policy-range/{bank}` returns lower/upper/midpoint, each labelled, LIVE from FRED (§4). | `service.py`, `routes.py` |
| Indicator dashboard | `GET /indicators` + `refresh_macro_indicators` (concurrent, per-series isolation) returns the latest real observation per curated series. | `service.py`, `routes.py` |
| One-click refresh | `POST /refresh/{bank}` refreshes meetings + decisions + indicators + expectations; the UI auto-bootstraps once on a fresh database. | `routes.py`, `MacroIntelligencePage.tsx` |
| Meeting card §6 | Meeting cards now show the sourced market-implied expectation when one exists. | `PolicyMeetingCard.tsx` |
| **Bug: bogus FOMC calendar** | The old scraper matched any `Month DD, YYYY` and picked up minutes-release text ("Released February 18, 2026"), reporting meetings that never existed. Now parses the real `fomc-meeting__month` / `fomc-meeting__date` cells and anchors each meeting at 2:00 p.m. America/New_York on its decision day. | `sources.py` |
| **Bug: dead BOJ URL** | The BOJ schedule URL returned 404, silently forcing the fallback forever. Moved to the live `mpmsche_minu` page and parse its tables. | `sources.py` |
| **Bug: oldest-N slicing** | `fetch_meetings` took `[:limit]` from an ascending list, so it returned 2022 and never an upcoming meeting. Now returns the most recent + upcoming. | `sources.py` |
| **Bug: naive/aware crash** | The slicing bug had hidden it: once upcoming meetings existed, countdowns and meeting resolution raised "can't subtract offset-naive and offset-aware datetimes" (SQLite returns naive datetimes). Added `_as_utc` at every read-back boundary. | `service.py` |
| **Bug: third-person contracts** | `\b increase \b` did not match "increases"/"decreases", so every BOJ hike contract was classified as neither — reported 0% hike. Fixed with word stems. | `expectations.py` |
| Freshness for keyless series | Monthly/quarterly observations were mislabelled STALE purely from wall-clock age; freshness now scales to the series' own release cadence, with `release_date_estimated` keeping the caveat visible. | `sources.py` |
| Tests | 16 new deterministic tests (calendar parsers, CSV parser, frequency/freshness, probability aggregation, third-person wording, indicator service, unknown-bank honesty). | `tests/test_macro_phase23a_realsources.py` (new) |

## Verification (this pass)

| Check | Result |
|---|---|
| `pytest` macro + main suite | **88 passed** |
| `npm run typecheck` | clean |
| `npm run build` | success |
| Live `POST /api/v1/macro/refresh/FED` | 20 meetings · 32 decisions · 1800 indicator rows · 1 expectation snapshot |
| Live `GET /policy-range/FED` | `3.75–4.00`, LIVE, FRED |
| Live `GET /expectations/FED` | LIVE, Polymarket, total 100.0%, real source URL |
| Live `GET /event-window/FED` | LIVE via yfinance |
| Headless-Chrome DOM of `/macro-intelligence` | rate range, 15 indicators, Polymarket expectation + 82.5%, meeting-card market-implied, event-window table all render · 0 page errors |
| Localhost | backend `127.0.0.1:8000` 200 · frontend `127.0.0.1:5173/macro-intelligence` 200 |

---

# PASS 3 — spec-completeness pass (additive; nothing removed)

This pass read the whole Phase 23A module, the changed files and the spec, then
filled the remaining gaps **additively**. No existing endpoint, component or
test was removed and no working service was rewritten.

## What this pass ADDED

| Spec | Added | File |
|---|---|---|
| §3 Extensible bank architecture | `CENTRAL_BANK_SOURCE_FACTORIES` registry + `register_central_bank_source()` + `available_source_banks()` + `CENTRAL_BANK_CATALOGUE`. The service resolves a bank's adapter through the registry instead of hardcoding FED/BOJ, so ECB/BOE/BOC/RBA/SNB is one registration + one catalogue entry — the shared fetch→normalise→store→API path is unchanged. `initialize_central_banks()` is now catalogue-driven. | `macro_intelligence/service.py` |
| §15 API surface | `GET /api/v1/macro/central-banks/supported` (declared before `/{bank_id}` so the literal path wins) and `GET /api/v1/macro/upcoming` (spec's named alias for the upcoming view; shares the `/meetings` code path). `/health` now reports `registered_source_banks`. | `macro_intelligence/routes.py` |
| §8 "Last Updated" | `source_timestamp` now flows through the meeting payload, and the meeting card renders "Last updated <source capture time>". | `service.py`, `routes.py`, `PolicyMeetingCard.tsx`, `UpcomingMeetings.tsx` |
| §19 Invalid series | `GET /series/{id}` now returns **404** with the exact reason when the id is neither curated nor stored, instead of a misleading empty 200. `is_known_series()` added. | `routes.py`, `service.py` |
| §18 UI components | New exported components: `FreshnessBadge`, `DataSourceBadge`, `ExpectationCard`, `UpcomingMeetings`, `MacroSeriesExplorer`. `MacroSeriesCard` (previously defined but unused) is now actually used. | `components/macro/*.tsx`, `components/macro/index.ts` |
| §10 Macro data UI | **Macro Series Explorer** panel: series selector over the real `/series` catalogue, latest value via `MacroSeriesCard`, backend trend analytics, a sparkline of real observations, and observation-vs-release dates with the estimated-release caveat. | `MacroSeriesExplorer.tsx`, `pages/MacroIntelligencePage.tsx` |
| §18 UI test surface | `/macro-intelligence` added to the dev page-audit route list so the panel is continuously checked for uncaught errors. | `frontend/scripts/page-audit.mjs` |
| §20 Tests | New `tests/test_macro_phase23a_registry.py` (14 tests): registry ships FED+BOJ, catalogue matches, unknown bank has no source, a newly-registered bank flows through the shared store path, catalogue drives init, `/supported` not shadowed, `/upcoming` served, `source_timestamp` present, `/health` registry, unknown series 404, known series 200, unknown bank history empty. | `tests/test_macro_phase23a_registry.py` |

## Verification (this pass, real localhost run)

| Check | Result |
|---|---|
| `pytest` macro + main suite | **102 passed** (was 88; +14 new registry tests) |
| `npm run typecheck` | clean |
| `npm run build` | success |
| Live `POST /refresh/FED` | 20 meetings · 32 decisions · **1800 indicator rows** · 1 expectation snapshot |
| Live `GET /policy-range/FED` | **3.75–4.00**, LIVE, FRED `DFEDTARU` |
| Live `GET /upcoming` | next FOMC **2026-10-28 18:00 UTC**, countdown computed live (20d 6h), `source_timestamp` present |
| Live `GET /indicators` | 15 real series (DFF 3.88, UNRATE 4.2, DGS10 5.27, VIX, …) |
| Live `GET /expectations/FED` | Polymarket, HIKE 14.85% / UNCHANGED 85.5% / CUT 0.6%, total 100.95%, real event URL |
| Live `GET /expectations/BOJ` | Polymarket, HIKE 4.85% / UNCHANGED 95.2%, total 100.15% |
| Live `GET /series/DGS10` | two real observations, source `FRED CSV` |
| Live `GET /analytics/trend/UNRATE` | trend `volatile`, rolling 3M computed from stored rows |
| Live `GET /series/NOT_A_REAL_SERIES` | **404** with "Unknown macro series …" |
| Live `GET /event-window/FED` | LIVE via yfinance (real ^GSPC 1D/3D/5D/10D/20D) |
| Live `GET /event-window/FED?windows=1,x` | **400** |
| `POST /refresh/BOJ` | 16 meetings · 28 decisions · 1800 indicator rows · 1 snapshot |
| Headless-Chrome audit `/macro-intelligence --full` | **0 routes need attention** (no uncaught exceptions / console errors / failed requests); DOM contains Macro Series Explorer, Upcoming Meetings (10 × "Last updated"), Market-Implied Policy Expectations (3 × "Reported total"), Event-Window Analysis, Federal Funds Target Range |
| Backend log across the browser session | **0 tracebacks, 0 5xx** |
| Localhost | backend `127.0.0.1:8000` 200 · frontend `127.0.0.1:5173/macro-intelligence` 200 |

## Memory notes (how to run / what to know)

- Run backend: `cd stock_ai_extreme/backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Run frontend: `cd stock_ai_extreme/frontend && npm run dev -- --host 127.0.0.1 --port 5173`
- Page: `http://127.0.0.1:5173/macro-intelligence` · API docs: `http://127.0.0.1:8000/docs`
- Real sources, keyless: FOMC calendar (federalreserve.gov), BOJ MPM schedule (boj.or.jp), FRED public CSV (`fredgraph.csv`), Polymarket Gamma API, and the app's own yfinance provider for event windows. `FRED_API_KEY` (optional) upgrades series to true release dates.
- Add a future bank: append to `CENTRAL_BANK_CATALOGUE` + `register_central_bank_source("ECB", factory)` — no engine change; then `POST /api/v1/macro/refresh/ECB`.
- Nothing is fabricated: every empty state is an explicit `UNAVAILABLE`/404/empty list, never a placeholder number.

## Remaining limitations (honest)

- FRED keyless CSV cannot publish FRED's true release/vintage stamp, so rows are flagged `release_date_estimated`; setting `FRED_API_KEY` removes the caveat.
- Market-implied expectations come from Polymarket; when no open market exists for a bank the API/UI state "Market-implied expectations unavailable." rather than inventing a probability.
- Event-window results are historical observations, never a causation claim.
- Phase 23B was **not** started (spec: STOP AFTER PHASE 23A).
