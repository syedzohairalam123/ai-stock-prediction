# Phase 11 — Professional Charting & Technical Analysis Engine

Technical report. Phases 1–10 were left functional; nothing was removed or
redesigned. The existing chart was promoted into a **multi-panel technical
analysis workspace** on top of the libraries the project already used
(`plotly.js` + `react-plotly.js`, `zustand` + `persist`, React Query, the Phase-5
timeframe system and the Phase-2/5 market-data services).

---

## 1. Architecture

```
/charts  (pages/ChartWorkspacePage.tsx — thin shell: deep-links, URL sync)
 │
 ▼
ChartWorkspace            components/charting/ChartWorkspace.tsx
 │                        single | split | mobile — decides how many panels
 ▼
ChartPanel (× 2)          components/charting/ChartPanel.tsx   ← one ChartInstance
 │  │                     ├─ React Query dataset (hooks/useChartData)
 │  │                     ├─ memoized indicator compute (lib/charting/indicators)
 │  │                     ├─ axis window + persisted viewport (lib/charting/plotModel)
 │  │                     └─ its own ErrorBoundary (a broken panel never takes the page)
 │  ▼
 │  ChartToolbar + DrawingToolbar + IndicatorMenu + PriceLevelMenu + SymbolSearch
 │
 ▼
PlotSurface               components/charting/PlotSurface.tsx
 │                        ├─ memoized Plotly figure (traces / layout / config)
 │                        ├─ pointer gestures: place · select · move · resize · drag level
 │                        └─ ChartHud: crosshair readout + indicator legend
 ▼
AnnotationLayer (SVG)     components/charting/AnnotationLayer.tsx
                          drawings + price levels, painted in *data space*
```

Data pipeline:

```
provider row                normalizer                 engine
─────────────              ─────────────              ─────────────
MarketService.getHistory  ─┐
(PSX stocks)               ├─► normalizeOHLCV() ──► Candle[] ──► computeIndicators()
getHistoryAsync (indices) ─┘   reject/repair/dedupe             SMA·EMA·VWAP·BB
                               (honest stats)                    (memoized)
```

Layer by layer:

| Layer | File | Responsibility |
|---|---|---|
| Types | `lib/charting/types.ts` | `ChartInstance`, `Candle`, `DrawingShape`, `PriceLevel`, `Viewport`, `NormalizedDataset` |
| Maths | `lib/charting/math.ts` | `mean`, `stdev`, `rollingMean`, `rollingStdev`, `clamp`, `unlerp`, numeric guards |
| Indicators | `lib/charting/indicators.ts` | `calculateSMA/EMA/VWAP/BollingerBands`, memoized `computeIndicators`, `unavailable[]` |
| Normalization | `lib/charting/ohlcv.ts` | `normalizeOHLCV`, timestamp parsing, provider adapters |
| Geometry | `lib/charting/geometry.ts` | the **only** data-space ⇄ pixel module; hit testing |
| Drawings | `lib/charting/drawings.ts` | create / translate / re-anchor, price-level catalog |
| Annotation model | `lib/charting/annotations.ts` | render layers + hit testing (one source of truth) |
| Defaults | `lib/charting/defaults.ts` | indicator catalog, chart styles, instance factory, `datasetFitKey` |
| Data source | `lib/charting/dataSource.ts` | unified stock/index loader, symbol universe, typed errors |
| Plot model | `lib/charting/plotModel.ts` | traces, layout, ranges, `interpretRelayout`, axis↔pixel pane rect |
| State | `store/useChartStore.ts` | persisted workspace + per-chart undo/redo |

---

## 2. Multi-chart workspace (§3, §4, §28)

* Two independent panels — **Chart A** (opens on `OGDC` 6M) and **Chart B**
  (opens on `KSE100` 1Y). `layout` is `single` or `split`; split stacks A over B.
* Each panel owns symbol, entity type, timeframe, chart style, indicators,
  drawings, price levels, viewport and display settings. Changing one panel
  cannot touch the other (verified in the browser audit).
* Responsive behaviour is decided in JavaScript (`useMediaQuery`), not only in
  CSS, because the *number* of panels changes:
  * **desktop** — single or side-by-side stack,
  * **tablet** — the same stack, which reads as stacked charts,
  * **mobile (≤820px)** — exactly one panel plus an explicit Chart A / Chart B
    switcher, so a 390px viewport never gets two squeezed plots.
* Touch input works throughout: gestures set `touch-action: none` while a tool
  is armed, and every drag is a pointer-capture gesture.

## 3. Chart styles (§5)

