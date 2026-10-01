# PHASE 22C — CRYPTO VOLATILITY MARKETS UI + SUBCATEGORIES + REAL-TIME INTEGRATION

Audit + build report. **Nothing was removed.** Phases 22A and 22B remain intact
and their engines are consumed as-is (no rewrite).

## 1. What was built (frontend only)

The Phase 22C surface was added on top of the existing `/crypto-terminal` page
(the Phase 22A data-foundation view), which continues to work.

New components (`frontend/src/components/crypto/`):

| File | Purpose |
|---|---|
| `CryptoSubcategoryNav.tsx` | ALL / PRE-MARKET / INSTITUTIONS / TARGETS / INDUSTRY tabs (§1/§2) |
| `CryptoStates.tsx` | skeleton / `NO DATA AVAILABLE` empty / isolated widget error / panel chrome (§23–§25) |
| `CryptoSignalPanels.tsx` | Micro-trend card, Volatility card, micro-trend timeline (§5–§7) |
| `CryptoForecastPanel.tsx` | MODELLED FORECAST card + model provenance + validation table (§8/§9/§35) |
| `CryptoTargetsPanel.tsx` | target ladder + target comparison + threshold analyzer (§10–§13/§36) |
| `CryptoCategoryPanels.tsx` | PRE-MARKET / INSTITUTIONS / INDUSTRY views (§15/§16/§18) |

New hooks (`frontend/src/hooks/useCryptoQueries.ts`): forecast, forecast history,
forecast performance, targets, target history, threshold, on-date, pre-session,
institutions, industry — each mapped to a real backend endpoint.

Page (`frontend/src/pages/CryptoMarketTerminalPage.tsx`) now renders the
subcategories, a prominent timeframe selector, the micro-trend/volatility cards,
the trend timeline, the forecast card, the multi-timeframe table and the sources
panel, with per-widget error isolation and, in ALL, the market header + chart.

## 2. Category rule (§2) — each tab is a real query

| Tab | Backend dataset |
|---|---|
| ALL | `GET /quote`, `/candles`, `/analytics`, `/multi-timeframe`, `/forecast` |
| PRE-MARKET | `GET /categories/pre-session` (continuous 24/7 boundaries + observed trending) |
| INSTITUTIONS | `GET /categories/institutions/{symbol}` (disclosed holdings, source/coverage) |
| TARGETS | `GET /targets/{symbol}` + `/threshold/{symbol}` + `/on-date/{symbol}` |
| INDUSTRY | `GET /categories/industry` (documented taxonomy + provider categories) |

A category with no data renders `NO DATA AVAILABLE` / `NO VERIFIED DATA`.

## 3. Real-data end-to-end trace (§30, measured on this machine)

BTC, backend on `127.0.0.1:8000`:

- quote: `binance`, price ≈ 83,916–83,922, status LIVE (REST + WS tick observed)
- candles/analytics: real Binance klines, quality HIGH, gaps `DATA COMPLETE`
- multi-timeframe: 8 rows (5m/15m/1h/4h/1d/1w/1M/1Y), 1Y rolled up from monthly
- forecast: `LIVE`, 7 candidates validated, model `naive` (baseline won — reported)
- targets: real swing ladder (support 82,874.93 / 83,183.00 / 83,500.01;
  resistance 83,849.00 / 84,193.39 / 84,336.96), 7 active / 0 reached
- threshold(85,000, 1h, h=5): empirical 3.42%, GBM 3.38%, 995 samples,
  Brier 0.0168, Brier skill 0.75, 249 calibration samples
- on-date 2026-09-30 @ 85,000: `ANSWERED true`, evidence `bar high 85649.95 vs
  threshold 85000.0`, observation 2026-09-30T00:00:00Z
- pre-session: `is_24_7 = true`, boundaries DAY/WEEK/MONTH, 15 observed trending
- institutions BTC: source `coingecko`, total holdings 1,298,212.67, coverage stated
- industry: 12 documented industries; 24 real provider categories (`LIVE`)

## 4. Audits

| Spec | Result |
|---|---|
| §31 no-dummy audit | No `Math.random`/mock/dummy/hardcoded price in the crypto production path. `lib/crypto.ts` uses `Math.random`/`crypto.randomUUID` **only** to generate a client id, never a value. |
| §32 API audit | All 5 subcategory datasets + forecast/targets/threshold/on-date return real data with real timestamps and source labels. |
| §33 WebSocket audit | `connect → subscribe → snapshot(200 candles) → tick` observed via a real WS client. Reconnect logic (backoff + fresh snapshot) is in `useCryptoSocket`. |
| §34 timeframe audit | 7 native + 1 roll-up; each row computed from its own dataset; cached per (symbol, timeframe). |
| §35 forecast audit | model, version, feature version, training window/end, validation metrics, prediction and generated time all present. |
| §36 target audit | status/distance/touches/timestamps all computed server-side from real candles. |
| §40 security | Provider keys are backend-only (frontend has no keys); ticker/threshold input validated server-side; crypto REST has an IP rate limiter; no arbitrary HTML execution. |
| §20 connection state | CONNECTED / RECONNECTING / CONNECTING / DISCONNECTED with a `LIVE DATA CONNECTION LOST` banner. |
| §27 accessibility | timeframe/subcategory buttons use `role=tab`/`aria-selected`/`aria-pressed`; charts have captions/`sr-only` text; gain/loss shown with sign + arrow + word, never colour alone; focus-visible outlines. |

