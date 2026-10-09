# PHASE 23B — WORKING NOTES / MEMORY (do not delete)

Task: SPX/SPY market-direction analytics + dynamic corporate market-cap intelligence.
Rules from the user: ADD ONLY. Never remove/break existing website features. All data must be
REAL (provider/API), no dummy data. Run the site on localhost.

STATUS: **COMPLETE** — all spec §1–§19 gaps closed additively; verified on localhost with real
yfinance data. Phase 23A continues to pass. Phase 23C was NOT started (spec: STOP AFTER 23B).

## Backend `app/market_intel/`
- `direction.py`  — instruments (^GSPC index vs SPY ETF), `DailyObservation`,
  `build_daily_observations`, `classify_direction`, `compute_direction_statistics`, `compute_rolling`,
  `latest_session`, `align_instruments`, AND the spec §3 `MarketDirectionEngine` class facade
  (`build`/`classify`/`daily_return`/`statistics`/`rolling`/`latest`/`align`).
- `companies.py`  — COMPANY_UNIVERSE (~37 large caps), `CompanyMarketData`,
  `build_company_market_data`, `compute_market_cap`, `rank_companies`, split helpers,
  `scenario_market_cap`, `market_cap_race`.
  **BUG FIXED:** the builder read only `marketCap`, but this project's yfinance adapter
  (`get_profile`) exposes `market_cap` (snake_case) — so provider-reported caps were never seen and
  every figure silently degraded to an estimate. Now reads both, so `VERIFIED PROVIDER_REPORTED`
  actually happens (confirmed live: NVDA $5.565T VERIFIED).
- `analytics.py` (NEW, spec §17) — NumPy/SciPy helpers: `simple_returns`, `annualized_volatility`,
  `mean_return`, `rolling_mean_std`, `value_at_risk`, `max_drawdown`, `pearson_correlation`,
  `spearman_rank_correlation`. Used by the comparison endpoint (SPX/SPY correlation + vols).
- `db_models.py`  — `companies`, `company_market_observations`, `market_cap_rank_history`,
  `corporate_action_events`, PLUS spec §15 `company_security_mappings` (one row per listed security,
  multi-class aware) and `market_cap_snapshots` (frozen inputs + derived cap + rank + source).
- `service.py`    — `MarketIntelligenceService`. Now also: builds security mappings, writes market-cap
  snapshots, paged history (`limit`/`offset`), `get_security_mappings`, `get_market_cap_snapshots`,
  comparison `analytics`, and a **concurrent** profile fetch (bounded semaphore of 8) — the
  leaderboard cold-cache time dropped from **180s → 16.5s** with identical real data.
- `facades.py` (NEW, spec §15) — named services `IndexDataService`, `MarketDirectionService`,
  `CompanyDataService`, `MarketCapService`, `CorporateActionService`, `MarketScenarioService`
  (thin stateless facades over the one singleton; resolved lazily).
- `routes.py`     — `/api/v1/market-intel/*` endpoints plus NEW `GET /companies`,
  `/company/{id}/snapshots`, `/company/{id}/mappings`, and `offset` on history/direction/company
  history. Literal routes stay declared before `/{instrument}`.
- `__init__.py`   — exports the engine, singleton service, facades and helpers.
- `main.py` — unchanged wiring (SAME provider manager + Phase 23A macro service).
- `db.py` — unchanged; `init_db()` imports `market_intel.db_models`, so the two new tables are created.

## Frontend `frontend/src/components/market-intel/` + page
- Existing: InstrumentCard, DirectionCharts, SpxSpyComparison, MarketCapLeaderboard, ScenarioCalculator.
- NEW `MarketCapRace.tsx` (spec §12) — descriptive grouped bar + table; no probability/forecast.
- NEW `CompanyCapHistory.tsx` (spec §14) — per-company stored cap line + rank line (inverted axis),
  latest observed inputs/methodology/quality/source.
- `MarketIntelligencePage.tsx` — added the race + company-history sections; event study now has an
  **SPX/SPY toggle** and renders the backend's returned windows dynamically (1D/3D/5D/10D/20D); the
  event study loads in **parallel** with a proper loading state (was misleadingly showing
  "unavailable" while in flight).
- `index.ts` exports the two new components + types. Route `/market-intelligence` unchanged in
  App.tsx / header / Layout / page-audit.

## Tests
- `tests/test_market_intel_phase23b_engine.py`, `..._service.py` — existing (69).
- NEW `tests/test_market_intel_phase23b_additions.py` (28) — engine facade, analytics (NumPy/SciPy),
  snake_case cap key, security mappings, snapshots, pagination, comparison analytics, health surface,
  and the new HTTP routes.

