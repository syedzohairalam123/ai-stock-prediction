# NEURAL MARKET — Master Build Prompt
### (Paste this to your coding AI — e.g. Claude Code — to drive the build, phase by phase)

---

## HOW TO ACTUALLY USE THIS DOCUMENT

1. Paste this **whole file** once, at the start of a fresh session with your coding AI, as project context.
2. Then work **one phase at a time** — e.g. *"Do Phase 1 only. Show me the diff before touching anything else."* Never ask it to "do everything" in one message — that's how you get broken, half-finished code across 40 files.
3. Phase 0 (the audit) is **already done for you below** — your AI doesn't need to re-discover the codebase from scratch, it can start straight at Phase 1.
4. After every phase: run it, click through it yourself, THEN move to the next phase. This is in the rules below too — it's repeated here because it's the single biggest reason "one giant AI prompt" projects fail.

---

## 0. ROLE & GROUND RULES (non-negotiable)

You are acting as a senior full-stack engineer, ML/quant engineer, data engineer, UI/UX designer, and DevOps engineer, working on an **existing** codebase called `stock_ai_extreme` ("Neural Market"). This is an educational financial-analytics platform, not a trading system.

- **Never rewrite what already works.** Extend and refactor incrementally. Section 1 below tells you exactly what already exists — read it before touching anything.
- **No fake data, ever.** No hardcoded prices, no randomly-generated "predictions," no invented confidence scores, no made-up news or social sentiment. If a data source is unavailable, the UI must clearly say "unavailable," never quietly substitute fake numbers.
- **No certainty language.** Never say a market, coin, or index "will" rise/fall. Always frame output as a probabilistic estimate with an uncertainty range and a plain disclaimer.
- **Chronological integrity.** Never shuffle time-series data for training/validation. Always split and validate in time order. Fit scalers only on training data. Watch for any feature that leaks future information into a past row.
- **One phase, fully tested, before the next.** A phase is done only when it actually runs, its new API routes respond correctly, and its new UI renders without errors.
- **Small correct feature > big fake feature.** If a data source or model can't be done honestly with free/legal resources, say so and ship a smaller, real version instead of faking the impressive one.

---

## 1. CURRENT STATE — Phase 0 Audit (already completed)

`stock_ai_extreme` is a small, genuinely working full-stack starter — **not** a blank project. Here's exactly what's already there:

**Backend (FastAPI, Python)** — `backend/app/`
- `main.py` — FastAPI app, CORS, 2 REST routes (`/api/stocks/{ticker}/history`, `/api/stocks/{ticker}/predict`) + 1 WebSocket route (`/ws/stock/{ticker}`) that polls every `LIVE_POLL_SECONDS`.
- `agents.py` — `DataAgent` (async `yfinance` fetch), `PredictionAgent` (Random Forest / Ridge, proper `TimeSeriesSplit` chronological CV, recursive multi-day forecasting), `InsightAgent` (plain-text trend/RSI/volatility/risk commentary + disclaimer).
- `lstm_agent.py` — a real Keras LSTM (2-layer, dropout, early stopping, 80/20 chronological holdout, recursive forecasting).
- `indicators.py` — SMA 10/30, EMA 10/26, RSI 14, MACD+signal, Bollinger Bands, returns.
- `config.py` — env-driven settings (CORS origins, poll interval, model dir).
- Confidence band = `prediction ± 1.96 × validation RMSE` (honestly documented as "not a calibrated probability interval").

**Frontend (React + TypeScript + Vite + Plotly)** — `frontend/src/`
- `App.tsx` — single dashboard: ticker search, model selector (RF / Ridge / LSTM), Plotly chart (history + forecast + shaded interval), metrics panel (risk/MAE/RMSE), insights list, forecast table.
- `useStockWebSocket.ts` — reconnecting WebSocket hook for the live price tick.
- `index.css` — dark theme with glass panels and gradient accents.

**Deployment** — `Dockerfile` + `docker-compose.yml` (backend only), `render.yaml` (Render Blueprint for the API). Frontend is deployed separately (Vercel/Netlify/Render Static).

