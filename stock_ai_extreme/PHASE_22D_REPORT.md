# PHASE 22D — VERIFICATION & GAP-CLOSURE REPORT

Audit + additive build pass over the Phase 22 Crypto Volatility / Forecasting
feature. **Nothing was removed.** Phases 22A (data engine), 22B (quant engine)
and 22C (markets UI) remain intact; this pass verified them end-to-end against a
running localhost stack and **added** the surfaces that were computed on the
backend but never shown.

Measured on this machine: backend `127.0.0.1:8000`, frontend
`http://localhost:5173/crypto-terminal`.

## Overall status

**READY WITH FIXES** — the core feature is real, live and functional. The fixes
in this pass are additive (two new UI panels, one required column, one timestamp
field correction, load-test tooling, Redis cross-worker fan-out and its tests).
The only outstanding item is genuine 10,000-user scale proof, which was **not**
achievable on this host and is reported as NOT VERIFIED.

## What this pass changed (all additive)

| File | Type | Change |
|---|---|---|
| `frontend/src/components/crypto/CryptoForecastHistoryPanel.tsx` | new | Surfaces realised forecast performance + stored forecast history (spec §9/§20/§30/§31) using the already-existing but unused hooks. |
| `frontend/src/components/crypto/CryptoTargetHistoryPanel.tsx` | new | Surfaces the append-only target event timeline (spec §11/§40). |
| `frontend/src/pages/CryptoMarketTerminalPage.tsx` | edit | Renders the two new panels; fixes the footer freshness line to read `source_timestamp ?? fetched_at` (was `timestamp`, always N/A). |
| `frontend/src/components/crypto/CryptoTargetsPanel.tsx` | edit | Adds the required **First reached** column (spec §11 `first_reached_at`). |
| `backend/scripts/crypto_load_test.py` | new | Real HTTP + WebSocket load harness for spec §23 (writes a JSON report). |
| `backend/crypto_load_test_report*.json` | new | Measured evidence from this pass. |
| `backend/app/crypto/websocket/event_bus.py` | new | Redis pub/sub fan-out for the WS gateway (cross-worker), gated by `REDIS_URL`; local in-process bus otherwise. |
| `backend/app/crypto/websocket/manager.py` | edit | Routes normalized events through the bus; local behaviour unchanged. |
| `backend/app/crypto/config.py` | edit | Adds `CRYPTO_REDIS_PUBSUB` / `CRYPTO_REDIS_CHANNEL`. |
| `backend/app/crypto/tests/test_event_bus.py` | new | 7 tests covering local default, Redis publish/listen, and graceful degradation. |
| `frontend/scripts/crypto-panels-test.mjs` | new | CDP test asserting all crypto panels (including the new ones) render; `npm run test:crypto:panels`. |

## Real Data Verification

| Asset path | Provider | Evidence | Classification |
|---|---|---|---|
| BTC quote | Binance spot REST | `price 86460.24`, `bid/ask`, `high_24h 86912.75`, `change_percent_24h 3.138`, `source_timestamp 2026-10-02T11:23:24Z`, status `LIVE` | REAL |
| BTC candles | Binance klines | 1000× 1h candles, quality HIGH, `DATA COMPLETE`, 0 duplicate/out-of-order | REAL |
| Analytics | computed | EMA/RSI/ATR/returns/volatility/regime | CALCULATED |
| Forecast | computed | `exp_smoothing@1.0.0+crypto-features-v1`, prediction + empirical band | MODELLED |
| Targets | computed | derived swing ladder from real highs/lows | CALCULATED |
| Threshold | computed | empirical + GBM probability, walk-forward Brier | MODELLED |
| On-date | Binance candle | bar high 85649.95 vs threshold 85000 → ANSWERED true | REAL |
| Institutions | CoinGecko | disclosed holdings, attributed | REAL |
| Industry | internal taxonomy + provider categories | documented | DERIVED |

Configured providers: **Binance** (`api.binance.com`, keyless REST + WebSocket
`stream.binance.com`) primary, **CoinGecko** (`api.coingecko.com`, keyless)
metadata/fallback. Both were `AVAILABLE` in `/sources` and `/health`.

## Dummy / Fake Data Findings

No fake value can reach the production crypto path.

| File | Location | Data | Production reachable | Severity |
|---|---|---|---|---|
| `frontend/src/lib/crypto.ts:854/859` | WS client id | `Math.random()` used **only** to build a client id, never a value | no (identifier) | none |
| `frontend/src/lib/services.ts`, `psxMarket.ts`, `sentimentService.ts`, `SentimentPage.tsx` | legacy stock/index/sentiment pages | deterministic mock series | yes, but **other phases**, not crypto | pre-existing, out of scope |
| `IndexPage.tsx`, `MarketPage.tsx` | labels | rendered as `DEMO`/`MOCK FEED` | labelled, not silent | low |