## Verification (real localhost run)
| Check | Result |
|---|---|
| 23B tests + new additions | 97 passed |
| 23A macro + main suite (with 23B) | **187 passed** |
| `npm run typecheck` | clean |
| `npm run build` | success |
| Live `GET /spx/quote` | `^GSPC` close **7765.36**, prev 7801.77, **-0.4667% DOWN**, source yfinance, trading_date 2026-10-08 |
| Live `GET /spy/quote` | `SPY` close **773.93**, **-0.4233% DOWN**, source yfinance (index ≠ ETF) |
| Live `GET /leaderboard` | NVDA $5.565T **VERIFIED PROVIDER_REPORTED**; AAPL/GOOGL/MSFT/AMZN/TSM/META/AVGO/TSLA/BRK-B ranked |
| Live `GET /comparison` | 289 aligned sessions · SPX/SPY correlation **0.9969** · vol **12.47%** · max DD **-9.10%** |
| Live `GET /company/nvidia/snapshots` | price 230.48 × 24,147,000,000 shares → 5,565,400,481,792, rank 1, yfinance |
| Live `GET /company/apple/scenario?return_pct=10` | HYPOTHETICAL: 340.42 → 374.462 → cap 5.465T |
| Live `GET /events/FED?instrument=spy` | status LIVE, **ticker SPY**, real SPY 1D/20D windows |
| Headless-Chrome audit `/market-intelligence --full` | **0 routes need attention**, exit 0; DOM shows race, company history, leaderboard, scenario, SPX/SPY event study |
| Localhost | backend `127.0.0.1:8000` 200 · frontend `127.0.0.1:5173/market-intelligence` 200 |

## Memory — how to run / what to know
- Backend: `cd stock_ai_extreme/backend && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Frontend: `cd stock_ai_extreme/frontend && npm run dev -- --host 127.0.0.1 --port 5173`
- Page: `http://127.0.0.1:5173/market-intelligence` · API docs: `http://127.0.0.1:8000/docs`
- Real source: the app's own yfinance provider via the shared `MarketDataManager` (no second stack).
  SPX = index symbol `^GSPC`; SPY = ETF `SPY`; they are always distinct.
- Leaderboard cold-cache ~10–16s (37 concurrent profile calls); warm is fast (1h profile cache).
- **If a stale server is already on :8000 it will serve OLD code** — kill the PID on the port first
  (`netstat -ano | grep :8000`, `taskkill //F //PID <pid>`) before restarting uvicorn.
- Add a company: append to `COMPANY_UNIVERSE` (mappings self-populate on next leaderboard).
- Nothing is fabricated: missing data → explicit UNAVAILABLE/unranked/None; scenarios labelled
  `HYPOTHETICAL_SCENARIO`; event studies labelled `OBSERVATIONAL`.

## Second pass — remaining spec gaps closed (additive; nothing removed)

| Spec | Added | File |
|---|---|---|
| §10 | **Real provider splits** ingested as corporate actions: `YFinanceProvider.get_splits` + `MarketDataManager.splits` + `POST /corporate-actions/refresh/{id}` (`refresh_corporate_actions`, idempotent). Buybacks/issuance stay manual (no machine-readable feed). | `providers/yfinance_provider.py`, `providers/manager.py`, `market_intel/service.py`, `routes.py` |
| §15 | Explicit `shares_outstanding_observations` table with its OWN freshness check (a share row is written even when the quote is unchanged, so its as-of date/source can't be hidden behind a fresh price). `GET /company/{id}/shares`. | `db_models.py`, `service.py`, `routes.py` |
| §14 | `GET /rank-history` (cross-company rank snapshots grouped per ticker) + `RankTimeline.tsx` chart (top 10, inverted rank axis). | `service.py`, `routes.py`, `RankTimeline.tsx` |
| §12 | Race **period selector** (30/90/180/365/730 days) that reloads the race from stored snapshots. | `MarketIntelligencePage.tsx` |
| §7 | Event-window analysis now records the **market sessions** each window spans: `decision_session`, `pre_session`, `window_end_sessions` (real trading dates, weekends/holidays skipped), surfaced in the table. | `macro_intelligence/analytics.py`, `macro_intelligence/service.py`, `MarketIntelligencePage.tsx` |
| §10 UI | Company panel now lists stored corporate actions and has a **Refresh splits from provider** button + `marketIntelPost` helper. | `CompanyCapHistory.tsx`, `api.ts` |
| §18 | +18 tests for splits ingestion/idempotency, share-count store, rank history, event-session metadata, and the new routes. | `test_market_intel_phase23b_additions.py` |

**Second-pass verification:** backend **199 passed** · `npm run typecheck` clean · `npm run build` success · live
`POST /corporate-actions/refresh/nvidia` → 6 real splits (2000/2001/2006/2007/2021 4:1/2024 10:1) · live
`GET /company/apple/shares` → 14,594,180,000 (yfinance sharesOutstanding, VERIFIED) · live `GET /rank-history` →
724 rows / 37 series · live `GET /events/FED` → `decision_session`/`pre_session`/window end sessions ·
headless-Chrome audit `/market-intelligence --full` → **0 routes need attention**, exit 0, DOM shows
"Corporate actions (6)", "Refresh splits from provider", "Ranking timeline", "Comparison period".

## Remaining limitations (honest)
- yfinance is an unofficial Yahoo wrapper with no SLA; a company the provider cannot answer for is
  reported unranked, never given an invented cap.
- Provider-reported caps are company-wide per Yahoo's methodology; computed (price × shares) figures
  are labelled ESTIMATED and flag the multi-class limitation.
- Race analytics are descriptive only — no forecast/probability is produced.
- Buybacks/share issuance can only be recorded manually: the provider publishes splits as a
  machine-readable feed, but not buybacks/issuance, so those are never guessed.
- A long market-history fetch can fail transiently; the event study then reports UNAVAILABLE with the
  provider reason instead of a fabricated figure (retry once it succeeds).
