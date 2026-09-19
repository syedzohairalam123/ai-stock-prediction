# Neural Market — Extreme Python AI Stock Analytics Platform

This ZIP is a complete, runnable **full-stack starter project** for educational stock analysis. It includes a Python FastAPI backend, real market-history retrieval through `yfinance`, technical-analysis calculations, machine-learning forecasting, an optional TensorFlow LSTM model, a live WebSocket stream, and a premium React dashboard.

> **Financial-risk notice:** Every prediction is a statistical estimate based on historical data. It can be wrong, it does not account for all market information, and it is not investment advice. Do not use it as the sole basis for buying, selling, or managing money.

## What is Included

| Area | Included capability |
|---|---|
| Python API | FastAPI REST endpoints, OpenAPI/Swagger docs, CORS configuration, health endpoint |
| Data Agent | Downloads historical OHLCV market data and standardizes it asynchronously |
| Analysis | SMA 10/30, EMA 10/26, RSI 14, MACD and signal, Bollinger Bands, daily returns |
| ML Forecasts | Random Forest and Ridge Regression with chronological validation |
| Deep Learning | Optional TensorFlow/Keras LSTM close-price forecaster |
| Forecast confidence | 95% band calculated as forecast plus/minus 1.96 times validation RMSE |
| Insights Agent | Trend, RSI momentum, volatility, validation-error and risk-level explanations |
| Live capability | WebSocket endpoint polling the provider on a configurable interval |
| Frontend | React + TypeScript + Plotly dashboard with live quote reconnect hook |
| Deployment | Dockerfile, docker-compose file and Render Blueprint starter |

## Project Tree

```text
stock_ai_extreme/
├── backend/
│   ├── app/
│   │   ├── main.py           # REST routes and WebSocket server
│   │   ├── agents.py         # DataAgent, PredictionAgent, InsightAgent
│   │   ├── lstm_agent.py     # Optional TensorFlow LSTM model
│   │   ├── indicators.py     # Technical indicator calculations
│   │   └── config.py         # Environment configuration
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/App.tsx           # Dashboard UI and API requests
│   ├── src/hooks/useStockWebSocket.ts  # reconnecting live WebSocket hook
│   └── src/index.css         # responsive neon/glass visual design
├── Dockerfile
├── docker-compose.yml
└── render.yaml
```

## Backend Installation

### Prerequisites

- Python 3.11 or newer
- Internet connection for market-data requests
- Node.js 20+ only if you will run the React frontend
- TensorFlow may be slow or unavailable on some machines; Random Forest works without GPU and is the recommended first test.

### Windows PowerShell

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

### macOS / Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

After startup, visit `http://127.0.0.1:8000/docs`. Swagger provides an interactive page where every REST route can be tested without the frontend.

## Frontend Installation

The ZIP already contains frontend source files and `package.json`.

```bash
cd frontend
npm install
npm run dev
```

Open the URL shown by Vite, normally `http://localhost:5173`. Keep the backend running at `http://127.0.0.1:8000`.

### Frontend Flow

1. Enter a ticker such as `AAPL`, `MSFT`, `TSLA`, or a valid market-provider symbol.
2. The dashboard requests two years of historical data.
3. It requests a seven-day forecast using the currently selected model.
4. Plotly renders history, a dotted forecast line, and a confidence area.
5. `useStockWebSocket` opens `ws://127.0.0.1:8000/ws/stock/TICKER`.
6. If the socket disconnects, the hook retries after three seconds.
7. The API polls the data provider every `LIVE_POLL_SECONDS` and sends the newest available close/quote value.

## API Reference

### `POST /api/stocks/{ticker}/history`

Loads OHLCV data and calculated indicators.

```json
{"start":"2024-01-01","end":"2026-01-01","interval":"1d"}
```

### `POST /api/stocks/{ticker}/predict`

Creates a forecast. Supported values: `rf`, `ridge`, `lstm`.

```json
{"start":"2024-01-01","end":"2026-01-01","horizon":7,"model":"rf","lstm_epochs":20}
```

Response includes `predictions`, `model_metrics`, `insights`, and the investment-risk disclaimer.

### `WS /ws/stock/{ticker}`

Streams JSON messages like:

```json
{"type":"price","ticker":"AAPL","price":210.12,"timestamp":"2026-09-03 00:00:00"}
```

## Agent Logic

### DataAgent

`DataAgent.history()` calls `yfinance` in a background thread so a blocking provider request does not block FastAPI's async event loop. It requests OHLCV records, removes incomplete rows, and passes the data to the indicator pipeline.

### Indicator Engine

The engine produces trend, momentum, volatility, and band features:

- **SMA / EMA:** smooth price history for short- and medium-term trend signals.
- **RSI:** compares average upward and downward movement over 14 periods.
- **MACD:** compares fast and slow exponential averages; a signal line smooths MACD.
- **Bollinger Bands:** estimate a moving range around the 20-period average.
- **Returns:** price changes used for rolling volatility.

### Random Forest / Ridge Agent

For the tabular models, the target is the next trading day's close. The input has OHLCV and technical-indicator values. `TimeSeriesSplit` is used instead of random shuffling to preserve chronology and reduce future-data leakage during evaluation. The final model retrains on the complete selected range, then predicts recursively for the requested horizon.

### LSTM Agent

The LSTM uses 30-day close-price sequences, MinMax scaling, two LSTM layers, dropout, dense layers, early stopping, and an 80/20 chronological holdout. Use it for an advanced demonstration, but it is computationally heavier and its predictions are not automatically better than Random Forest.

### Confidence and Risk

The interval is:

```text
lower = prediction - 1.96 × validation_RMSE
upper = prediction + 1.96 × validation_RMSE
```

It is a simple error-based uncertainty estimate, not a guaranteed 95% market-probability interval. Risk labels combine 30-day volatility and validation RMSE: LOW, MEDIUM, or HIGH.

## Environment Variables

| Variable | Meaning | Default |
|---|---|---|
| `CORS_ORIGINS` | Comma-separated frontend domains permitted to call the API | `http://localhost:5173` |
| `DEFAULT_PREDICTION_HORIZON` | Default horizon setting for future extension | `7` |
| `LIVE_POLL_SECONDS` | WebSocket provider polling interval | `20` |
| `MODEL_DIR` | Planned location for persisted model artifacts | `artifacts/models` |

## Docker

From the project root:

```bash
cp backend/.env.example backend/.env
# Windows: copy backend\.env.example backend\.env
docker compose up --build
```

The API will be available on `http://localhost:8000/docs`. The supplied compose configuration starts the backend. For production, build the frontend separately and host its static output through a CDN or frontend service.

## Render Deployment

1. Push this folder to a GitHub repository.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render detects `render.yaml`.
4. Replace `https://YOUR-FRONTEND-DOMAIN` in `CORS_ORIGINS` with the deployed frontend URL.
5. Deploy the React frontend separately as a Render Static Site, Vercel, Netlify, or another static host.
6. Deploy the React frontend separately as a Render Static Site, Vercel, Netlify, or another static host, setting `VITE_API_URL` and `VITE_WS_URL` (see `frontend/.env.example`) to your deployed HTTPS/WSS API domain at build time.

## Important Production Upgrades

This is a high-quality educational starter, not an exchange-trading system. Before production use, add a licensed live-data provider, provider fallback and rate-limit handling, Redis cache/pub-sub, PostgreSQL, authentication, password hashing, role control, secret management, audit logging, structured logs, monitoring, tests, background jobs, robust market-calendar handling, model-version registry, data-quality checks, walk-forward backtesting, and calibrated conformal prediction intervals.

`yfinance` data availability and timing can vary. Free sources often have delayed quotes, restrictive rate limits, missing exchanges, or terms that do not allow commercial redistribution. Check each provider's license and use a licensed real-time feed where required.

## What's New — Phase 1 + Phase 2 (this update)

