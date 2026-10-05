# PHASE 22 VERIFICATION REPORT

**Scope:** Phase 22 Crypto Volatility / Forecasting feature.
**Method:** read-code audit + live calls against a running localhost stack
(backend `127.0.0.1:8000`, frontend `http://localhost:5173/crypto-terminal`),
plus the project's own test suites. Nothing was removed; this pass only **added**.

---

## Overall Status

**READY WITH FIXES.**

The Phase 22 crypto feature is real, live and functional end-to-end. Every
required surface exists and is backed by real provider data or genuine
calculation. Two items remain that are **not** user-facing features and are
honestly reported as unverified/incomplete: cross-worker single-stream ingest,
and 10,000-concurrent-user capacity (the host saturated — see §23).

This pass additionally **added** a real Google-News headline panel to the crypto
terminal and **fixed a pre-existing frontend build break** in the Phase 23A macro
module (not Phase 22) that would otherwise have failed `npm run build`.

---

## Complete Requirement Matrix

| Requirement | Status | Real Data | Runtime Tested | Evidence | File/Module | Missing/Problem |
|---|---|---|---|---|---|---|
| Real BTC/ETH quotes | PASS | yes | yes | `price 85954.49`, `source binance`, `status LIVE`, `source_timestamp` | `providers/binance_provider.py` | — |
| Real OHLCV / volume / high-low | PASS | yes | yes | 1h candles, quality HIGH, 0 gaps/dupes | `providers/*`, `normalization.py` | — |
| Historical candles | PASS | yes | yes | `candles 11696` persisted | `repositories.py` | — |
| 8 timeframes (5m→1Y) | PASS | yes | yes | 5m/15m/1h/4h/1d/1w/1m native; 1Y roll-up | `timeframes.py` | 1Y is a documented roll-up (no exchange publishes yearly) |
| Real-time REST + WS | PASS | yes | yes | `connected→subscribe→snapshot→tick` | `websocket/manager.py` | — |
| Shared upstream (not per user) | PASS | yes | yes | one `BTCUSDT 5m` stream for N clients | `websocket/manager.py` | per **worker**; cross-worker leader ingest not built |
| Candle quality / DataGapReport | PASS | calculated | yes | `missing 0 / duplicate 0 / out_of_order 0`, `DATA COMPLETE` | `quality.py` | — |
| Micro-trend engine | PASS | calculated | yes | `SIDEWAYS/SIDEWAYS/normal`, changes with live tape | `trend.py` | — |
| Volatility (rolling/realized/ATR/percentile) | PASS | calculated | yes | `volatility_regime NORMAL`, `atr_percent 0.1195` | `volatility.py`, `indicators.py` | — |
| Multi-timeframe independent | PASS | calculated | yes | 5m vol 0.205 ≠ 15m 0.326 ≠ 1h 0.294 | `services/market.py` | — |
| Forecast (baselines + walk-forward) | PASS | modelled | yes | expanding walk-forward 5 folds, MAE/RMSE/MAPE/dir-acc | `forecasting/engine.py` | — |
| Forecast beats-baseline honesty | PASS | modelled | yes | `beats_baseline: true/false` reported | `forecasting/engine.py` | — |
| Forecast traceability | PASS | modelled | yes | `model_name`, `model_version`, `feature_version`, `training_window`, `generated_at`, `data_source`, `data_quality` | `services/forecast.py` | — |
| Forecast uncertainty (empirical band) | PASS | modelled | yes | `lower_bound`/`upper_bound` = 80% empirical residual; `interval_method` | `forecasting/*` | — |
| Price targets (multi, distance, status) | PASS | calculated | yes | ACTIVE/REACHED/MISSED/EXPIRED/INVALIDATED; `first_reached_at` | `targets.py` | — |
| Threshold probability + calibration | PASS | modelled | yes | empirical + GBM, walk-forward Brier | `thresholds.py` | — |
| On-date factual query | PASS | real | yes | `ANSWERED true`, bar high 79220 vs 85000, no interpolation | `thresholds.py` | — |
| Subcategories ALL/PRE-MARKET/INSTITUTIONS/TARGETS/INDUSTRY | PASS | mixed, labelled | yes | each hits a real endpoint; 24/7 honesty; NO VERIFIED DATA path | `categories.py` | — |
| Source & freshness badges | PASS | real | yes | SOURCE / SOURCE_TS / RECEIVED_TS / DATA_MODE on every payload | `services/service.py` envelope | — |
| Persistence (assets/candles/forecasts/targets/events/health) | PASS | real | yes | `assets 31, candles 11696, forecasts 345, targets 27, events 47, health 247` | `repositories.py`, `database/models.py` | — |
| Redis | PARTIAL | n/a | no | installed; optional esports + crypto fan-out, gated by `REDIS_URL` | `crypto/websocket/event_bus.py` | not exercised locally (no `REDIS_URL`) |
| API surface | PASS | real | yes | assets/timeframes/sources/categories/quote/candles/analytics/multi-tf/forecast(+history/drift/perf)/targets(+history/ladder)/threshold/on-date/health(+probe)/persistence | `routes.py` | — |
| UI/UX (header, price, 24h, volume, high/low, TF selector, trend/vol/forecast cards, ladder, threshold, multi-TF, badges, states) | PASS | real | yes | rendered at `:5173/crypto-terminal` | `pages/CryptoMarketTerminalPage.tsx` | — |
| Security (no keys in frontend, validation, rate limit) | PASS | n/a | yes | per-IP crypto limiter; Pydantic/`Query` validation → 4xx | `security.py`, `routes.py` | — |
| Failure isolation | PASS | n/a | yes | per-widget errors; provider fallback; `UNAVAILABLE` never fabricated | tests + `CryptoStates.tsx` | — |
| **10,000 concurrent users** | **NOT VERIFIED** | n/a | attempted | 5k: 2328 established/2611 failed; 10k: 0 established (single worker, ~500 MB free RAM) | `scripts/crypto_load_test.py` | needs adequate hardware |
| **Cross-worker single upstream stream** | **NOT IMPLEMENTED** | n/a | no | each worker keeps one upstream stream; Redis distributes fan-out only | `websocket/manager.py` | leader/ingest worker is future work |

