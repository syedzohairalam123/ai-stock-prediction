# Phase 19 — Advanced Market Discovery, New & Trending Engine

**Status: complete.** Backend + frontend both verified on localhost against
real, live sources. Nothing was removed from the application; this pass only
added the discovery module (plus two genuine bug fixes it exposed — see below).

> This is a **discovery** layer, not a recommender and not advice. It ranks
> what real sources measured. It never invents a popularity count, a volume or
> a trend score, and a metric no source publishes renders as **N/A**.

> Note on numbering: the README's historical changelog has an older slice also
> labelled "Phase 19" (rate limiting / input validation). This document is the
> **Phase 19 of the current brief** — market discovery — and it did not touch
> the security middleware.

---

## Task memory — what this work was

Phases 1–18 were already complete. The brief asked for a professional
market-discovery engine:

* feeds: **NEW · TRENDING · POPULAR · RECENTLY UPDATED**, generated from real
  data (actual `createdAt` timestamps — no faked recency);
* a configurable **TrendEngine** with separate, individually callable
  component scorers (`calculateRecencyScore`, `calculateActivityScore`,
  `calculateVelocityScore`, `calculateInterestScore`, `calculateNewsScore`)
  aggregated by `calculateTrendScore()` through configurable weights — with
  **no hidden constants** anywhere;
* a category system (12 categories) with **granular, data-driven sub-tags**;
* discovery filters: category, sub-tag, date, status, source, asset type, plus
  the NEW/TRENDING modes;
* trending cards showing name, category, activity metric, trend score,
  updated time and source/data mode — never fictional activity numbers;
* a `/discover` page with the four sections, switchable **without a full page
  reload**;
* a unified normalized **`DiscoverableEntity`** model covering stocks,
  indices, crypto, commodities, forex, news topics and forecast events;
* **trend history** (`{timestamp, activity, score}`) drawn only from actual
  observations, rendered as small sparklines;
* **tag navigation** (clicking a tag filters exactly the entities that carry
  it — no unrelated matches);
* **personalization** from explicit signals only (watchlist, recently viewed,
  selected categories — never inferred sensitive preferences);
* **caching** on both server and client;
* **performance** work (bounded pages, memoized cards, debounced search,
  cached universe);
* **real data only** — `N/A` wherever a metric is unavailable;
* explainable **Python analytics** (EMA, z-score, slope, acceleration);
* existing search and Phases 1–18 untouched and still functional.

---

## Real bugs found and fixed while building this

1. **Forecast events were mis-categorised by a substring rule.**
   `forecast_markets._category` matched keywords with `in`, so the Tech rule's
   `"ai"` matched **"Strait"** (and "train", "paint", "email"…) — the very real
   geopolitics questions on the front page were being filed as *Tech* while
   genuine geopolitics text fell through to the *Finance* fallback. Matching is
   now word-boundary based with an optional plural (`sport` ⇄ `sports`,
   `match` ⇄ `matches`), the missing geopolitical keywords were added, and a
   quick check now resolves Strait-of-Hormuz questions → **Geopolitics**,
   election questions → **Politics**, "Fed cuts interest rates" → **Economy**.

2. **ORM rows read after the session closed.** `store.observation_history`
   and the topic-timeline reader built their payloads *after* the
   `session_scope()` block. Commit expires ORM attributes, so the detached
   instances raised `Instance … is not bound to a Session` and the endpoints
   silently returned "no history". Both now read inside the session (a real
   bug the new tests caught — it looked like "no data" rather than an error).

3. **(Pre-existing, extended, not broken):** `popular_stocks.fetch_stock_data`
   fetched 30 days of history for the sparkline and then discarded the
   `Volume` column. It now also returns the last session's real volume as an
   additive `volume` field (None when the provider returns none — never
   estimated).

---

## Architecture