Following the 21-phase roadmap, this pass did **Phase 1 (Foundation Cleanup)**, **Phase 2 (Real Market Data Layer)**, and a small slice of **Phase 4** (company profile). It deliberately did *not* touch Phases 3, 5–21 (database, advanced charts, GRU/Transformer models, news/sentiment, crypto/forex, 3D, auth, etc.) — see the full roadmap in `NEURAL-MARKET-BUILD-PROMPT.md` for what's next, and do those one phase at a time.

**Fixed (real bugs, not style nits):**
- `frontend/src/App.tsx` and `useStockWebSocket.ts` hardcoded `127.0.0.1` — a deployed frontend would keep calling your laptop. Now read from `VITE_API_URL` / `VITE_WS_URL` (see `frontend/.env.example`), with the old localhost values kept only as a local-dev default.
- `frontend/package.json` pinned every dependency to `"latest"` — now uses caret-ranged real version numbers, and build tooling (`vite`, `typescript`, `@vitejs/plugin-react`) moved into `devDependencies` where it belongs.
- The frontend had no `tsconfig.json` and no `vite.config.ts` — `@vitejs/plugin-react` was listed as a dependency but never actually wired up. Both files now exist; `npm run build` was run end-to-end to confirm it compiles and bundles.

**Added — provider abstraction layer (`backend/app/providers/`):**
- `base.py` — the `MarketDataProvider` interface, `DataStatus` (LIVE/RECENT/CACHED/STALE/UNAVAILABLE), `Quote`/`HistoryResult` types.
- `yfinance_provider.py` — the original yfinance call, now with retry + exponential backoff and freshness classification. Also adds `get_profile()` (sector/country/website/summary) — the one genuinely useful idea carried over from the earlier "Warren" project, which this codebase didn't have yet.
- `finnhub_provider.py` — optional live-quote fallback. Inactive unless you set `FINNHUB_API_KEY`; the app runs fine without it.
- `cache.py` — a simple in-memory TTL cache (Phase 3 can swap this for Redis without touching any caller).
- `manager.py` — tries providers in order, caches successes, falls back to a stale cached value only as a last resort, and never fabricates a price when everything fails (`status: "UNAVAILABLE"` instead).
- `agents.py`'s `DataAgent` now goes through the manager instead of calling `yfinance` directly. `main.py` gained `GET /api/stocks/{ticker}/profile` and `GET /api/system/health`, and `/history`/`/predict` responses now include a `meta`/`data_meta` block with `source` + `status`. The WebSocket stream uses the same resilient path.
- Frontend: added a Company Profile card and a small `LIVE`/`CACHED`/etc. freshness badge next to the price, so the UI is honest about how fresh what it's showing actually is.

**Tested — how, and the one real limitation to know about:**
This sandbox's network access is restricted to package registries (pypi/npm/GitHub) and cannot reach yfinance, Finnhub, or any other live data API directly — confirmed directly (`curl` to each returned `403`). So:
- 33 automated tests (`backend/tests/`, `pytest`) cover the cache, both providers, the manager's fallback/caching/status logic, and the FastAPI routes — all with the actual network calls mocked, not with real market data. All 33 pass. (One real bug was caught and fixed this way: the cache was deleting expired entries on read, which silently broke the "serve stale data if every provider is down" fallback.)
- The frontend was verified with a real `npm install`, `npx tsc --noEmit`, and a full `npm run build` — all succeed.
- **Not verified here:** an actual live network call to yfinance/Finnhub returning real prices. Run `uvicorn app.main:app --reload` yourself (from an environment with normal internet access) and open the dashboard to see it pull real data — that part needs your machine, not this sandbox.

**Also worth knowing:** `npm install` reports one moderate, dev-server-only advisory in `esbuild`/`vite` (arbitrary sites can probe the local dev server) — it doesn't affect production builds, but running `npm audit fix --force` later (a Vite major-version bump) is worth doing as a deliberate, tested step, not blindly.

## What's New — Phase 3, 5, 6, 7, 8, 9, 16 (this update)

This pass covers, in the same "real code + real tests, one phase at a time" spirit as Phase 1/2: **Phase 3** (database), **Phase 5** (more indicators), **Phase 6** (baseline hardening), **Phase 7** (GRU + ensemble), **Phase 8** (conformal prediction), **Phase 9** (backtesting), and **Phase 16** (watchlist). Still not done — and not attempted this round, on purpose — are news/sentiment, macro, crypto/forex/commodities, the LLM/RAG briefing layer, 3D analytics, auth, and production deployment hardening (Phases 10–15, 17–21).

**A real bug found and fixed while building this:** the original RSI formula (`100 - 100/(1+gain/loss)`) divided by a NaN-replaced zero whenever a 14-day window had *no down days at all* — a strong, steady uptrend — which silently turned RSI into `NaN` for that row instead of the mathematically-correct value of 100. On real, choppier stock data this rarely bites, but it's a genuine correctness bug (found because the Phase 9 backtest tests use a smooth synthetic uptrend and every single row came back empty). Fixed: zero-loss now correctly resolves to RSI=100, zero-movement to a neutral 50, and a regression test locks this in (`test_rsi_handles_zero_loss_window_without_producing_nan`).