`app/crypto/**` contains no `Math.random`, no `mock`, no `dummy`, no hardcoded
price/probability/target and no fake timestamp. The only `NotImplementedError`
occurrences are abstract base-class guards in `forecasting/baselines.py` and
`forecasting/models.py` — by design.

## Timeframe Verification

All eight are served: **5m, 15m, 1h, 4h, 1D, 1W, 1M native; 1Y roll-up** of 12
monthly candles (no exchange publishes yearly). Each is queried/cached per
`(symbol, timeframe)`; multi-timeframe computes each row from its own dataset
(observed distinct values: 5m trend SIDEWAYS/vol 0.314 vs 15m vol 0.260 …).
Timezone handling is UTC end-to-end; no look-ahead (validation is strictly past
prefix — leakage tests pass).

## Micro-Trend Verification

`trend.py` computes direction/strength/confidence from real returns, EMA
fast/slow slope, momentum, volume change, volatility and range position.
Outputs `UP / DOWN / SIDEWAYS / INSUFFICIENT DATA`; values are not hardcoded
(observed changing with the live tape). Confidence is capped and
INSUFFICIENT_DATA is first-class.

## Volatility Verification

`volatility.py` / `indicators.py`: rolling std, realised volatility, Wilder ATR,
range volatility, percentile from the asset's **own** distribution, and regime
`LOW/NORMAL/HIGH/EXTREME` derived from configurable percentiles. Observed:
1h `volatility_regime: NORMAL`, `atr_percent 0.1195` — computed, not fixed.

## Forecast Verification

- Baselines: naive, moving-average, exponential smoothing, trend extrapolation.
- ML (sample-gated): Ridge always; RandomForest / GradientBoosting when justified.
- Validation: **expanding-window walk-forward** (5 folds); no random split.
- Metrics: MAE / RMSE / MAPE / directional accuracy + baseline comparison.
- Honesty: on this tape **no ML model beat the baseline**, and the engine kept
  the baseline and reported `beats_baseline: false` — exactly as specified.
- Prediction interval: 80% **empirical residual** band, labelled MODELLED FORECAST.

## Target / Threshold Verification

Statuses (ACTIVE/REACHED/MISSED/EXPIRED/INVALIDATED), distance, distance %,
target date, touch counts, last-touch and first-reached timestamps are all
computed server-side from real candles. The only client-settable state is an
explicit INVALIDATED action, which is itself logged as an event.
Threshold on-date returned `ANSWERED true` with real candle evidence, and the
modelled probability is reported separately with walk-forward Brier score.

## Subcategory Verification

ALL / PRE-MARKET / INSTITUTIONS / TARGETS / INDUSTRY each hit a real endpoint.
PRE-MARKET honestly states crypto is 24/7 (no invented auction); INSTITUTIONS
returns attributed disclosures or NO VERIFIED DATA; TARGETS now also shows the
event timeline; INDUSTRY returns the documented taxonomy + provider categories.

## API Verification

All crypto routes returned real, shaped data with source + status + timestamps:
`assets`, `timeframes`, `sources`, `categories(+pre-session/institutions/
industry)`, `quote`, `candles`, `analytics`, `multi-timeframe`, `forecast(+history/
drift)`, `forecast-performance`, `targets(+history/ladder)`, `threshold`,
`on-date`, `health(+probe)`, `observability`, `persistence`, `rate-limit`.

## WebSocket Verification

Real client (`websockets`) against `ws://127.0.0.1:8000/api/v1/crypto/ws/<id>`:
`connected → subscribe BTC/5m → subscribed {channels} → snapshot (200 candles +
quote) → live ticks (price 86431.7, source binance)`. Reconnect/backoff and
fresh-snapshot-on-subscribe are implemented in `useCryptoSocket` + the gateway.
**Shared upstream confirmed:** 100 concurrent clients produced exactly **1**
upstream Binance stream (`upstream_streams: [BTCUSDT 5m]`) and coalescing was
observed (`coalesced` counter advancing). No per-user provider connection.

## Database / Redis Verification

`/persistence` reported real rows: assets 31, candles 9144, forecasts 157,
evaluations 69, targets 24, target_events 41, provider_health 133, categories
769 — all written by the background workers and request path. Cache is the
project's shared in-process TTL cache (entry-count exposed via `/observability`).
Redis is installed and used only for the **esports** event bus when `REDIS_URL`
is set. As of Phase 22D the **crypto** gateway also supports Redis pub/sub
fan-out (`app/crypto/websocket/event_bus.py`): with `REDIS_URL` set and
`CRYPTO_REDIS_PUBSUB=true`, an event routed on one worker reaches subscribers on
every worker. Without `REDIS_URL` (and with the `redis` package absent, as in
this audit venv) the gateway transparently uses the in-process bus — verified by
`test_event_bus.py` and observed live as `event_bus: {backend: local}`. Note the
upstream provider stream is still **one per worker** (one per process), never one
per user; true single-stream cross-worker ingest would need a leader, which was
not added.