`candles` · `volume-candles` · `line`, chosen from a toolbar dropdown.
Switching style changes **only** the trace type — symbol, timeframe, viewport,
indicators, drawings and price levels are deliberately preserved (the store's
`setChartStyle` is a pure style write).

## 4. OHLCV normalization (§6)

`normalizeOHLCV` is the single gate every candle passes through. It is honest
about what it had to do, and it never invents data:

| Situation | Behaviour |
|---|---|
| Non-numeric / non-positive price, unparseable timestamp | **rejected** and counted |
| Duplicate timestamp | last print wins, counted |
| Out-of-order rows | re-sorted ascending, counted |
| `high < low`, `high < max(o,c)`, `low > min(o,c)` | clamped into a coherent candle, counted (reject instead with `repair: false`) |
| Missing volume | `volume: 0`, `hasVolume: false`, counted — surfaced in the UI, never implied as "zero traded" |
| Missing candles (calendar gaps) | **not fabricated** |

Timestamps accept epoch ms/s, ISO strings and the PSX `"YYYY-MM-DD"` /
`"YYYY-MM-DD HH:mm"` formats; bare calendar days are parsed as UTC so a row maps
to the same instant in every timezone. A data-quality chip on the panel reports
the counts whenever the normalizer had to intervene.

## 5. Indicator engine (§8–§14)

| Indicator | Formula | Notes |
|---|---|---|
| SMA 20 / SMA 50 | `Σ close / period` | rolling, `null` until the window is complete |
| EMA 20 | `k = 2/(period+1)`, seeded by the SMA of the first `period` closes | period configurable from the panel (default 20) |
| VWAP | `Σ(typical × volume) / Σ volume`, `typical = (H+L+C)/3` | cumulative intraday; requires intraday bars **and** real volume |
| Bollinger Bands 20/2 | SMA middle ± `multiplier ×` rolling population σ | multiplier configurable (default 2) |

* Calculations live in `math.ts`/`indicators.ts` — **never inside a React
  render**. Every indicator is expressed with the shared statistical primitives.
* Insufficient history yields `null` values, so a line is simply not drawn until
  it is meaningful; the legend then reads “insufficient history”.
* **VWAP is never fabricated.** On a daily dataset (or a series with no volume)
  the engine returns an `unavailable` entry carrying the exact reason
  `"VWAP unavailable for this dataset"`, which the indicators panel displays.
* The Indicators panel supports enable/disable, colour, period, BB multiplier,
  remove, “add another” and reset — SMA 20 + SMA 50 on, EMA 20 / VWAP /
  Bollinger Bands off, exactly as specified.
* Results are memoized on `datasetKey + enabled-config signature`, so hover,
  panning, style switches and the second split panel never recompute (§27).

## 6. Drawings (§15–§18)

Five primitives — **Trend Line, Rectangle, Circle, Parabola, Semicircle** — drawn
as real SVG paths on an overlay that shares the plot rectangle with Plotly, not
as decorative HTML.

Stored model:

```ts
{ id, type, coordinates: [{ t, p }, { t, p }], style, visible, locked }
```

`t` is a time-axis value (epoch ms, fractional allowed) and `p` a price — i.e.
**data space**. `geometry.ts` is the only module that converts to pixels, so a
drawing survives zoom, resize, timeframe switches and viewport moves unchanged
(§16, §21). Curve primitives are parametrized in pixels but driven by two
data-space anchors, which is the only way a circle stays round on axes whose
price/time scales differ by orders of magnitude.

Actions: create, move (drag the shape), resize (drag an anchor), delete, hide,
show, lock, unlock, clear all, **undo/redo** (60-step per-chart stack). The
toolbar is compact, every control has a tooltip and an explicit active state, and
the cursor reflects the current mode. Escape unwinds cleanly: abandon a
half-placed shape → deselect → disarm the tool.

## 7. Price levels (§19–§21)

`SUPPORT` · `RESISTANCE` · `ENTRY` · `STOP_LOSS` · `TARGET`, stored as

```ts
{ id, type, price, label, visible, locked }
```

Only the **price** is persisted; the pixel row is derived on every frame, so a
level stays glued to its value through zoom, resize, timeframe change and
viewport movement. The chip renders the level's *live* price, so dragging a line
can never leave a stale number behind. A level can be placed by clicking the
chart with a tool armed, quick-placed at the last price, dragged, renamed,
**price-edited from the list**, hidden, locked (which blocks dragging) or
deleted. Repeat placements on the same price stack by a small ATR-like offset
instead of silently landing on top of each other.