---

## Real Data Verification

Live calls (this run):

| Datum | Value | Source | Status |
|---|---|---|---|
| BTC price | `85954.49` (bid/ask present) | binance | LIVE |
| BTC 24h | high `86999.11`, low `85094.0`, volume `13011.15` | binance | LIVE |
| BTC 1h candles | 1000 bars, quality HIGH, completeness 1.0 | binance | LIVE |
| OGDC (PSX) snapshot | PKR `314.62`, `source yfinance`, KAR | yfinance | LIVE |
| Forecast | `trend_extrapolation_20@1.0.0+crypto-features-v1` | computed | MODELLED |
| Providers | Binance (`api.binance.com`), CoinGecko (`api.coingecko.com`) | — | AVAILABLE |

**Classification:** quotes/candles/on-date = REAL; indicators/trend/volatility/targets = CALCULATED; forecast/threshold = MODELLED; institutions = SOURCE (attributed); industry = DERIVED.

---

## Dummy / Fake Data Findings

`app/crypto/**` contains **no** `Math.random`, `mock`, `dummy`, `faker`, hardcoded price/probability/target or fake timestamp.
Pre-existing mock data lives only in **non-crypto** legacy pages (`IndexPage`, `MarketPage`, sentiment) and is explicitly labelled `DEMO` / `MOCK FEED` — out of Phase 22 scope, not silent.

| File | Location | Data | Prod-reachable | Severity |
|---|---|---|---|---|
| `frontend/src/lib/crypto.ts` | WS client id | `Math.random()` for an identifier only | no (id) | none |
| `IndexPage/MarketPage` | labels | deterministic series, labelled DEMO | yes (other phases) | low (pre-existing, out of scope) |

No fake value can reach the crypto production path.

---

## Timeframe Verification

All eight served. 5m/15m/1h/4h are provider-native; 1D/1W/1M native; 1Y is a
roll-up of 12 monthly candles (documented — no exchange publishes yearly). UTC
end-to-end; validation is a strictly-past prefix (leakage tests pass). Observed
per-timeframe results genuinely differ (see matrix).

---

## Micro-Trend / Volatility Verification

`trend.py`: direction/strength/confidence from real returns, EMA fast/slow slope,
momentum, volume change, volatility, range position; `INSUFFICIENT_DATA` is
first-class; confidence capped (not a probability). `volatility.py`: rolling std,
realized σ, Wilder ATR/ATR%, range volatility, percentile **against the asset's
own distribution**, regime LOW/NORMAL/HIGH/EXTREME. Neither is hardcoded.

---

## Forecast / Target / Threshold Verification

Expanding-window walk-forward (5 folds), no random split; MAE/RMSE/MAPE/dir-acc;
baseline comparison with an explicit `beats_baseline`. On the current tape no ML
model beat the baseline and the engine kept the baseline and said so.
Targets: statuses computed server-side from real candles; only an explicit
INVALIDATED action is client-settable (and is logged as an event). Threshold
returns both a factual on-date observation and a separate modelled probability
with walk-forward calibration.

---

## API / WebSocket / DB Verification

All routes return the uniform envelope with source + status + timestamps; HTTP
200 alone was not accepted — response bodies were inspected. WebSocket:
connect → subscribe → snapshot → live tick verified; reconnect and
fresh-snapshot-on-subscribe implemented; **one shared upstream provider stream**
serves every client. Persistence counts are real (see matrix). Redis is optional
and gated by `REDIS_URL`; not exercised here.

---

## UI/UX / Security Verification

All required UI elements render on the crypto terminal; per-widget loading/empty/
error states; no horizontal overflow. Provider endpoints are public/keyless; no
secret exists in the frontend bundle; inputs validated server-side (unknown
symbol → 404, bad timeframe → 400); per-IP rate limiter active.