## UI / UX Verification

Headless-Chrome (CDP) audit of `/crypto-terminal` at 1440px:
- ALL tab panels rendered: Micro trend, Volatility, Micro-trend timeline,
  MODELLED FORECAST, **REALISED Forecast performance** (new), **STORED Forecast
  history** (new), Data quality, Analytics, Multi-timeframe, Data sources.
- TARGETS tab: Target ladder (6 real levels) · Target comparison (with the new
  **FIRST REACHED** column) · Threshold analyzer · **Target event timeline** (43
  real events) (new).
- No uncaught exceptions, no console errors, no failed network requests, no
  horizontal overflow.
- Reproducible as a test: `npm run test:crypto:panels` (15/15 assertions pass,
  including the new panels and the FIRST REACHED column).

## Security Verification

Provider endpoints are public/keyless; no provider secret exists in the
frontend bundle. The crypto REST surface has its own per-IP rate limiter and
every input (symbol, timeframe, price, date, horizon) is validated by Pydantic /
`Query(...)` with 4xx on rejection. WS connections are bounded and can be
rejected (1013) rather than degrading everyone. No arbitrary HTML execution.

## Performance / 10,000-User Verification

Measured on this host with `scripts/crypto_load_test.py`:

| Level | Kind | Result |
|---|---|---|
| 100 | HTTP @ concurrency 10 | 100/100 OK, **p50 117 ms, p95 673 ms, p99 736 ms**, 54.6 rps, server RSS 468 MB, 0×429 |
| 100 | WebSocket | **100/100 connected**, 900 msgs (100 snapshots, 600 ticks), connect p50 135 ms, **1 upstream stream** |
| 1,000 | WebSocket (contended) | 154 established / 745 failed — single-worker + ~500 MB free RAM saturated |
| 5,000 | WebSocket | **2,328 established / 2,611 failed**, connect p50 **16.6 s**, p95 18.6 s; server `/health` unresponsive immediately after |
| 10,000 | WebSocket | **0 established / 10,000 failed** — the (still-listening) single worker was recovering from the 5k burst |
| 1,000 | HTTP | Rate-limited by the app's global middleware (429) before the crypto bucket; not a crypto result |

The 5k/10k runs were done against a single uvicorn worker on this laptop
(~500 MB free RAM, both processes sharing one CPU). They do **not** represent
production capacity: the server accepted 2,328 sockets at 5k, then its event
loop saturated (`/health` no longer answered within 8 s) and 10k established
zero while it was still recovering. **The 10,000-user target remains NOT
VERIFIED.** Architecture (one shared upstream stream per worker, stateless REST,
coalesced fan-out, per-process cache, optional Redis cross-worker fan-out) is
consistent with scale, but the spec requires measurement on adequate hardware
and there is none here. Keep the report honest: capacity is unproven.

## Missing / Not Implemented

- True single-stream cross-worker provider ingest (a leader/ingest worker);
  Redis only distributes the **fan-out**, each worker keeps one upstream stream.
- 5,000 / 10,000 concurrent-user capacity on adequate hardware (measured here,
  but the host saturated — result is NOT VERIFIED).

## Fixes / additions applied

1. Forecast history + realised performance now visible in the UI.
2. Target event timeline now visible; `first_reached_at` now shown.
3. Footer freshness line now reads the real source timestamp.
4. Redis pub/sub cross-worker fan-out for the crypto WS gateway (additive,
   `REDIS_URL`-gated, degrades to the in-process bus).
5. Backend event-bus tests (7) and a frontend CDP panel test (15 checks).
6. Crypto load-test harness + measured reports.

## Checks

| Check | Result |
|---|---|
| `pytest app/crypto/tests` (offline) | **197 passed** (190 + 7 new event-bus tests) |
| `pytest app/crypto/tests/test_real_data_trace.py` (live network) | **7 passed** |
| `node scripts/crypto-panels-test.mjs` (CDP) | **15/15 checks passed** |
| Live WebSocket client (connect→subscribe→snapshot→tick) | `WS_OK` after the bus change |
| `tsc --noEmit` | clean |
| `vite build` | success (`CryptoMarketTerminalPage` chunk) |
| Localhost | backend `:8000` 200, UI `:5173` 200, crypto terminal verified |

No real-money trading/wagering was added. Modelled outputs remain labelled
estimates, not guarantees.