## 8. Crosshair, legend, toolbar (§22–§24)

* Crosshair via Plotly's spike lines plus a floating HUD that follows the hovered
  bar and reports **date/time, O, H, L, C, volume**, the change on the bar, the
  bar index and the active indicator values. When no index is available on the
  hover point (candlestick traces do not report one) it is recovered by binary
  search over the hovered time — otherwise the readout would sit on “latest”
  forever for the default chart style.
* The legend lists every active indicator with its colour and value at the
  selected bar (Bollinger shows the middle band, with bands labelled separately).
* The toolbar carries symbol (combobox over the existing PSX universe, indices
  first), timeframe (`1D · 7D · 1M · 6M · 1Y · 3Y · 5Y`), chart style, indicators,
  drawing tools, price levels, volume, crosshair, settings, fit/reset and
  fullscreen. It wraps to two compact rows.

## 9. Fullscreen & persistence (§25, §26)

* Fullscreen uses the real Fullscreen API on the panel **element**, so nothing
  unmounts and the whole chart state (indicators, drawings, levels, timeframe,
  viewport) survives. If the API is unavailable or refuses, the hook degrades to
  a maximised in-page mode so the button is never a no-op; Escape always exits.
* Persistence reuses the project's existing zustand-persist architecture
  (`neural-market-chart-workspace`): layout, active panel, per-chart symbol /
  timeframe / style / indicators / drawings / price levels / settings and the
  saved viewport. Undo stacks and transient cursor modes are deliberately **not**
  persisted — a stale editing history replayed after a reload would mutate
  annotations the user cannot see.
* A persisted viewport is re-applied only when its `fitKey`
  (`symbol|timeframe|bars|first|last`) still matches, so a stale zoom can never
  distort a different dataset — the panel simply re-fits.

## 10. States & performance (§27, §29)

* A chart is never an unexplained blank rectangle: sized loading skeleton,
  unknown-symbol state with working suggestions, honest “no bars for this
  window” state, fetch-failure state with retry, and a per-panel error boundary
  so one broken panel cannot blank the workspace.
* Performance: figure props are memoized on their real dependencies (hover and
  drag state are deliberately excluded), indicator maths is memoized twice,
  Plotly `uirevision` keeps user zoom, drags render from a local override and
  commit to the store **once per gesture** (one undo step, one localStorage
  write), and viewport persistence is debounced 500ms.

---

## 11. Files created / modified

**Engine (`src/lib/charting/`)**

| File | Purpose |
|---|---|
| `types.ts` | shared models (chart instance, candle, drawings, levels) |
| `math.ts` | statistical primitives |
| `indicators.ts` | SMA / EMA / VWAP / Bollinger + memoized compute + unavailable reasons |
| `ohlcv.ts` | normalization and provider adapters |
| `geometry.ts` | data-space ⇄ pixel transform, hit testing, curve sampling |
| `drawings.ts` | drawing & price-level model helpers, catalogs, ids, formatting |
| `annotations.ts` | render layers + hit testing |
| `defaults.ts` | indicator catalog, styles, instance factory, `datasetFitKey` |
| `dataSource.ts` | unified stock/index dataset loader, symbol universe, typed errors |
| `plotModel.ts` | traces, layout, ranges, relayout interpretation, pane rect |
| `index.ts` | public surface re-export |

**UI (`src/components/charting/`)**

`ChartWorkspace` · `ChartPanel` · `PlotSurface` · `AnnotationLayer` · `ChartHud` ·
`ChartToolbar` · `DrawingToolbar` · `IndicatorMenu` · `PriceLevelMenu` ·
`SymbolSearch` · `Dropdown` · `ChartStates`

**Hooks / store / page / styles**

`hooks/useChartData` · `hooks/useChartTheme` · `hooks/useElementSize` ·
`hooks/useFullscreen` · `hooks/useMediaQuery` · `store/useChartStore` ·
`pages/ChartWorkspacePage` · chart styles in `src/index.css` · route in
`src/App.tsx` · footer link in `src/Layout.tsx`

**Tests**

`scripts/chart-engine-test.mjs` (Node, bundles the pure engine with esbuild) ·
`scripts/chart-audit.mjs` (Chrome DevTools Protocol, real input events)

---

## 12. Bugs found and fixed in this pass