**Phase 3 — Database (`backend/app/db.py`, `models.py`, `repository.py`):** SQLite by default via `DATABASE_URL` (swap to Postgres later with zero code changes). Tables: `prediction_history` (every prediction the app has ever actually made — the real record Phase 9's future accuracy-tracking would read from) and `watchlist_items`. No Alembic yet — `create_all()` on startup is honest for a schema this small; add migrations once the schema needs to evolve.

**Phase 5 — More indicators (`indicators.py`):** ATR (Wilder-smoothed), a 14-day rolling VWAP approximation (true intraday VWAP needs tick data we don't have on daily bars — documented in the code), Stochastic %K/%D, and ADX with +DI/-DI. All bounded/sanity-checked in `test_indicators.py`.

**Phase 6 — Baseline hardening (`baselines.py`):** naive-persistence and 10-day moving-average baselines, computed and returned in every `/predict` response as `baseline_comparison`, with an explicit `beats_naive_baseline` boolean — a model that loses to the trivial baseline says so, it isn't hidden.

**Phase 7 — GRU + Ensemble (`gru_agent.py`, `recurrent_models.py`, `ensemble.py`):** LSTM and the new GRU now share one training function (`recurrent_models.forecast_recurrent`) instead of duplicated code. `model: "ensemble"` combines RF + Ridge (always) with LSTM + GRU (only if TensorFlow is available — degrades gracefully, never crashes) via inverse-RMSE weighting, and reports `model_disagreement` per date as a genuine uncertainty signal rather than averaging it away.

**Phase 8 — Conformal prediction (`conformal.py`):** replaces the flat `±1.96×RMSE` band (which assumes Gaussian, stationary errors) with split-conformal calibration on a held-out chronological slice — an empirically-validated ~90%-coverage interval (see `test_empirical_coverage_is_reasonably_close_to_target_on_unseen_test_data`), not a guess. Falls back to the old RMSE band only when there's too little data to calibrate on. `model_metrics.interval_method` tells you which one was actually used.

**Phase 9 — Walk-forward backtesting (`backtest.py`, `POST /api/stocks/{ticker}/backtest`):** expanding-window, periodic-refit backtest (never a shuffled/leaky split) reporting MAE/RMSE/directional accuracy plus one illustrative default paper strategy's total return, max drawdown, and win rate against a buy-and-hold benchmark — explicitly labeled as one simple strategy for illustration, not a recommendation.

**Phase 16 — Watchlist (`GET/POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`):** persisted via Phase 3's database; the frontend's new Watchlist panel lets you add/remove/click-to-switch tickers.

**Frontend additions:** GRU/Ensemble entries in the model selector; a baseline-comparison badge next to the model metrics; SMA/EMA/Bollinger overlay toggles on the main chart; a new indicators section with RSI/MACD/Stochastic/ADX mini-charts; a Watchlist panel; a Backtest panel. Verified with `npx tsc --noEmit` and a full `npm run build` (50 modules, succeeds).

**Testing:** 72 automated backend tests now (up from 33), still all against mocked/synthetic data for the same reason as before — this sandbox cannot reach real market-data APIs (confirmed via direct `curl`, all return 403). Every new module (`baselines`, `conformal`, `ensemble`, `backtest`, `db`/`repository`, the expanded `indicators`) has its own dedicated test file, plus new end-to-end route tests for the ensemble model, baseline comparison, backtest endpoint, prediction-history persistence, and the watchlist CRUD flow.

## What's New — Phase 12, 13, 14, 17, 18, 19 (this update)

This pass adds **Phase 12** (cross-asset), **Phase 13** (crypto/commodities/forex), **Phase 14** (AI briefing), **Phase 17** (smart alerts), **Phase 18** (model monitoring/drift), and **Phase 19** (rate limiting + input validation). Deliberately not attempted, and worth being upfront about: **Phase 10/11** (real news + macro/FRED — genuinely new external data sources, kept out of this round to stay focused), **Phase 15** partially covered (see below), and **Phase 16/20/21** already exist in earlier phases or are ongoing rather than one-shot.

**A real bug found while wiring this round together:** the `client` test fixture created a `TestClient(app)` without ever triggering FastAPI's `lifespan` startup event (which is what calls `init_db()`) — so tests only passed because *another test file* happened to call `init_db()` first and alphabetical collection order papered over it. Running the new monitoring test in isolation immediately surfaced `no such table: prediction_history`. Fixed by calling `init_db()` explicitly in the fixture instead of depending on lifespan firing or file execution order — a classic hidden-test-order dependency, exactly the kind of thing that looks fine until someone runs one file on its own.

**Phase 12 — Cross-asset intelligence (`cross_asset.py`, `POST /api/cross-asset/report`):** correlation matrix, beta, and relative-strength across any tickers you name, computed on returns (never raw price levels — those are almost always spuriously correlated) from data already fetched through the Phase 2 provider layer. No new data source needed.

**Phase 13 — Crypto/commodities/forex (`multi_asset.py`, `GET /api/markets/{class}`):** reuses the existing yfinance-backed provider rather than bolting on a redundant new one — yfinance already quotes `BTC-USD`, `GC=F`, `EURUSD=X` through the exact same interface as stocks. A single bad symbol degrades gracefully (`status: UNAVAILABLE` for that one card) instead of failing the whole category.

**Phase 14 — AI market briefing (`llm_briefing.py`, `POST /api/stocks/{ticker}/briefing`):** optional, needs your own `ANTHROPIC_API_KEY` — reports `UNAVAILABLE` cleanly without it, exactly like the Finnhub provider. The model is only ever handed data this endpoint already computed and is explicitly instructed not to state a number that isn't in that data; the frontend panel shows the exact JSON the briefing was grounded in so you can check it yourself. Model name is configurable (`ANTHROPIC_MODEL`), not hardcoded to something that'll silently go stale.

**Phase 17 — Smart alerts (`alerts.py`, `POST/GET /api/alerts`, `DELETE /api/alerts/{id}`, `POST /api/stocks/{ticker}/alerts/check`):** price-above/below, % daily move, RSI overbought/oversold. Checking evaluates against freshly fetched real data, never a simulated trigger; a triggered alert is marked resolved with the value that fired it, not silently deleted.

**Phase 18 — Model monitoring (`monitoring.py`, `POST /api/monitoring/resolve`, `GET /api/monitoring/drift`):** built entirely on Phase 3's `prediction_history` — once a forecast's target date has passed, `/resolve` fetches the real close that happened and records it, and `/drift` compares recent resolved-prediction error against the historical average to flag possible drift. This is genuine accuracy tracking against real predictions the app actually made, not a simulation.

**Phase 19 — Security & performance (`security.py`):** a dependency-free in-memory sliding-window rate limiter (120 req/min/IP by default, `/health`/`/docs` exempt) and ticker-format validation applied across every route that takes a ticker — rejects obviously malformed input before it reaches a provider call.

**Phase 15 note (3D analytics):** not a full separate phase yet, but the cross-asset report now includes `asset_stats` (return / volatility / volume per ticker) and the frontend's new Cross-Asset panel renders a real 3D scatter (Plotly `scatter3d`) from it — return, volatility, and volume as the three axes, colored by return. It's a genuine analytical view of the data already being computed, not decoration; a full 3D risk-landscape / prediction-surface treatment is still future work.

**Frontend additions:** a Markets Overview panel (crypto/commodities/forex tabs), a Cross-Asset panel (correlation heatmap + the 3D map + a beta/relative-strength table), an Alerts panel (create/list/check/delete), a Model Health indicator (drift status), and an AI Briefing panel with graceful unavailable/error states. Verified with `npx tsc --noEmit` and a full `npm run build` (55 modules, succeeds).

**Testing:** 131 automated backend tests now (up from 72) — `cross_asset`, `multi_asset`, `alerts`, `monitoring`, `llm_briefing`, and `security` each have dedicated test files, plus new end-to-end route tests for every new endpoint. All still against mocked data for the reason explained above; `llm_briefing`'s tests mock the HTTP call the same way the Finnhub provider's tests do, since no real Anthropic API key is available in this sandbox either (confirmed: `api.anthropic.com` is reachable, but authentication correctly fails with no key configured).

## What's New — Phase 10 (news/sentiment), notifications, background jobs, portfolio, bug fixes (this update)

This pass added **Phase 10 (news + sentiment)**, **alert notifications**, a **background maintenance loop**, a **portfolio tracker**, **CSV export**, and fixed three real bugs found in the existing code. Nothing was removed — every prior feature still works exactly as before.

**Real bugs fixed:**
- **WebSocket crash (`RuntimeError: Cannot call "send" once a close message has been sent.`)** — when a client disconnected mid-stream, the inner `except` tried to send an error on the already-closed socket and the whole handler crashed, spamming the log on every disconnect. The loop now breaks cleanly on `WebSocketDisconnect` and guards the error-send so a dead socket can't raise. (This was visible in `uvicorn.log` before the fix.)
- **Unbounded in-memory cache** — `TTLCache.purge_expired()` existed but was never called, so a long-running server would accumulate expired entries forever. The background loop now calls `manager.purge_caches()` every interval.
- **Rate-limiter memory growth** — `RateLimiter._hits` kept a bucket per distinct client IP forever. Added `RateLimiter.cleanup()` (idle buckets dropped) and wired it into the same background loop.

**Phase 10 — News + sentiment (`news.py`, `GET /api/stocks/{ticker}/news`):** headlines come through the same provider layer as prices (yfinance's feed — no new data source or API key), and each headline is scored by a small dependency-free finance lexicon with a bullish/bearish/neutral label plus an aggregate roll-up. It's explicitly labelled a heuristic, not an NLP model, in both the API response and the UI. The provider normalizer handles **both** yfinance news shapes (the legacy flat items and the newer nested `content` block) because the upstream format has changed before and will again — verified against real live data.

**Alert notifications (`notifications.py`):** when an alert triggers (via the background loop or the manual check), the app can push to **Telegram** (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) and/or **email** (any SMTP server via `SMTP_*` env vars). Both are strictly optional — with nothing configured, `notify()` just logs the message and nothing else breaks. `requests` for Telegram, stdlib `smtplib` for email — no new dependencies.

**Background maintenance loop (`jobs.py`):** started in FastAPI's lifespan, this single asyncio task periodically (1) checks every active alert against freshly fetched data and notifies when something fires, (2) resolves prediction records whose target date has passed so drift monitoring stays current without anyone clicking a button, and (3) purges caches + rate-limiter buckets. Every job is isolated — one failure never takes down the loop or the API. Disable with `BACKGROUND_JOBS_ENABLED=false`; interval via `BACKGROUND_INTERVAL_SECONDS`.

**Portfolio tracker (`portfolio.py`, `models.PortfolioHolding`, `GET/POST /api/portfolio`, `PATCH/DELETE /api/portfolio/{id}`):** track positions (ticker, shares, average cost) in the existing database. Current prices are always fetched live at read time — never stored — so market value, P&L, and P&L% are honest and current, and a holding whose quote can't be fetched shows `null` rather than a fabricated price. The frontend Portfolio panel shows the live summary (total value, total P&L, P&L%) and per-position rows.

**CSV export:** the Forecast Output panel now has one-click ⬇ buttons to download the forecast and the historical rows as CSV, generated client-side (no backend round-trip).

**Frontend additions:** a News & Sentiment panel (per-headline sentiment chips + aggregate badge), a Portfolio Tracker panel (add/remove positions, live P&L), and the CSV export buttons. Verified with `npx tsc --noEmit` and a full `npm run build` (succeeds).

**Testing:** **170 automated backend tests now** (up from 131) — new dedicated files for `news` (scoring, aggregate, both yfinance formats, manager cache/fallback, route), `notifications` (both channels + failure isolation, all network mocked), `portfolio` (P&L math, repository CRUD, routes with the provider seam mocked), and `jobs` (alert check/notify, prediction resolution, rate-limiter cleanup). And this time the new endpoints were also verified against **real live data** (yfinance news + quotes) on a running server — the news feed returned real headlines with real sentiment, and the portfolio returned live P&L.


## What's New — Macro, Events, Fundamentals, Regime, Crypto Pro, Screener + multi-page frontend (this update)

This pass completed six analytical modules that had been left out of earlier rounds, plus the frontend to drive all of them. Every module follows the project's ground rules: real computation on real fetched data, per-item honest degradation, selectable data sources where two exist, and explicit "not investment advice" labeling in both the API and the UI.

**Backend (`backend/app/`, each with a dedicated test file):**

- **`macro.py` — Macro intelligence dashboard (`GET /api/macro`).** Two SELECTABLE sources, never auto-substituted: `yfinance` (market proxies — ^IRX/^TNX/^FVX/^TYX, DX-Y.NYB, GC=F, CL=F, ^VIX, ^GSPC; zero setup) and `fred` (official CPI, Fed Funds, unemployment, GDP, yield spread; needs a free `FRED_API_KEY`). Includes a yield-curve inversion watch classifier, a deterministic 3-factor macro tone (growth/inflation/policy → risk-on/mixed/risk-off), an economic-calendar reference view, and per-indicator failure reporting. Expected/surprise calendar columns stay `null` unless a real consensus feed fills them — never invented.
- **`events.py` — Event impact analytics (`POST /api/stocks/{ticker}/events/study`, `GET /api/market-stress`).** A historical event study that measures what an asset ACTUALLY did +1d/+5d/+20d after real past dates (sample size reported honestly — "anecdotal" under 5 events), and a 0–100 geopolitical/market stress gauge built from real headline keyword volume + lexicon sentiment. Both are explicitly risk indicators and historical statistics, never predictions of political outcomes.
- **`fundamentals.py` — Company deep-dive (`GET /api/stocks/{ticker}/fundamentals`).** Valuation ratios (P/E, P/B, P/S, PEG), profitability with a letter-style grade, balance-sheet health (net cash, leverage bucket), dividends, analyst targets with implied upside, and 52-week/1m/3m price context. Every field the provider doesn't return is `null`, never 0 — a missing EPS cannot become a fake P/E.
- **`regime.py` — Market regime detection (`GET /api/stocks/{ticker}/regime`).** Rule-based classification (trending up/down, range-bound, high-volatility chop) from ADX/DI, price-vs-SMA30, RSI, and a 30-day volatility percentile — with every threshold and reason visible in the response. Optional Gaussian HMM (via `hmmlearn`, an optional dependency) adds a proper statistical regime-switch model when installed; the deterministic classifier is the always-available baseline.
- **`crypto_pro.py` — Crypto pro dashboard (`POST /api/crypto/overview`).** Selectable sources: `coingecko` (market cap, rank, supply, ATH, 24h/7d/30d changes; no key needed) or `yfinance` (same provider layer as everything else). Same normalized row shape from both, so the frontend switches with one dropdown.
- **`screener.py` — Analytical ranking engine (`POST /api/screener`).** Real computed factors (1m/3m momentum, trend score, RSI, annualized volatility) min-max normalized across the scanned set into a transparent composite (momentum 40% / trend 30% / inverse-vol 30%). Failing tickers appear in `unavailable` with the reason — never silently dropped, never given fake scores. Ranked table explicitly labeled analytical, not advisory.
- **`config.py`** gained `FRED_API_KEY`, `MACRO_DEFAULT_SOURCE`, `CRYPTO_DEFAULT_SOURCE`, and `SCREENER_DEFAULT_TICKERS` (all optional — the app runs with none set).

**Frontend — the dashboard is now a multi-page app:**

- `App.tsx` is a react-router v7 router; the old single-page dashboard moved to `pages/CommandCenter.tsx` unchanged, wrapped in a new sidebar shell (`components/Layout.tsx`) with a `/`-redirect for unknown paths.
- Six new pages under `src/pages/`: **Macro** (source selector, tone/yield-curve cards, indicator + calendar tables, honest failure list), **Events & Stress** (stress gauge with keyword chips, event-study form with one-click historical example dates), **Company** (fundamentals: valuation/balance-sheet/analyst/price-context panels), **Screener** (composite-ranked table with score bars + methodology note), **Crypto** (source selector, dominance/best-worst cards, coins table), **Regime Analytics** (regime card, explainable reasoning list, optional HMM state table).
- `src/lib/api.tsx` is the shared fetch layer (`getJSON`/`postJSON` with real error messages, `Pct`/`Money`/`Num`/`MetaBadge`/`StatCard` primitives) so every page degrades the same honest way when a source is unavailable.
- Verified with `npx tsc --noEmit` and a full `npm run build` (76 modules, succeeds).

**Testing:** 231 automated backend tests (up from 170) — the six new modules each have a dedicated test file, all against synthetic/mocked data, plus route tests through the FastAPI app. One environment note: `pytest-asyncio` must be installed for the async test suite (`pip install pytest-asyncio`); without it every async test fails with "async def functions are not natively supported", which looks like 29 unrelated failures but is purely the missing plugin.## What's New — PSX live data, completed pages & error cleanup (this update)

This pass ran the whole app end-to-end (backend + frontend), found the internal
errors that were breaking features silently, and fixed them. Nothing was removed.

**The root-cause bug — every PSX ticker feature was failing live.** Yahoo Finance
lists Pakistan Stock Exchange companies with a `.KA` suffix; the bare symbol
(`OGDC`, `KEL`, `MEBL`, …) returns *no data at all*. So the PSX terminal's global
search, watchlist, announcement "View Stock", alerts, portfolio and the stock
dashboard all resolved to an empty payload — while US tickers worked, which made it
look like only "some features" were broken. Fixed in a new
`backend/app/symbols.py` used by the yfinance provider: a known PSX symbol maps
straight to `<TICKER>.KA`, anything else is tried bare first and then with `.KA`
(so `AAPL` still works and unlisted PSX symbols still resolve). Verified live:
`OGDC` (545 rows), `KEL`, `MEBL` ("Meezan Bank Limited", PKR), `SYS` news,
screener + cross-asset + predict + fundamentals + regime — all now return real data.

**Completed pages that were "coming soon" stubs:**
- `NewsPage` — live headlines + lexicon sentiment for a selectable PSX ticker or the broader market (`^GSPC`), via the existing `/api/stocks/{t}/news`.
- `AnnouncementPage` (`/announcements/:id`) — real permalink detail, backed by a new `GET /api/psx/announcements/{id}` route that searches the live feed, then the labelled demo set, and 404s honestly when an id has rolled off. Announcement cards now link to it.

**Other fixes:**
- `GlobalSearch` searched a hardcoded mock list; it now autocompletes the real PSX universe (stocks + indices + sectors from `lib/psxMarket.ts`) and routes correctly — and no longer displays invented percentage changes.
- `HomePage` quick-tickers were US names in a PSX terminal → now PSX blue chips.
- `EVENT_META.BOARD_CHANGE` had the literal string `"chair"` as its icon → fixed to ⚑.
- Cross-asset defaults now start from PSX tickers (`OGDC, LUCK, HBL, MEBL`).
- Removed two accidental zero-byte artifacts (`backend/=24.1.0`, `backend/=8.5.0`).

**Verified:** 258 backend tests pass (up from 241 — new `test_symbols.py` plus
announcement-permalink route tests), `npx tsc --noEmit` clean, `npm run build`
succeeds, and a live smoke run of every PSX feature returned `200` with zero
unavailable tickers and no server-side tracebacks.

PSX-specific to-do checklist (all 9 items now done):
- [x] Inspect existing project structure and framework
- [x] Create PSX-specific header with navigation
- [x] Implement global search UI with autocomplete (real universe)
- [x] Add responsive navigation with mobile menu
- [x] Implement theme system (dark/light mode)
- [x] Create base UI components (buttons, cards, badges, etc.)
- [x] Enhance routing with PSX-specific routes
- [x] Add loading skeleton and empty state components
- [x] Test responsiveness and theme switching

**Known limitation (honest, not hidden):** PSX *index* levels (KSE-100 etc.) are
not available on Yahoo Finance, so the Market/Index pages still use clearly-labelled
mock data. Individual PSX **stocks** are live. Swapping in the official PSX Data
Portal API is the documented next step for real index data.

## Phase 4 — PSX Announcements, Filings & AI Intelligence

A complete Smart Company Announcements system, kept strictly separate from the
rest of the market features (nothing else was touched).

**Live feed.** `backend/app/announcements.py` fetches real PSX company
announcements from the public ksestocks.com mirror (server-rendered HTML of the
official feed — no API key), parses the `<table id="ans">` rows, and runs
deterministic rule-based analysis on the real filing text. `source_status` is
`LIVE` when the mirror answered, `STALE` when served from last-good cache, and
`UNAVAILABLE` when it didn't — **no filing is ever fabricated to fill a gap.**
`GET /api/psx/announcements` serves the feed; `GET /api/psx/announcements/{id}`
serves a single permalink record (live first, then demo, honest 404 otherwise).

**All 17 event categories:** Rights Issue, Bonus Shares, Dividend, AGM, EGM,
Insider Sale, Insider Purchase, Management Change, Board Change, Financial
Results, Profit Warning, Acquisition, Merger, Contract Award, Corporate Action,
Regulatory Notice, Other.

**Sentiment:** POSITIVE / NEGATIVE / MIXED / NEUTRAL — each rendered as
**icon + text + accessible label** (`role="img"` + `aria-label`), never color alone.

**AI summary block:** every card shows an `AI SUMMARY` chip, the analysis engine
(`rule-based-v1`), extracted highlights (facts/dates/actions/figures drawn only
from the source text), the structured fields, and an explicit “AI-generated
analysis — not an official PSX statement” disclaimer. AI content and source
content are visually separated — the original filing text sits in its own
collapsible block labelled as source, not AI.

**Structured event extraction:** Event, Person, Action, Shares, Price, Total
Value, Effective Date (plus EPS, Dividend, Bonus, Rights and book-closure dates).
Only fields literally present in the source are emitted — a missing field stays
`null` and is simply not rendered; nothing is inferred into existence.

**Card contents:** company, ticker, published date + honest relative time, event
badge, sentiment badge, AI summary, structured data, original PDF, original
image, source link, permalink, **View Stock →** and **Company Fundamentals →**.

**Filtering:** event type, sentiment, company (case-insensitive partial match),
date range, and stock ticker. **Search:** company, ticker, title, event and body.
**Pagination:** 7-slot pager window with server-side clamping, built to scale to
large feeds; every filter/view is deep-linkable via URL query params.

**Demo dataset:** `source=simulated` serves clearly-labelled `DEMO` records across
all categories (real PSX tickers, synthetic bodies) for interface development —
never a claim about a real company.

**Data architecture (API separate from UI):** `lib/announcements.ts` exposes
`AnnouncementService` (typed fetch funnel), `AIAnalysisService` (event/sentiment
presentation metadata + `structuredRows`), `AnnouncementTypes`, and
`AnnouncementFilters` — mirroring the backend contract 1:1 so the official PSX
Data Portal can be swapped in without touching the UI.

**Completed in this pass** (spec gaps): added the Company filter to the UI +
case-insensitive partial matching, added the EVENT row to structured extraction,
added honest relative dates, added the Company Fundamentals deep-link, and made
`/company` accept `?ticker=` so announcement cards can deep-link into it.

## Phase 5 — Final Integration, Detail Pages & Production Polish

The whole app is now one integrated PSX financial terminal. Nothing was removed.

**Stock detail page (`/stock/:symbol`).** A new `GET /api/stocks/{ticker}/snapshot`
gives the page one consolidated payload (name, sector/industry/country/exchange,
price, absolute + percent change, open, day high/low, previous close, volume,
traded value, 52-week high/low). The page renders a snapshot header with a
**LIVE / RECENT / CACHED / STALE / UNAVAILABLE** freshness chip, a PSX session
badge, and a Shariah badge (only for known PSX symbols — never invented for US
tickers). An interactive chart has **1D / 7D / 1M / 6M / 1Y / 3Y / 5Y** timeframes
(intraday bars for the short ranges, daily beyond), deep-linkable via `?range=1Y`,
with SMA/EMA/Bollinger overlays and the AI forecast band on daily ranges. Every
existing panel (prediction engine, drift, indicators, cross-asset, forecast
table, backtest, briefing, alerts, watchlist) is preserved, plus live news.

**Index detail page (`/index/:symbol`).** Rebuilt from a stub into a full page:
value, change, percent change, interactive chart with all seven timeframes,
open/high/low/previous close/volume/traded value, day range and 52-week range —
reusing the existing market components. Clearly labelled **DEMO** because PSX
index levels are not on the free provider.

**Watchlist foundation.** `GET /api/watchlist/quotes` prices every saved ticker
fresh at read time; the panel shows current price and % change for each saved
stock with add/remove and persistence. A ticker the provider can't price shows
“no quote” — never a fabricated number.

**Portfolio foundation.** Existing holdings / quantity / average price / current
price / market value / P&L UI is unchanged and server-backed (already better than
the mock data the brief suggested).

**Data architecture — one direction, no shortcuts:**

```
UI (pages/components)  ->  hooks (React Query)  ->  services  ->  API/data layer
```

- `lib/services.ts` — typed endpoints (`MarketService`), the only place URLs live.
- `hooks/useMarketQueries.ts` — `useStockSnapshot`, `useStockHistory`, `useWatchlist`
  with caching, de-duplication, retries and cache invalidation.
- `lib/timeframes.ts` — one definition of each chart range.
- `lib/axios.ts` + `lib/react-query.ts` are now genuinely used (previously set up
  but unused), and its interceptors normalize network/timeout/HTTP errors into
  human-readable messages surfaced consistently in the UI.

**Performance.** Route-level code splitting (`React.lazy`) with a Suspense
boundary **inside** the shell, so the terminal chrome never unmounts while a page
chunk loads. The initial JS bundle dropped from **5,126 kB to 250 kB** and Plotly
is isolated into its own on-demand chunk. Chart traces are `useMemo`-ized,
`AnnouncementCard` is `React.memo`-ized, and search/filters are debounced.

**Accessibility.** Semantic landmarks, `role="tablist"`/`aria-selected` on
range and chart controls, `role="status"`/`role="alert"` on async states,
`scope="col"` table headers, `.sr-only` labels for icon-only actions, focus
rings on new controls, and gain/loss shown with **sign + arrow + text**, never
colour alone.

**Error handling.** Every new async surface has loading (skeleton), error
(message + Retry) and empty states; invalid symbols, unavailable providers and
empty datasets each render a specific, honest message instead of a blank panel.

**Mobile.** Snapshot header stacks, the stat strip becomes 2-up, tables scroll
horizontally, charts resize (`useResizeHandler`), and the mobile nav is unchanged.

**Engineering audit.** `npx tsc --noEmit` clean, `npm run build` succeeds,
`pytest` green, no broken routes/imports, no duplicate logic added, and no
console errors in the app code (axios logging is DEV-only).

### Final structure (new/changed in Phase 5)

```text
backend/app/
  main.py                       + /snapshot, + /watchlist/quotes
  symbols.py                    PSX .KA resolution (Phase 4 pass)
frontend/src/
  App.tsx                       route-level code splitting
  Layout.tsx                    Suspense boundary around <Outlet/>
  lib/services.ts               NEW  typed service layer
  lib/timeframes.ts             NEW  chart range definitions
  lib/psxMarket.ts              + getStockMeta / sectorLabel
  hooks/useMarketQueries.ts     NEW  React Query hooks
  components/ShariahBadge.tsx   NEW
  components/RouteFallback.tsx  NEW
  components/Watchlist.tsx      live price + % change
  pages/StockDashboard.tsx      snapshot header, timeframes, stats, news
  pages/IndexPage.tsx           full index detail page
```

### Run it

```bash
# backend
cd stock_ai_extreme/backend
python -m venv .venv && .venv/Scripts/activate        # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000

# frontend (separate terminal)
cd stock_ai_extreme/frontend
npm install
npm run dev            # http://localhost:5173
```

### Build the production version

```bash
cd stock_ai_extreme/frontend
npm run build          # emits frontend/dist (static)
npm run preview        # local preview of the built bundle

# backend (production server)
cd stock_ai_extreme/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

## Phase 7 — Advanced Forex & Commodities Market Data Center

A new cross-market page (`/forex-commodities`, in the main nav) covering the eight required
currencies and the four required metal purities. Nothing was removed and no earlier phase
changed behaviour.

**Real sources, no keys required.** Two genuine feeds sit behind one small provider module
(`backend/app/providers/fx_rates.py`):

| Source | What it provides | Cost |
|---|---|---|
| Yahoo Finance (via `yfinance`) | live FX **bid/ask** for all eight PKR crosses (`USDPKR=X`, `GBPPKR=X`, …) and the COMEX front-month metals (`GC=F`, `SI=F`, `PL=F`) | free, no key |
| ExchangeRate-API open endpoint | 166 currencies incl. PKR/AED/SAR, published **once a day** — used only as a labelled fallback | free, no key |

**Forex module (`backend/app/forex.py`, `ForexQuote`).** Each pair is quoted as `<CURRENCY>/PKR` with
`bid`, `ask`, `mid = (bid+ask)/2`, `spread`, `spread %`, `change`, `change %`, the source's own
timestamp, `source` and a `data_mode`. Validation matters more than it sounds: Yahoo really does
return bid/ask **inverted** (bid > ask) for USD-quoted majors such as `EURUSD=X`. Those levels are
**rejected outright** with the reason attached (`bid_ask_note`) instead of being shown as a negative
spread, and `mid` falls back to the source's own traded price. Missing, zero, negative, `NaN` and
`Infinity` sides are dropped individually; `bid`/`ask` stay `null` and the UI renders `—`.

**Commodities module (`backend/app/commodities_pk.py`, `CommodityQuote`).** Gold 24K, Gold 22K, Silver
and Platinum in PKR. No free, keyless API publishes the Karachi Sarafa Association board, so this is
a **derivation from real inputs**, never a pretend feed:

```
price(PKR per unit) = (USD per troy ounce ÷ 31.1034768) × USD/PKR × grams_per_unit × purity_ratio
22K gold = 24K × 22/24          tola = 11.6638125 g          10-gram and tola are separate rows
```

Every row carries an explicit unit (`PKR per gram`, `PKR per 10 gram`, `PKR per tola`) — per-gram and
per-tola values are separate rows, never silently mixed. The response also returns the inputs it used
(contract, USD/troy-oz, previous close, bid/ask, the USD/PKR leg with its source and timestamp) and
states plainly that this is **not** the local retail board: retail adds dealer premiums, making
charges and taxes, so shops are usually higher.

**Freshness (spec O) and data modes (spec G).** `get_data_freshness()` returns FRESH/AGING/STALE/UNKNOWN
against **configurable** thresholds (`FX_LIVE_THRESHOLD_SECONDS`, `FX_AGING_THRESHOLD_SECONDS`,
`FX_STALE_THRESHOLD_SECONDS`), and `data_mode` is LIVE/DELAYED/DEMO/UNAVAILABLE. Two honesty rules are
enforced in code: a source that publishes **daily can never be LIVE**, and a quote older than the
stale window becomes **UNAVAILABLE** rather than being presented as a current rate. In practice the PKR
crosses carry a timestamp from that morning's interbank open, so they correctly render **Delayed ·
Aging** while the metals futures show **Live · Fresh** — the page reports what each feed actually is.

**Frontend.** `lib/forexCommodities.ts` holds the types, validation, the freshness utility and the only
place endpoint strings live (`ForexService` / `CommodityService`, with `getForexQuotes`,
`getForexQuote`, `getCommodityQuotes`, `getCommodityQuote`, `refreshMarketRates`). The page itself adds:
debounced search (USD / US Dollar / USD-PKR all match), sorting on **raw numeric values** with nulls
sinking to the bottom, a manual Refresh plus an opt-in 60 s auto-refresh that is always torn down, a
market-state/data-source pill per row that is visible at every breakpoint, metal cards with purity,
unit-explicit prices, a 30-session sparkline built from real daily closes × the matching day's
USD/PKR, and an expandable derivation panel. Forex and commodities are **independent sections**:
an outage in one cannot blank out the other. Movement is always sign + arrow icon + the word up/down,
never colour alone.

**A project-wide mobile fix came out of this phase.** `frontend/index.html` had no doctype, `<head>` or
viewport meta tag, so a real phone fell back to a ~980 px layout viewport and zoomed the whole terminal
out — which also meant no `max-width` media query ever matched on mobile. Added
`<meta name="viewport" content="width=device-width, initial-scale=1">` (plus charset, title,
description). Verified by emulation: at 390 px the viewport is now 390 px, the card grid collapses to
a single column, and the forex grid scrolls inside its own container with a sticky currency column
instead of pushing the page sideways.

**Testing.** 60 new backend tests (`tests/test_forex.py`, `tests/test_commodities_pk.py`) — all network
mocked at the provider seam — covering a valid quote, missing bid, missing ask, zero/negative/NaN
sides, inverted bid/ask, positive and negative change, stale and undated timestamps, invalid currency
codes, an unknown unit, a daily source never being LIVE, a total outage yielding UNAVAILABLE instead of
a number, and the tola/10-gram/22K conversions. Full suite: **324 passing**.

**Honest limitations, stated rather than hidden:** Yahoo publishes no spot metal symbol (`XAUUSD=X`
returns nothing), so the international leg is the COMEX front-month futures contract and is labelled as
such. PKR crosses are illiquid and their timestamps can be hours old, which the freshness states report
rather than paper over. Swapping in a licensed feed (or the official PSX Data Portal) means writing one
provider and pointing the module at it.

## Phase 8 addendum — the News Desk actually works now (this pass)

The previous pass shipped Phase 8's *files*, and its own summary said it was
"100% complete". It was not: **the backend did not import at all**, so no news
feature had ever run. This pass fixed that and then built the newsroom out
properly. Nothing was removed — every prior phase is untouched.

**The blockers, found and fixed (these were real, not style nits):**

| # | What was broken | Why it mattered |
|---|---|---|
| 1 | `news_service.py` did `from .db import get_db` — a function that has never existed | `main.py` imports this module at startup, so **the entire FastAPI app failed with `ImportError`**. Nothing in the project could run. |
| 2 | `main.py` used `NewsArticle`, `func`, `desc`, `or_`, `and_` without importing any of them | Every one of the 8 news routes raised `NameError` → HTTP 500. `GET /api/news/categories` could never have returned 200. |
| 3 | `aggregate_and_store` used `next(get_db())` with no such symbol | The refresh route was dead even after fixing the import. Now uses the existing `session_scope()`. |
| 4 | `test_news_service.py` referenced `client` / `test_db` fixtures that do not exist | 5 tests errored on collection, so **none of the Phase 8 tests had ever executed**. The "tests pass" claim rested on them. |
| 5 | The news desk only read from `NewsArticle`, which starts empty | A fresh install showed an empty newsroom until someone pressed Refresh — and without NewsAPI/Finnhub/Alpha Vantage keys, Refresh stayed empty too. |

**What was added (nothing removed):**

* **`news_sources.py` — keyless real publisher feeds.** 15 enabled RSS/Atom
  feeds that need no key and no account: Dawn Business, The Express Tribune
  Business, Google News queries scoped to PSX / KSE-100 / SBP / SECP / the
  rupee / gold and the Pakistan economy, plus BBC Business, CNBC Markets, WSJ
  Markets, Yahoo Finance and Investing.com. A hardened parser (DTD/entity
  declarations rejected, response size capped, RSS 2.0 **and** Atom, two-digit
  RFC-822 years, namespace-insensitive tags, media/enclosure/`<img>` image
  extraction, Google News publisher attribution, placeholder-address bylines
  cleaned) with **honest per-feed status**: `OK` / `EMPTY` / `ERROR` +
  HTTP code + reason, or `DISABLED` with the reason kept. Business Recorder is
  retained and reported as `DISABLED` (it answers this server with 403) rather
  than deleted — a real coverage gap should be visible, not hidden.
  Verified live: **~960–1,200 articles per ingest from 15/15 feeds.**
* **`news_analytics.py` — the analysis engine, all pure stdlib.**
  * **MinHash + LSH near-duplicate detection** (24-row signatures, 6 bands of 4)
    and 64-bit **SimHash**. SimHash alone is *not* sufficient here and the module
    measures why: on a 40-shingle article a one-word edit moves the SimHash
    fingerprint ~11 bits — indistinguishable from an unrelated story at ~26–39
    bits — while the MinHash Jaccard estimate stays above 0.5 and identical text
    scores 1.0. Ingestion therefore gates on the signature. Real effect:
    ~33 near-duplicates caught per ingest that URL-only de-duplication missed.
  * **BM25 Okapi ranking** (k1=1.2, b=0.75) with headline field-boosting and
    conservative fuzzy term expansion via the indexed vocabulary.
  * **TF-IDF keyword extraction** with IDF computed over the live corpus.
  * **Entity linking validated against the real PSX universe** — a bare token is
    only accepted if it is in `symbols.PSX_SYMBOLS`, so the feed never produces
    a ticker link for a company the terminal cannot price (spec H). Company
    names resolve through an alias table that a test asserts maps only to real
    symbols.
  * **Event classification** (dividend, earnings, M&A, rights, regulatory,
    monetary policy, macro data, insider, contract, rating, legal, management,
    market update) and a **transparent 0–100 impact score** whose five weighted
    components are returned with the total, so the ranking is inspectable.
  * **Story clustering** — agglomerative TF-IDF cosine grouping, threshold 0.3
    chosen against a live corpus (0.22 merged unrelated syndicated round-ups;
    0.45 split genuinely-same stories).
  * **Time-decayed trending** — `0.5 ** (age / half-life)` mentions, so six
    mentions this morning outrank forty from last week.
* **`models.py` + `db.py`** — new `news_articles` columns (`data_mode`,
  `event_type`, `impact_score`, `keywords`, `entities`, `topics`, `simhash`,
  `shingle_signature`, `word_count`, `reading_time_minutes`, `feed_key`) plus an
  **append-only `ALTER TABLE ADD COLUMN` migration** in `init_db()`, because
  `create_all()` never alters an existing table and the pre-existing
  `neural_market.db` would otherwise fail on the first query. Conservative by
  design: it never drops, renames or retypes, and skips a non-nullable column it
  cannot supply a scalar default for rather than inventing values.
* **`news_service.py`** — RSS + symbol-scoped ingestion, the enrichment
  pipeline, the duplicate report (stored / duplicate_url / duplicate_title /
  near_duplicate / failed), real de-duplication, and **every HTTP call moved off
  the event loop** via `asyncio.to_thread` (the previous version did blocking
  `httpx` inside `async def`, stalling the API on any slow publisher).
* **`jobs.py`** — automatic ingestion on the existing background loop, throttled
  by `NEWS_REFRESH_INTERVAL_SECONDS` (30 min), so the desk fills itself instead
  of waiting for a button. A failed ingest deliberately does **not** consume the
  interval, so the next tick retries.
* **`main.py` routes** — relevance-ranked `POST /api/news/search` (sort by
  `recent` / `impact` / `relevance`, plus `event_type`, `priority`, `min_impact`
  and a `date_to` that includes the whole day), hero chosen by impact score with
  a stated empty reason, `by-symbol` with a **live publisher fallback**, and four
  new endpoints: `GET /api/news/trending`, `POST /api/news/clusters`,
  `GET /api/news/{id}/related`, `GET /api/news/stats`, `GET /api/news/sources`.
  Search also matches hyphen/space-insensitive forms, so `kse100` finds `KSE-100`
  and `s&p500` finds `S&P 500`, and falls back to fuzzy BM25 ranking when a
  literal substring match finds nothing (`dividnd` → 13 real results).
* **`GET /api/news/image`** — an **allow-listed** image proxy used only as a
  retry after a direct browser load fails (some CDNs 403 a cross-origin `<img>`
  but serve a server request). https only, hostname must match a fixed list, no
  credentials and no custom port, image content-type required, body size-capped,
  cached. A non-allow-listed URL is refused *before* any request is made —
  verified: `evil.example.com` and `http://127.0.0.1:8000/...` both return 400
  with no outbound call.

**Frontend:** `SafeImage` (lazy loading, reserved aspect-ratio box, a
one-shot proxy retry, and a session memo so a host that has already refused both
paths is not re-attempted on every render), shared news metadata components, a
`TrendingStrip`, `StoryClusters` (with the terms that define each group, so the
grouping is inspectable), a `NewsSourceHealth` panel showing the real HTTP
result per feed, sort controls, a refresh result line, and **`RelatedNews` wired
into the stock detail page** (spec I) — it existed before but was never imported
anywhere. Ticker links are validated against the terminal's own universe and
render as inert text when unknown, and every freshness/sentiment state carries a
word or symbol as well as a colour.

**Testing:** **519 backend tests** (up from 328 passing + 5 erroring) — new
`test_news_analytics.py` (72 tests over MinHash/SimHash/BM25/TF-IDF/entities/
impact/clustering/trending), `test_news_sources.py` (42 tests over RSS + Atom
parsing, date formats, unsafe-XML rejection, author cleanup and every
`OK`/`EMPTY`/`ERROR`/`DISABLED` path with a stubbed client) and
`test_news_image_proxy.py` (34 tests over the SSRF guard, content-type and size
limits, route status mapping, and the throttled background job). The previously
non-running `test_news_service.py` was repaired **and extended** (30 tests, incl.
de-duplication and freshness windows). Frontend: `npx tsc --noEmit` clean,
`npm run build` succeeds.

**Verification actually performed (not asserted):** a live backend and frontend
on localhost, ingesting from real feeds and rendering the page in headless
Chrome. Confirmed against real data: the hero carried a real Dawn headline with
its image, excerpt and keywords; trending listed real entities (`monetary-policy`
×23, `PPL` ×17, `inflation` ×15, `KSE100` ×8, `SYS` ×6); story clusters grouped
the SBP policy-rate decision across 8 outlets; source health reported 15/15 live
with per-feed HTTP 200 and item counts; `/api/news/by-symbol/OGDC` returned real
OGDC coverage; and `/stock/OGDC` rendered its related-news block (the page-audit
harness reports that route `ok`).

**Known limitations, stated rather than hidden:**

* A handful of publisher CDNs (notably `content-media.investing.com`) refuse the
  image request from *both* the browser and this server, so those thumbnails fall
  back to a labelled placeholder. The console still records the browser's 403
  because it is the browser making that request — the app cannot suppress it
  without proxying *every* image, which is not worth the bandwidth. About 7% of
  current articles are affected; the layout and the article link are unaffected.
  (The `page-audit.mjs` harness flags any failed request, including third-party
  ones, so `/news` reports a failure for exactly this reason.)
* Business Recorder, SBP and SECP answer this server with HTTP 403. Their content
  is still covered through the Google News queries against their own published
  headlines, and the feeds themselves are reported as `DISABLED` with the reason.
* RSS items are headline + lede only. Deeper full-text extraction was not added:
  it is a scraping problem with per-publisher rules, and the honest choice was
  not to ship it half-done.
* Index-level PSX data (KSE-100 etc.) remains the previously documented demo
  dataset — that limitation is unchanged by this pass.

### Run the Phase 8 addendum

```bash
# backend (feeds need no keys — the desk is non-empty out of the box)
cd stock_ai_extreme/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# first ingest happens on its own (30 min); trigger it immediately with:
curl -X POST http://127.0.0.1:8000/api/news/refresh

# frontend
cd ../frontend && npm install && npm run dev   # http://localhost:5173/news
```

Useful checks while it runs:

```bash
curl -s http://127.0.0.1:8000/api/news/sources   # real per-feed health
curl -s http://127.0.0.1:8000/api/news/stats     # corpus statistics
curl -s "http://127.0.0.1:8000/api/news/trending?window_hours=72"
curl -s -X POST http://127.0.0.1:8000/api/news/clusters -H 'content-type: application/json' -d '{}'
curl -s "http://127.0.0.1:8000/api/news/by-symbol/OGDC?limit=5"
```

New configuration (all optional, see `backend/.env.example`):
`NEWS_RSS_ENABLED`, `NEWS_DEFAULT_REGION`, `NEWS_FETCH_CONCURRENCY`,
`NEWS_REFRESH_INTERVAL_SECONDS`, `NEWS_SYMBOL_WATCHLIST`, `NEWS_SYMBOL_MAX`,
`NEWS_DEDUPE_SCAN_LIMIT`, `NEWS_MINHASH_ROWS`, `NEWS_MINHASH_BAND_ROWS`,
`NEWS_DEDUPE_JACCARD_THRESHOLD`, `NEWS_SIMHASH_BANDS`,
`NEWS_SIMHASH_HAMMING_THRESHOLD`, `NEWS_SEARCH_TITLE_BOOST`, `NEWS_SEARCH_FUZZY`.

## Phase 10 — Context-Aware AI Financial Assistant

The assistant is a real chat surface, not a log console:

* **Desktop** — a docked right rail (the page takes a gutter so nothing hides
  behind it); **mobile** — a full-screen sheet with a keyboard-safe composer.
* **Context chips** above the thread show what the assistant can see
  (page, symbol/index, timeframe, session window, data families), and
  "What is sent" spells out exactly what will be attached to the next question.
* **Answers** render structured markdown, label every statement as
  FACT / CALCULATION / INTERPRETATION / ESTIMATE / USER-SUPPLIED, list the
  sources they used, and offer Copy and Retry.
* **Streaming** with a Stop button that keeps the partial answer; errors always
  resolve into a card with an action — never an endless spinner.
* **Conversations** are stored server-side with search, rename, delete and
  day grouping; agent task history is recorded separately.
* **Voice input** uses the browser's speech recognition and states plainly when
  the browser does not support it.

```bash
# backend: choose a provider and set its key
cd stock_ai_extreme/backend
#   AI_PROVIDER=openai        OPENAI_API_KEY=...
#   AI_PROVIDER=openrouter    OPENROUTER_API_KEY=...
#   AI_PROVIDER=anthropic     ANTHROPIC_API_KEY=...
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd ../frontend && npm install && npm run dev   # look for “Ask the assistant”
```

With no key set the assistant reports “not configured” and explains how to fix
it; every other page keeps working. If the API itself is down the panel says so
instead — a stopped backend is not blamed on a missing key.

```bash
# audit the assistant in a real browser (backend + dev server must be running,
# Chrome launched with --remote-debugging-port=9222) — 63 checks, screenshots
cd stock_ai_extreme/frontend && node scripts/assistant-audit.mjs
```

Full architecture, endpoints, context model and test results:
[`PHASE_10_AI_ASSISTANT.md`](PHASE_10_AI_ASSISTANT.md).

---

## Phase 11 — Professional Charting & Technical Analysis Engine

The existing chart is now a **multi-panel technical-analysis workspace** at
`/charts`. Nothing from Phases 1–10 was removed, and no new charting library was
introduced — it is built on the `plotly.js` / `react-plotly.js` pair and the
project's existing `zustand` + `persist` store, React Query layer, timeframe
system and market-data services.

**Workspace.** Two independent panels — **Chart A** and **Chart B** — that can be
viewed one at a time or stacked (single / split). Each panel owns its symbol,
timeframe, chart style, indicators, drawings, price levels, viewport and display
settings, so changing one never disturbs the other. On mobile the workspace shows
exactly one panel with an explicit A/B switcher, and the drawing tools stay
usable with touch input.

**Chart styles.** Candlestick, volume candlesticks and line. Switching style
preserves the symbol, timeframe, viewport, indicators, drawings and price levels.

**Data.** Every candle passes through one normalizer that rejects malformed rows,
collapses duplicate timestamps, re-sorts out-of-order bars, repairs incoherent
OHLC relationships and records a missing volume as *missing* rather than zero —
starting from real provider data (the market-history API for stocks, the PSX
index series for indices). The panel states its source, its freshness and whether
the normalizer had to clean anything; nothing is fabricated to fill a gap.

**Indicators.** SMA 20, SMA 50, EMA 20 (configurable period), VWAP and Bollinger
Bands 20/2 (configurable multiplier). SMA 20 and SMA 50 start on; the rest start
off. Calculations are pure, memoized, and never run inside a render. Indicators
that a dataset cannot support say so — on daily bars VWAP reports
“VWAP unavailable for this dataset” instead of inventing a number. The legend and
the crosshair readout show live values at the hovered bar, and insufficient
history is labelled rather than drawn.

**Charting tools.** Five drawing primitives — trend line, rectangle, circle,
parabola, semicircle — plus five price-level types: support, resistance, entry,
stop loss and target. Everything is stored in **data space** (time + price), never
as screen pixels, so a drawing or a level stays exactly where it belongs through
zoom, resize, timeframe changes and viewport moves. Drawings can be created,
moved, reshaped, hidden, locked, deleted or cleared, with per-chart undo/redo
(60 steps). A professional crosshair readout reports date/time, OHLCV and the
active indicators, and any chart can go fullscreen with its state intact.

**Persistence.** Layout, active panel, per-chart configuration, indicators,
drawings, price levels and the saved zoom window survive a reload through the
project's existing persistence architecture. A stored zoom is only re-applied
when it still matches the exact dataset it was captured for.

**Verification** (both harnesses are committed):

```bash
cd stock_ai_extreme/frontend
node scripts/chart-engine-test.mjs     # 178 pure-engine assertions, no browser
npx tsc --noEmit && npm run build      # typecheck + production build

# audit the workspace in a real browser (dev server on :5173, Chrome launched
# with --remote-debugging-port=9222) — 95 checks, real input events, screenshots
node scripts/chart-audit.mjs
```

Two real defects were found and fixed while verifying: a Plotly `purge` /
React-cleanup ordering race that threw from a passive unmount and blanked the
whole workspace whenever a panel was unmounted (split → single, switching to
mobile), and the footer's “Charts” link, which never navigated because it used a
hash href under a `BrowserRouter`.

Full architecture, data models, maths, bug analysis and test results:
[`PHASE_11_COMPLETE.md`](PHASE_11_COMPLETE.md).