```
backend/app/discovery/
  config.py        DiscoverySettings — every weight, saturation, limit and
                   threshold (env prefix DISCOVERY_). Returned by the API so
                   the ranking can be reproduced by hand.
  taxonomy.py      12-category vocabulary + curated, reviewable tag lexicon
                   (whole-word matching) + taxonomy builder with live counts
  entities.py      DiscoverableEntity + ActivityMetric (spec §11) — dataclass
                   contract every collector produces
  trend_engine.py  TrendEngine: recency / activity / velocity / interest /
                   news components + calculate_trend_score() and
                   calculate_popularity_score() with weight renormalization
                   over *available* signals only
  analytics.py     numpy explainable statistics over stored observations:
                   EMA, rolling z-score (anomaly flag), least-squares slope,
                   second-difference acceleration, direction with dead-band
  store.py         persistence: discovery_events (real views/searches),
                   trend_observations (real samples), pruning
  collectors.py    5 isolated collectors → Polymarket forecast events,
                   Phase 17 news topics, PSX quotes (Phase 2 provider chain),
                   real world indices, crypto/commodity/forex instruments
  service.py       collect → enrich (interest/news/velocity) → score →
                   filter → rank → paginate → sample observations
  routes.py        GET  /api/discover                feed + filters + paging
                   GET  /api/discover/taxonomy       categories + sub-tags
                   GET  /api/discover/engine         scoring contract
                   GET  /api/discover/trends/{id}    history + analytics
                   POST /api/discover/events         record a real view/search

frontend/src/
  lib/discovery.ts                 types + DiscoveryService + formatting
  hooks/useDiscoveryQueries.ts     React Query hooks (client caching)
  components/discover/
    DiscoveryCard.tsx              card: activity, score breakdown, tags,
                                   sparkline, updated, source/data mode
    DiscoveryFilters.tsx           §7 filter set + category chips + star pins
    TrendSparkline.tsx             SVG sparkline of stored observations
  pages/DiscoverPage.tsx           route /discover (mode tabs, URL state)
  index.css                        Phase 19 styles (add-only section)
  App.tsx, Layout.tsx, PSXHeader.tsx  route + footer/nav links
```

**New tables** (created by the existing `create_all()` + additive-column
migration — no Alembic needed): `trend_observations`, `discovery_events`.

---

## Data sources (all real, all attributed)

| Entity type | Source | Real fields used |
|---|---|---|
| Forecast events | Polymarket public Gamma API | `createdAt`, `updatedAt`, 24h volume (now passed through), participant count, status |
| News topics | Phase 17 topic engine tables | mention counts, distinct publishers, `trend_velocity`, first/last seen, **hourly timeline buckets used as real trend history** |
| PSX stocks | Phase 2 provider chain (yfinance) | quote, previous close → day change, profile sector/industry, 30-day closes (sparkline + last volume), real 24h headline counts from the news corpus |
| Indices | Provider quotes for real quotable world indices (`^GSPC`, `^DJI`, `^VIX`, `^FTSE`, `^N225` …) | price, day change, quote timestamp |
| Crypto / commodities / forex | Provider quotes over the existing Phase 13 symbol sets | price, day change, quote timestamp |
| Interest (popularity) | **Events this app recorded**: views (`POST /api/discover/events`), search matches (the Phase 13 BM25 search records its hits), watchlist additions (real table) | counts only — 0 means "none recorded", never a placeholder |

PSX **index** levels are still not available on the free provider (the
documented app-wide limitation), so indices are the real world ones only — no
demo index was ever added here.

---

## Scoring rules (spec §4, §17)

* Each component is computed by its own named function and returned in the
  response with the **weights actually used** and the **signals that were
  missing** for that entity.
* A missing signal is **excluded and the remaining weights renormalized** — an
  entity is never punished (or credited) for a signal nobody collects.
* `score = 100 × Σ(component × weight) / Σ(weights used)`, clamped to [0, 100].
* `POPULAR` uses a separate interest-first weighting (interest 0.7, activity
  0.3) via `calculate_popularity_score()`.
* Saturation constants (activity 5% day-change, $250k event volume, 60 topic
  mentions, 6 mentions/h velocity, 25 interest events, 6 publishers, 10
  headlines/24h) and the 72-hour recency half-life all live in
  `config.DiscoverySettings` and are echoed by `GET /api/discover/engine`.
* The raw measured inputs are returned per item (`signals`), so any score can
  be recomputed by hand from the response alone.

## Personalization (spec §14)