1. **Plotly emitter teardown crashed the workspace on every panel unmount.**
   `PlotSurface` subscribed to `plotly_relayout` / `plotly_hover` /
   `plotly_unhover` directly on the graph div and detached with
   `removeListener` in its effect cleanup. `Plotly.purge` **deletes** those
   methods from the div (Plotly mixes them in as own properties), and React tears
   a child down before its parent — so react-plotly had already purged the div by
   the time the cleanup ran. The resulting
   `TypeError: emitter.removeListener is not a function` was thrown from inside a
   passive unmount, which React cannot recover from: it propagated past the
   panel's error boundary and blanked the entire page. It fired on every split →
   single switch, every switch to mobile, and (because StrictMode double-mounts)
   on every page load in development.

   Fix: capture the attach/detach functions **bound at attach time**, guard every
   call, fall back to native `addEventListener`/`removeEventListener` if Plotly
   ever drops the mixin, and treat “the plot was already purged” as a no-op
   rather than an error.

2. **The footer's “Charts” link never navigated.** `Layout.tsx` used
   `href="#/charts"` while the app mounts a `BrowserRouter`, so the link only set
   a URL fragment. Replaced the footer links (`Charts`, `Settings`, `Alerts`,
   `Screener`, `Sentiment`) with react-router `Link`s, which also restores the
   chart workspace's entry point from every page.

3. **The crosshair readout sat on “latest” because Plotly's candlestick hover
   event is unreliable.** The readout depended entirely on `plotly_hover`, and
   that event was found to silently stop firing on candlestick figures — while
   scatter traces on the same figure kept delivering it — reproducibly under
   CDP device-metrics emulation and intermittently under normal use, without
   any error. An `x unified` figure built on a suppressed-candlestick base
   simply never emits. Because candlestick is the *default* chart style, the
   analyst's readout froze on the newest bar while they pointed at a specific
   candle.

   Fix: the readout no longer depends on Plotly's event alone. The existing
   pointer-move gesture handler now also resolves the hovered bar through the
   same data-space transform the annotation layer uses (`toData` →
   `nearestIndexByTime`, an O(log n) binary search per move — the memoized
   indicator maths is untouched, so §27's performance contract holds).
   Plotly's event remains wired and authoritative when it fires; the pointer
   path only guarantees the readout is never stale. Pointer leave clears the
   override so the HUD falls back to the latest bar as designed.

## 13. Test results

| Check | Command | Result |
|---|---|---|
| TypeScript | `npx tsc --noEmit` | clean (exit 0) |
| Production build | `npm run build` | succeeds; `ChartWorkspacePage` chunk 85.9 kB (gzip 26.5 kB) |
| Engine unit assertions | `node scripts/chart-engine-test.mjs` | **178 / 178 passed** |
| Browser workspace audit | `node scripts/chart-audit.mjs` | **95 / 95 passed** |

The engine harness exercises §6 normalization (duplicates, ordering, malformed
rows, repair, volume), §9–§13 indicator correctness including “insufficient
history”, §16 drawings staying in data space when moved, §21 price levels
attached to a price rather than a pixel, and §5 chart-style trace shapes.

The browser audit drives the real page over the DevTools Protocol with genuine
input events: layout switching, all three chart styles, every indicator toggle
and the VWAP unavailable path, periods, split independence, all five drawing
primitives, undo/redo, selection, delete-by-keyboard, every price-level action
including dragging and locking, the crosshair readout, fullscreen, zoom
persistence **and** restoration across a reload, mobile switching, mobile
drawing, and finally hygiene — **no uncaught exceptions and no console errors
from the charting code**.

Manual runs during the build were made with the backend on `:8000` deliberately
**down**, which is the honest worst case: the chart falls back to the Phase-5
sample history and labels the panel `CACHED · fallback` instead of pretending the
data is live.

## 14. Known limitations

* **Chart B is the only second panel.** The workspace supports single and split
  (A over B) as specified; there is no user-defined N-panel grid.
* **Index series are deterministic sample data.** Stock candles come from the
  market-history API; PSX index bars come from the Phase-2 generator and the
  panel labels them `PSX index series`, so the two are never confused.
* **VWAP needs genuine intraday volume.** With the sample fallback in place it
  will usually report itself unavailable — deliberately, rather than drawing a
  fabricated number.
* **Undo/redo covers annotations**, not viewport changes or indicator toggles
  (those are persisted configuration, not edits).
* **The drawing set is the specified five primitives** plus the five price-level
  types; there is no Fibonacci/pitchfork/measure tool yet.
* **Pixel-perfect plot-rect agreement assumes the chart's own margins.** The SVG
  overlay derives the price pane from `PLOT_MARGINS` + `VOLUME_FRACTION` rather
  than measuring Plotly's DOM, so any future change to those constants must be
  made in `plotModel.ts` (single source of truth).