**What is genuinely missing right now** (confirmed by reading every file, not assumed):
- No database at all — nothing persists. Every prediction re-downloads history and retrains from zero.
- No auth/users, no watchlists, no portfolio, no alerts.
- No caching, no rate-limit handling, no retry/backoff, no circuit breaker, no fallback provider — `yfinance` is a single point of failure.
- No news, sentiment, macro, crypto, forex, or commodities modules — only single-stock price forecasting exists so far.
- No tests anywhere in the repo.
- `frontend/src/App.tsx` and `useStockWebSocket.ts` **hardcode** `http://127.0.0.1:8000` / `ws://127.0.0.1:8000`. This will silently break the moment you deploy — the deployed frontend will keep trying to call your laptop. Fix this in Phase 1 (move to `import.meta.env.VITE_API_URL`).
- `frontend/package.json` pins every dependency to `"latest"` — will eventually break without warning when a library ships a breaking major version. Pin real version numbers in Phase 1.
- Only Random Forest / Ridge / LSTM exist — no GRU, Transformer, ensemble, or probabilistic/conformal intervals yet.
- The current dark theme leans "glassmorphism SaaS landing page" (blur, gradients) rather than a flat, high-density "trading terminal" look — worth a deliberate visual-direction decision in Phase 4, not just an assumption.

**What to actually reuse from the earlier "Warren" (Prophet) project:** Warren is a simpler, older project than `stock_ai_extreme` — almost everything it did, `stock_ai_extreme` already does better (real indicators, real charts, live updates, multi-model). There is exactly **one** genuinely useful idea worth porting over: Warren's dashboard pulled the company's **profile info** (`sector`, `country`, `website`, `longBusinessSummary`) straight from `yfinance`'s `.info` dict. `stock_ai_extreme` currently shows none of that — add a lightweight "Company Profile" card using the same `.info` fields as part of Phase 4.

---

## 2. DATA SOURCE & API STRATEGY (replaces the "just use Google's API" assumption)

Important correction first: **Google does not offer an official, free, real-time stock-market data API.** Google Finance's public feed was discontinued years ago; nothing free and supported exists to swap in here. Build the provider layer so the app works without Google market data at all, and treats every provider as swappable.

Use a **provider abstraction layer** (interface + multiple implementations), not a hard dependency on one service. Realistic, genuinely free (or free-tier) sources as of today:

| Domain | Primary | Backup / notes |
|---|---|---|
| Stock history (already in use) | `yfinance` (free, unofficial — no SLA, can break, don't rely on it alone) | Alpha Vantage free tier exists but is very tight (roughly 25 requests/day, 5/min, ~15-min delayed) — fine as an occasional fallback, not a primary live source |
| Live/near-real-time equity quotes | Finnhub free tier (free WebSocket trade ticks for US equities, a generous free call allowance — confirm current exact numbers on finnhub.io, they do change) | Polling `yfinance` on an interval (what the current WebSocket route already does) |
| Crypto prices/market data | CoinGecko public endpoint (free, no key needed for basic calls, ~30 requests/min) | Exchange public REST APIs (Binance, Coinbase) for specific pairs |
| Macro/economic indicators | FRED (Federal Reserve Economic Data) — free, official, effectively no rate limit, gold-standard source for rates/inflation/unemployment/GDP/yields | — |
| News | Any officially licensed news API — check commercial-use terms carefully; several "free" news APIs only permit local development, not a live deployed product | RSS from official company/exchange press releases as a legally-safe fallback |
| Forex, commodities | Twelve Data / Alpha Vantage free tiers for prototyping | Treat exactly like the stock provider — swappable, rate-limited, cached |

Every provider call must be wrapped with: rate limiting, retry + exponential backoff, a persistent cache (even SQLite is fine at first), and a `LIVE / RECENT / CACHED / STALE / UNAVAILABLE` status that the frontend actually displays next to the data. **Never show cached or delayed data labeled as "live."**

---

## 3. HONEST REFRAMING — a few requests as written aren't buildable responsibly; here's the version that is

Your original wishlist is genuinely good in most places — it already correctly says "never guarantee profits," "never tell users to buy/sell a coin," "don't fabricate data." A few items in the prose brief need the same honesty applied:

- **"Predict the next president" / "war prediction"** → Nothing — no AI, no dataset — can reliably predict elections or wars from market data; claiming otherwise would be dishonest, not "advanced." Build instead: an **Election/Policy Event Tracker** — surfaces upcoming political/economic events on a calendar, tracks news sentiment around them, and shows the *historical* market reaction to similar past events. Same for geopolitical risk: a **Geopolitical Risk Score** built from news volume/sentiment around conflict-related keywords, clearly labeled as a risk indicator, never a forecast of outcomes.
- **"Which coin should I invest in"** → Keep this as an **analytical ranking** (momentum, volatility, sentiment, risk score — exactly like your own spec's `ai_opportunity_scanner` already says), explicitly labeled "not personalized investment advice," never a direct buy/sell instruction.
- **"Tech no one has used before"** → No individual developer/small team should be promising literally unprecedented technology — that's a red flag, not a spec. The closest honest version is: **genuinely current (2025–2026-era) techniques** that most hobby projects skip — Temporal Fusion Transformer / N-BEATS for forecasting, **conformal prediction** for calibrated uncertainty bands (a real step up from the current ±1.96×RMSE band), SHAP explainability, HMM/change-point-based regime detection, and a RAG-grounded LLM briefing layer. That combination is legitimately advanced without overclaiming.
- **Sports predictions** → Doesn't have a defensible connection to a *financial* intelligence platform. Recommend dropping it. **Weather** can reasonably stay, but scoped only to commodities where the link is real (crude oil, natural gas, agricultural futures) — exactly as your own spec's `market_context` section already says: "only use these signals when a defensible relationship exists."

---

## 4. PHASED ROADMAP

Each phase = inspect → plan → implement incrementally → test it actually running → report back before moving on.

**Phase 1 — Foundation Cleanup**
Fix the two hardcoded-URL bugs (`App.tsx`, `useStockWebSocket.ts` → env variables). Pin all frontend dependency versions. Add `.env.example` entries for every new env var going forward. Add a proper `.gitignore`. Set up separate dev/test/prod config.

**Phase 2 — Real Market Data Layer**
Build the provider-abstraction interfaces from Section 2 (`MarketDataProvider`, `NewsProvider`, `CryptoDataProvider`, `MacroDataProvider`). Wrap `yfinance` as the first implementation. Add caching, retry/backoff, and the `LIVE/RECENT/CACHED/STALE` status object end-to-end (backend → API response → frontend badge).

**Phase 3 — Database & Persistence**
Pick SQLite (simplest, upgrade path to Postgres later) or Postgres directly if you already know you'll deploy multi-user. Core tables: `users`, `assets`, `price_history`, `predictions`, `prediction_history`, `watchlists`, `watchlist_items`, `alerts`, `model_runs`. Add migrations (Alembic).

**Phase 4 — Dashboard & Company Profile**
Bring over the one good Warren idea: a company-profile card (sector/country/website/summary from `yfinance.info`). Make an explicit visual-direction call for the terminal look (flat/high-contrast vs. the current glass/gradient style) rather than defaulting silently. Responsive layout pass (desktop/tablet/mobile).

**Phase 5 — Technical Analysis Expansion**
Add the indicators not yet present: ATR, VWAP, Stochastic Oscillator, ADX. Add chart overlays/toggles and comparison mode to the existing Plotly chart.

**Phase 6 — Baseline ML Hardening**
Add a naive-persistence and moving-average baseline that every "advanced" model must beat before being shown as the default. Log MAE/RMSE/directional accuracy for every model, always alongside the baseline's numbers — never hide a model that loses to the naive baseline.

**Phase 7 — Advanced Forecasting**
Add GRU and a Temporal Fusion Transformer (or N-BEATS) alongside the existing RF/Ridge/LSTM. Build a simple ensemble that combines them. Multi-horizon output (next day / 3 / 5 / 10 sessions), respecting the data frequency you actually have.

**Phase 8 — Probabilistic Forecasting**
Replace the flat ±1.96×RMSE band with conformal prediction or quantile regression for a properly calibrated interval. Surface probability-of-rise / probability-of-fall alongside the point forecast, and don't let the UI conflate "confidence," "probability," and "interval" — they're three different numbers.

**Phase 9 — Backtesting & Validation**
Walk-forward backtesting engine (symbol, date range, model, virtual capital, simple transaction-cost assumption). Report total return, max drawdown, win rate, and a benchmark comparison. Store every prediction ever made (`prediction_history`) so real historical accuracy can be computed later — not simulated.

**Phase 10 — News & Sentiment**
Pick one licensed/legitimate news source with clear commercial terms. Add a financial-domain sentiment model (or a well-tested general NLP sentiment model as a fallback). Tag headlines with related ticker, topic, and sentiment.

**Phase 11 — Macro Intelligence**
FRED integration for rates/inflation/unemployment/GDP/yields. Economic calendar with expected-vs-actual figures and historical market reaction after each release type.

**Phase 12 — Cross-Asset & Sector Analytics**
Correlation matrix, rolling correlation, beta, relative strength across whatever assets you've onboarded by this point.

**Phase 13 — Crypto, Commodities, Forex**
CoinGecko-based crypto module (price, market cap, volume, dominance) with the "analytical ranking, not advice" framing from Section 3. Gold/oil/silver/gas/copper commodity module. Major FX pairs module.

**Phase 14 — AI Market Briefing (LLM + RAG)**
LLM layer that *only* narrates structured data you've already computed — trend, top movers, risk, macro events, model signals. It must never invent a number. Retrieve real stored news/events (RAG) rather than letting the model recall from its own training data for anything time-sensitive.

**Phase 15 — 3D Analytics** *(only once 5–14 give you real data to visualize — 3D on top of fake data is worse than no 3D)*
3D market map (return / volatility / volume), 3D risk landscape, 3D correlation surface. WebGL-based, with a 2D fallback for low-end devices — this isn't decoration, each one needs an actual analytical read that a 2D chart can't give as clearly.

**Phase 16 — Watchlist & Paper Portfolio**
Multiple watchlists, virtual-cash paper portfolio with realized/unrealized P/L, allocation breakdowns. Explicitly "paper" — never real trade execution.

**Phase 17 — Smart Alerts**
Price/volume/volatility/sentiment/news-triggered alerts, persisted history, in-app + browser notification channels.

**Phase 18 — Model Monitoring**
Drift detection (prediction error creeping up, feature distributions shifting), a simple model registry (version, training range, metrics, status), and a visible warning banner when a live model's real-world accuracy degrades.

**Phase 19 — Security & Performance**
Env-based secrets (never in frontend code), input validation, rate limiting on your own API, safe API key proxying, query/index optimization, chart-data downsampling for large ranges.

**Phase 20 — Testing**
Unit tests for indicators/features, API tests, a dedicated "no future leakage" test suite, provider-fallback tests, auth tests, frontend integration tests.

**Phase 21 — Production Deployment**
Production WSGI/ASGI server config, structured logging, `/health` and `/api/system/health` with real subsystem statuses, DB migration strategy for prod, documented rollback plan.

---

## 5. FINAL ACCEPTANCE CHECKLIST

Ship it only once you can honestly check every one of these against the *running* app, not the plan:

Responsive premium UI · real ticker/company search · real historical data · live updates with honest freshness labeling · interactive charts with indicators · multi-horizon forecasts with calibrated uncertainty · walk-forward-validated backtesting · real news + sentiment · macro dashboard · crypto/commodity/forex modules · sector & cross-asset analytics · anomaly & regime detection · explainable AI · model comparison against baseline · watchlists · paper portfolio · smart alerts · model drift monitoring · data-quality/health monitoring · 3D analytics with real analytical value · secure secrets & auth · database persistence · provider fallback & caching · graceful error handling · test coverage · documentation (`README.md`, `ARCHITECTURE.md`, `ML_METHODOLOGY.md`, `DATA_SOURCES.md`, `API_REFERENCE.md`, `MODEL_CARD.md`) · production deployment config.

**Priority order when anything conflicts:** accuracy & data integrity > validation > security > explainability > reliability > performance > raw feature count. A smaller, honestly-working feature always beats an impressive-looking fake one.