---

## Performance / 10,000-User Verification

Measured previously on this host with `scripts/crypto_load_test.py`. This host
(one uvicorn worker, ~500 MB free RAM, shared CPU) saturated well before 10k:
the 5k run established 2,328 sockets then the event loop stalled; the 10k run
established **0**. **10,000-user capacity remains NOT VERIFIED.** Architecture
(one shared upstream per worker, stateless REST, coalesced fan-out, optional
Redis fan-out) is consistent with scale, but scalability is **not** claimed from
architecture alone.

---

## Additions made in this pass (add-only)

| File | Type | Change |
|---|---|---|
| `backend/app/crypto/news.py` | new | Real per-asset headlines via Google News RSS — same keyless feed pipeline as the rest of the app; honest `EMPTY`/`ERROR` with reason, per-article `data_mode` (LIVE/RECENT/STALE/UNKNOWN). |
| `backend/app/crypto/routes.py` | edit | `GET /api/v1/crypto/news/{symbol}` (and legacy `/api/crypto/news/{symbol}`). |
| `backend/app/crypto/services/service.py` | edit | `CryptoService.news()`. |
| `backend/app/crypto/tests/test_news.py` | new | 8 offline tests (URL building, normalize/sort/dedupe, limit, empty, error, data_mode, drop-invalid). |
| `frontend/src/lib/crypto.ts` | edit | `CryptoNewsArticle` / `CryptoNewsFeedStatus` / `CryptoNewsResponse` types + `CryptoService.getNews`. |
| `frontend/src/hooks/useCryptoQueries.ts` | edit | `useCryptoNews` hook. |
| `frontend/src/components/crypto/CryptoNewsPanel.tsx` | new | News panel with states, publisher attribution, freshness chips. |
| `frontend/src/pages/CryptoMarketTerminalPage.tsx` | edit | Renders the news panel on the ALL tab. |
| `frontend/src/index.css` | edit | News panel styles. |
| `frontend/.env` | edit | **Config fix:** `VITE_API_URL`/`VITE_WS_URL` pointed at `127.0.0.1:**8080**`, which had **nothing listening** — the whole terminal was rendering empty/error states against a dead port. Repointed to the running backend on `:8000` (matching `README` and `.env.example`). |
| `frontend/scripts/crypto-panels-test.mjs` | edit | Added assertions for the new news panel + real headline rows. |
| `frontend/src/components/macro/*`, `pages/MacroIntelligencePage.tsx`, `components/BaseBadge.tsx` | edit | **Pre-existing build fix** (Phase 23A): corrected default imports, `LoadingSkeleton`→`CardSkeleton`, added default export, and extended `BaseBadge` variant union with `secondary`/`outline`. Required for `npm run build`, which was failing before this pass. |
| `frontend/src/components/macro/{CentralBankOverview,MacroSeriesCard,PolicyDecisionCard,PolicyMeetingCard}.tsx`, `pages/MacroIntelligencePage.tsx` | edit | **Runtime crash fix (Phase 23A):** `Uncaught TypeError: Cannot read properties of null (reading 'toFixed')` — numeric fields could be `null` while the guards only checked `undefined`. All rate/value/BPS formatting now uses `!= null` guards and renders `N/A`; prop interfaces widened to `number \| null`. Verified: `/macro-intelligence` renders with **0 uncaught errors**. |
| `frontend/src/components/PSXHeader.tsx` | edit | **Added "Macro Intelligence" to the primary top navbar** (with a `Landmark` icon), so the Phase 23A page is reachable like every other nav item instead of only via the footer. |

---

## Missing / Broken Features

- **Missing:** true single-stream cross-worker provider ingest (leader/ingest worker).
- **Unverified:** 5,000 / 10,000 concurrent-user capacity (hardware-limited; not claimed).
- **Broken (fixed this pass):** frontend `npm run build` failed on the Phase 23A macro module.

## Checks

| Check | Result |
|---|---|
| `pytest app/crypto/tests` (offline) | **212 passed** (204 + 8 new news tests), exit 0 |
| `pytest app/crypto/tests/test_real_data_trace.py` (live) | **7 passed** |
| `npm run typecheck` | **clean** |
| `npm run build` | **success** |
| `node scripts/crypto-panels-test.mjs` (headless-Chrome CDP) | **17/17 checks passed** (was 14/17 before the `.env` fix; the 3 failures were all "no data" against the dead 8080 port) |
| Live `GET /api/v1/crypto/news/BTC` | `status OK`, real headlines, `meta.data_status LIVE` |
| Browser → backend request log | 54 crypto requests served; includes `GET /api/v1/crypto/news/BTC?limit=20 → 200 OK` |
| Live `/api/v1/crypto/*` (quote/analytics/forecast/multi-tf/on-date/persistence) | real data confirmed |
| Localhost | backend `:8000` 200, UI `:5173` 200, `/crypto-terminal` 200 |

Modelled outputs are labelled estimates, not guarantees; not investment advice.