Opt-in (`personalize=1` or the **Personalize** switch). Signals used — explicit
actions only: watchlist membership, entities this client opened, categories the
client starred (stored in *this browser's* localStorage). The applied rank
boost (+12%) is disclosed per item (`personalBoostApplied`, `rankScore`) and in
the response. No content-based or sensitive-preference inference exists in the
code.

## Caching & performance (spec §15, §16)

* Server: the whole collected universe is cached (`DISCOVERY_UNIVERSE_CACHE_
  TTL_SECONDS=180`), on top of the provider manager's own quote/history/profile
  caches; scores are recomputed per request over the cached universe.
* Client: React Query (`staleTime` 30 s, background refetch 60 s,
  `keepPreviousData` so mode switches never blank the grid).
* Pagination (24/page + Load more), memoized cards, debounced search (350 ms),
  bounded per-collector limits, throttled observation writes (5 min/entity) and
  pruned tables (7-day observations, 90-day events with a row cap).
* **Virtualization** was deliberately *not* added: feeds are capped pages of
  24 and the tag list is ~40 entries, so there is no long list that needs it —
  adding a windowing dependency for a paged grid would be complexity without a
  benefit.

---

## Verification (all on localhost, real live data)

**Backend:** `python -m pytest -q` → **877 passed** (838 pre-existing + 39 new
`tests/test_discovery.py`: component scorers, weight renormalization,
missing-signal reporting, taxonomy word-boundary regressions, feed sorting for
all four modes, tag/category/since/q filters, personalization disclosure,
pagination, sampling throttle, routes, table existence).

**Live API checks** (running `uvicorn` on `127.0.0.1:8000`):

* `/api/discover?mode=trending` → 96 real entities; VIX with a real −5.11% day
  change topping the list; live Polymarket geopolitics markets with $300k–$1.2M
  real 24h volumes; source health `polymarket OK 26 · news_corpus OK 21 ·
  psx_quotes 23/24 (ENGRO failed, disclosed) · index_quotes OK 10 ·
  instrument_quotes OK 16`.
* `/api/discover?mode=new` → 47 entities with genuine `createdAt`, **49
  entities excluded for having no real creation timestamp** (reported, not
  hidden).
* `/api/discover?tag=Technology&type=stock` → SYS and TRG only, each with its
  real 24h headline count (SYS 3; TRG `null` → its news signal is reported
  missing, not zero).
* `/api/discover/trends/{topic}` → 7 real hourly points from the Phase 17
  timeline with computed z-score/direction/anomaly.
* Live crypto quotes: BTC $83,920.90, ETH $2,684.44, all `LIVE` from yfinance.
* `POST /api/discover/events` → `{"recorded": true}`; the count is then visible
  in that entity's interest breakdown.

**Frontend:** `npx tsc --noEmit` clean, `npm run build` succeeds
(`DiscoverPage` code-split to 21.6 kB). Headless Chrome against
`http://localhost:5173/discover` rendered the full grid with live data, five
source-health chips, sparklines reading real stored observations, deep link
`/discover?mode=new&category=Stocks` restored state from the URL, zero JS
errors, and the pre-existing `/popular` page still renders (no regression).

**Run it:**

```bash
# backend (terminal 1)
cd stock_ai_extreme/backend
python -m uvicorn app.main:app --reload --port 8000

# frontend (terminal 2)
cd stock_ai_extreme/frontend
npm run dev        # http://localhost:5173/discover
```

---

## Honest limitations (stated, not hidden)

* **Velocity** for non-news entities needs at least two stored observations, so
  on a brand-new database the velocity component reports `missing` for stocks,
  indices and instruments; it fills in as the sampler (or the page) runs. News
  topics carry a native Phase 17 velocity from day one.
* **Interest** starts at 0 everywhere on a fresh install — that is the truth,
  and the UI says "0 recorded events" rather than inventing popularity.
* **`created_at`** exists only for forecast events and news topics; stocks,
  indices and instruments have no real creation timestamp in these sources, so
  they are excluded from the NEW feed (and the count excluded is shown).
* The PSX quote source showed `DEGRADED` for one symbol during verification
  (Yahoo `Invalid Crumb` on a single request) — the failure was listed on the
  card strip instead of being hidden, exactly as intended.
* The tag lexicon is a curated keyword list: it is deterministic and
  reviewable by design. Adding a tag is a data edit, not a model retrain.
