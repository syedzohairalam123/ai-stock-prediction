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