## 5. Not verified (stated honestly, §38)

- **10,000 concurrent users — NOT VERIFIED.** No load test was run against this
  host in this pass. The architecture (single shared provider connection,
  coalesced fan-out, per-process cache) is designed for it, but the spec requires
  measurement, and there is none here. Do not treat capacity as proven.
- Redis-backed multi-worker fan-out is available (`REDIS_URL`) but was not
  exercised in this pass.

## 6. Checks

| Check | Result |
|---|---|
| `tsc --noEmit` | clean |
| `vite build` | success (`CryptoMarketTerminalPage` chunk built) |
| Backend crypto suite | 197 passed (Phase 22B report) |

Localhost: backend `http://127.0.0.1:8000`, UI `http://localhost:5173/crypto-terminal`.

## 22C.1 — Post-review addition: primary top-nav entry

User request: "crypto-terminal ka option bhi uppar nav bar may do". Additive-only change in
`frontend/src/components/PSXHeader.tsx`:

- Added `{ path: '/crypto-terminal', label: 'Crypto Terminal', icon: Bitcoin }` to the primary
  top `navLinks` array, placed right after the Esports entry (same first-class-hub treatment,
  own lucide icon).
- `Bitcoin` icon imported from `lucide-react` alongside the existing `Gamepad2` import.
- MORE-dropdown entry kept as-is (nothing removed; same page now reachable from both places,
  matching the 21C additive philosophy).
- Mobile drawer inherits the entry automatically (it maps the same `navLinks` array).

Verification: `tsc --noEmit` clean; Vite HMR serving updated module (grep confirms
`crypto-terminal` in transformed output); `http://localhost:5173/crypto-terminal` → HTTP 200.

## 22C.2 — Mobile view test (390×844) + pre-existing drawer bug fix

Mobile verification was done with headless Chrome CDP (mobile emulation 390×844, real
input-event dispatch, DOM hit-testing), not just CSS inspection.

**Pre-existing bug found (affects every page, not crypto-specific):** the mobile drawer
overlay (`.psx-mobile-menu`, `position:fixed; inset:0`) is rendered inside `.psx-header`,
whose `backdrop-filter: blur(14px)` (index.css line 500) makes the header the containing
block for fixed descendants per CSS spec. The overlay therefore collapsed to the header's
height (~158px instead of 844px): the drawer body was visually clipped, links below it were
unpainted, and taps/clicks on drawer entries in the lower 80% of the screen fell through to
the page underneath (verified: click on "Crypto Terminal" slot actually hit the HomePage
ENGRO quick-ticker button underneath; `elementFromPoint` returned `quick-ticker-btn`).

**Fix (minimal, additive):** `PSXHeader.tsx` now renders the mobile menu overlay through a
React portal on `document.body` (`createPortal(..., document.body)`), escaping the header's
backdrop-filter containing block. Header CSS untouched; desktop nav untouched.

**Verified after fix (headless Chrome, real mouse/touch input):**
- Overlay geometry: 390×844 = full viewport, mounted on `<body>` ✓
- Hit-test: the Crypto Terminal drawer entry is its own hit target (`elementFromPoint`) ✓
- Full flow with dispatched clicks: hamburger → drawer opens → tap Crypto Terminal →
  navigates to `/crypto-terminal` AND drawer closes ✓ (this exact flow failed before the fix)
- Terminal page on 390px: no horizontal overflow, 5 subcategory buttons (ALL / PRE-MARKET /
  INSTITUTIONS / TARGETS / INDUSTRY), all 8 timeframes (5m/15m/1h/4h/1d/1w/1M/1Y),
  129 crypto-* elements, no error/UNAVAILABLE strings ✓
- Regression sweep: drawer overlay full-viewport on `/`, `/market`, `/esports` too ✓
- Desktop widths 1024/1280/1440: no page or header overflow (nav was already multi-row wrap;
  ≤820px switches to the drawer) ✓
- `tsc --noEmit` clean; `vite build` success ✓

Test-harness notes (for reproducibility): CDP input must read element rects only after the
drawer's 0.2s slide-in animation settles, and `Emulation.setDeviceMetricsOverride` is required
for viewport-accurate media queries.

STOP — Phase 22C complete. No real-money trading/wagering was added.
