/**
 * Phase 11 — Plotly trace/layout model (pure).
 *
 * A chart panel's whole visual contract lives here as plain functions, so the
 * React component only wires state in and renders what comes out. That keeps the
 * expensive Plotly config memoizable on real dependencies (and therefore stable
 * during hover/drag), and makes the model directly reviewable.
 *
 * Axis choice
 * -----------
 * The x axis is a **date axis in epoch-milliseconds**. Plotly then owns ticks,
 * zoom and pan natively, and every annotation (stored in data space) maps
 * through one transform — no fabricated index axis, no lost labels when zoomed.
 *
 * Panes
 * -----
 * `PLOT_MARGINS` + `VOLUME_FRACTION` fully determine the price pane rectangle, so
 * the SVG annotation layer and Plotly agree on where the plot area is without
 * measuring anything at runtime.
 *
 * Interpreting user zoom (`interpretRelayout`) lives here too: it is the one
 * piece of gesture handling that is pure, so it is unit-tested rather than left
 * to a browser assertion.
 */
import type { Config, Data, Layout } from "plotly.js";
import type { Candle, ChartInstance, IndicatorConfig } from "./types";
import type { IndicatorLine } from "./indicators";
import type { StockRange } from "../timeframes";
import { boundsOfCandles } from "./geometry";
import { formatPrice } from "./drawings";
import { toFiniteNumber } from "./math";

export const PLOT_MARGINS = { l: 64, r: 20, b: 28, t: 12 } as const;
/** Share of the price pane's vertical space given to the volume histogram. */
export const VOLUME_FRACTION = 0.22;
/** Gap between the volume pane and the price pane. */
export const PANE_GAP = 0.04;
/** How many of the most recent bars a fresh chart shows. */
export const DEFAULT_VISIBLE_BARS = 160;

/** Colours injected from the active theme (see `useChartTheme`). */
export interface ChartTheme {
  text: string;
  textDim: string;
  grid: string;
  spike: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  up: string;
  down: string;
  volume: string;
  line: string;
  accent: string;
}

export const FALLBACK_THEME: ChartTheme = {
  text: "#e6edf7",
  textDim: "#9daed1",
  grid: "rgba(120,140,180,.22)",
  spike: "rgba(157,174,209,.55)",
  tooltipBg: "#0d1424",
  tooltipBorder: "#31436d",
  tooltipText: "#e6edf7",
  up: "#72BC8F",
  down: "#E97366",
  volume: "rgba(94,159,232,.42)",
  line: "#5E9FE8",
  accent: "#5E9FE8",
};

/** A resolved axis window: epoch ms on x, price on y. */
export interface PlotRange {
  x: [number, number];
  y: [number, number];
}

export interface PaneRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

// ---------------------------------------------------------------------------
// Ranges
// ---------------------------------------------------------------------------

/** Half a bar of breathing room so the edge candles are not clipped. */
function halfBarMs(points: readonly Candle[]): number {
  if (points.length < 2) return 12 * 3600_000;
  const a = points[points.length - 2].timestamp;
  const b = points[points.length - 1].timestamp;
  const spacing = Math.abs(b - a);
  return spacing > 0 ? spacing / 2 : 12 * 3600_000;
}

/** Default window: the most recent `DEFAULT_VISIBLE_BARS` bars, auto-fitted. */
export function defaultRange(points: readonly Candle[], visibleBars = DEFAULT_VISIBLE_BARS): PlotRange | null {
  if (points.length === 0) return null;
  const from = Math.max(0, points.length - Math.max(1, visibleBars));
  const window = points.slice(from);
  const y = boundsOfCandles(window);
  if (!y) return null;
  const pad = halfBarMs(points);
  return { x: [window[0].timestamp - pad, window[window.length - 1].timestamp + pad], y: [y.yMin, y.yMax] };
}

/** Vertical window that fits exactly the bars inside `xRange` (Reset View). */
export function fitRangeForX(points: readonly Candle[], xRange: [number, number]): PlotRange | null {
  if (points.length === 0) return null;
  const [lo, hi] = xRange[0] <= xRange[1] ? xRange : [xRange[1], xRange[0]];
  const window = points.filter((p) => p.timestamp >= lo && p.timestamp <= hi);
  const y = boundsOfCandles(window.length ? window : points);
  if (!y) return null;
  const pad = halfBarMs(points);
  return { x: [window.length ? lo : points[0].timestamp - pad, window.length ? hi : points[points.length - 1].timestamp + pad], y: [y.yMin, y.yMax] };
}

/** Vertical window that also contains the visible indicators (bands included). */
export function fitRangeWithIndicators(
  points: readonly Candle[],
  lines: readonly IndicatorLine[],
  xRange: [number, number]
): PlotRange | null {
  const base = fitRangeForX(points, xRange);
  if (!base) return null;
  let yMin = base.y[0];
  let yMax = base.y[1];
  for (const line of lines) {
    for (let i = 0; i < points.length; i++) {
      if (points[i].timestamp < base.x[0] || points[i].timestamp > base.x[1]) continue;
      const v = line.values[i];
      if (v === null || !Number.isFinite(v)) continue;
      if (v < yMin) yMin = v;
      if (v > yMax) yMax = v;
    }
  }
  if (yMin === yMax) return base;
  const pad = (yMax - yMin) * 0.04;
  return { x: base.x, y: [yMin - pad, yMax + pad] };
}

/** A stored viewport is only reused when it belongs to this exact dataset. */
export function resolveInitialRange(
  points: readonly Candle[],
  fitKey: string,
  viewport: ChartInstance["viewport"]
): PlotRange | null {
  if (viewport && viewport.fitKey === fitKey) {
    const { xRange, yRange } = viewport;
    if (
      Array.isArray(xRange) &&
      xRange.length === 2 &&
      Number.isFinite(xRange[0]) &&
      Number.isFinite(xRange[1]) &&
      xRange[0] < xRange[1] &&
      Number.isFinite(yRange[0]) &&
      Number.isFinite(yRange[1]) &&
      yRange[0] < yRange[1]
    ) {
      return { x: [xRange[0], xRange[1]], y: [yRange[0], yRange[1]] };
    }
  }
  return null;
}

/** Plotly wants date-axis ranges as strings to avoid timezone drift on re-apply. */
export function axisRangeFor(range: PlotRange): { x: [string, string]; y: [number, number] } {
  return {
    x: [new Date(range.x[0]).toISOString(), new Date(range.x[1]).toISOString()],
    y: [range.y[0], range.y[1]],
  };
}

/** Parse whatever Plotly reports back into epoch ms. */
export function parseAxisX(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const t = Date.parse(value);
    return Number.isFinite(t) ? t : null;
  }
  if (value instanceof Date) return value.getTime();
  return null;
}

/** What a `plotly_relayout` payload means for the window we are tracking. */
export type RelayoutOutcome =
  | { kind: "reset" }
  | { kind: "ignore" }
  | { kind: "range"; range: PlotRange };

/**
 * Interpret a `plotly_relayout` payload against the window currently on screen.
 *
 * Why this is not a one-liner: the event is sparse and heterogeneous.
 *
 *   - `plotly_relayout` is *also* emitted for a window resize (`{autosize: true}`),
 *     a modebar action (`{dragmode: "zoom"}`) and legend clicks — none of which
 *     carry axis ranges, and all of which must leave the window untouched.
 *   - A single axis may be reported alone (a y-only zoom, an x-only pan, a box
 *     zoom that touched one axis). The missing axis must be carried over from
 *     `current`, otherwise every annotation would jump.
 *   - A date axis reports ISO strings where a linear axis reports numbers, so
 *     values are parsed permissively but validated strictly: a degenerate or
 *     inverted pair is treated as "no information for this axis", never applied.
 *   - Double-click (and an explicit autorange) hands the axes back to the layout,
 *     which is a *reset*, not a new range — the callers must drop the override.
 */
export function interpretRelayout(event: Record<string, unknown>, current: PlotRange | null): RelayoutOutcome {
  if (event["xaxis.autorange"] || event["yaxis.autorange"]) return { kind: "reset" };

  const x0 = parseAxisX(event["xaxis.range[0]"]);
  const x1 = parseAxisX(event["xaxis.range[1]"]);
  const y0 = toFiniteNumber(event["yaxis.range[0]"]);
  const y1 = toFiniteNumber(event["yaxis.range[1]"]);

  const nextX: [number, number] | null = x0 !== null && x1 !== null && x0 < x1 ? [x0, x1] : null;
  const nextY: [number, number] | null = y0 !== null && y1 !== null && y0 < y1 ? [y0, y1] : null;
  if (!nextX && !nextY) return { kind: "ignore" };
  if (!current) return nextX && nextY ? { kind: "range", range: { x: nextX, y: nextY } } : { kind: "ignore" };

  return { kind: "range", range: { x: nextX ?? current.x, y: nextY ?? current.y } };
}

// ---------------------------------------------------------------------------
// Geometry shared with the annotation layer
// ---------------------------------------------------------------------------

/** The price pane rectangle inside a plot container of `width` × `height`. */
export function pricePaneRect(width: number, height: number, showVolume: boolean): PaneRect {
  const innerWidth = Math.max(0, width - PLOT_MARGINS.l - PLOT_MARGINS.r);
  const innerHeight = Math.max(0, height - PLOT_MARGINS.t - PLOT_MARGINS.b);
  if (!showVolume) {
    return { left: PLOT_MARGINS.l, top: PLOT_MARGINS.t, width: innerWidth, height: innerHeight };
  }
  const priceFrac = 1 - (VOLUME_FRACTION + PANE_GAP);
  return {
    left: PLOT_MARGINS.l,
    top: PLOT_MARGINS.t,
    width: innerWidth,
    height: innerHeight * priceFrac,
  };
}

/** Plotly's `yaxis.domain` for the price pane. */
export function priceDomain(showVolume: boolean): [number, number] {
  return showVolume ? [VOLUME_FRACTION + PANE_GAP, 1] : [0, 1];
}

/** Aspect-correct bar width in ms (candles and volume bars agree). */
export function barWidthMs(points: readonly Candle[]): number {
  if (points.length < 2) return 12 * 3600_000;
  const spacing = Math.abs(points[points.length - 1].timestamp - points[points.length - 2].timestamp);
  if (spacing > 0) return spacing * 0.66;
  const span = Math.abs(points[points.length - 1].timestamp - points[0].timestamp);
  return Math.max(60_000, span / Math.max(1, points.length - 1)) * 0.66;
}

export function tickFormatFor(timeframe: StockRange): string {
  switch (timeframe) {
    case "1D":
      return "%H:%M";
    case "7D":
      return "%d %b %H:%M";
    case "1M":
    case "6M":
      return "%d %b";
    default:
      return "%b %y";
  }
}

/** Hover tooltip date format — precise for intraday, day-granular otherwise. */
export function hoverDateFormat(timeframe: StockRange): string {
  return timeframe === "1D" || timeframe === "7D" ? "%d %b %Y, %H:%M" : "%d %b %Y";
}

// ---------------------------------------------------------------------------
// Traces
// ---------------------------------------------------------------------------

export interface TraceInput {
  instance: ChartInstance;
  points: readonly Candle[];
  lines: readonly IndicatorLine[];
  name: string;
  theme: ChartTheme;
}

/** Number formatting for tooltips/legends — matches the price axis. */
export function formatValue(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return formatPrice(v, digits);
}

export function formatCompactNumber(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

/** Volume bars are shown when the style asks for it, or the user asked for it. */
export function shouldShowVolume(instance: ChartInstance): boolean {
  return instance.chartType === "volume-candles" || instance.volumeVisible;
}

export function buildTraces({ instance, points, lines, name, theme }: TraceInput): Data[] {
  if (points.length === 0) return [];
  const x = points.map((p) => p.timestamp);
  const out: Data[] = [];

  const hoverTemplate =
    `<b>%{customdata[0]}</b><br>` +
    `Open %{customdata[1]}<br>` +
    `High %{customdata[2]}<br>` +
    `Low %{customdata[3]}<br>` +
    `Close <b>%{customdata[4]}</b><br>` +
    `Volume %{customdata[5]}<extra></extra>`;

  const customdata = points.map((p) => [
    new Date(p.timestamp).toISOString().slice(0, 16).replace("T", " "),
    formatValue(p.open),
    formatValue(p.high),
    formatValue(p.low),
    formatValue(p.close),
    p.hasVolume ? formatCompactNumber(p.volume) : "n/a",
  ]);

  if (instance.chartType === "line") {
    out.push({
      type: "scatter",
      mode: "lines",
      name,
      x,
      y: points.map((p) => p.close),
      line: { color: theme.line, width: 2, shape: "spline", smoothing: 0.6 },
      fill: "tozeroy",
      fillcolor: "rgba(94,159,232,.10)",
      customdata,
      hovertemplate: hoverTemplate,
    } as Data);
  } else {
    out.push({
      type: "candlestick",
      name,
      x,
      open: points.map((p) => p.open),
      high: points.map((p) => p.high),
      low: points.map((p) => p.low),
      close: points.map((p) => p.close),
      increasing: { line: { color: theme.up, width: 1.2 }, fillcolor: theme.up },
      decreasing: { line: { color: theme.down, width: 1.2 }, fillcolor: theme.down },
      whiskerwidth: 0.35,
      customdata,
      hoverlabel: { bgcolor: theme.tooltipBg, bordercolor: theme.tooltipBorder, font: { color: theme.tooltipText, size: 11 } },
    } as Data);
  }

  for (const line of lines) {
    out.push({
      type: "scatter",
      mode: "lines",
      name: line.label,
      x,
      y: line.values,
      line: { color: line.color, width: line.width, dash: line.dash },
      hoverinfo: "skip",
      showlegend: false,
      connectgaps: false,
    } as Data);
  }

  if (shouldShowVolume(instance)) {
    out.push({
      type: "bar",
      name: "Volume",
      x,
      y: points.map((p) => (p.hasVolume ? p.volume : 0)),
      yaxis: "y2",
      marker: { color: theme.volume, line: { width: 0 } },
      width: barWidthMs(points),
      hovertemplate: "Volume %{y:,.0f}<extra></extra>",
      showlegend: false,
    } as Data);
  }

  return out;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export interface LayoutInput extends TraceInput {
  /** The window the chart should adopt right now (date-axis strings). */
  range: PlotRange;
  showVolume: boolean;
  /** Changes only when the panel should re-fit — Plotly keeps user zoom otherwise. */
  uirevision: string;
  dragmode: Layout["dragmode"];
}

export function buildLayout({
  instance,
  points,
  range,
  showVolume,
  uirevision,
  dragmode,
  theme,
}: LayoutInput): Partial<Layout> {
  const { settings, crosshairEnabled, timeframe } = instance;
  const axisRange = axisRangeFor(range);
  const maxVolume = points.reduce((m, p) => (p.hasVolume && p.volume > m ? p.volume : m), 1);

  const xaxis: Layout["xaxis"] = {
    // Declared explicitly: with numeric (epoch-ms) x values Plotly would infer a
    // *linear* axis and label it with raw milliseconds. `date` makes ticks,
    // ranges and the unified hover read as calendar time — the only thing a
    // trading chart may show on its time axis.
    type: "date",
    gridcolor: theme.grid,
    showgrid: settings.grid,
    zeroline: false,
    tickfont: { size: 10, color: theme.textDim },
    tickformat: tickFormatFor(timeframe),
    hoverformat: hoverDateFormat(timeframe),
    nticks: 7,
    range: axisRange.x,
    rangeslider: { visible: false },
    showspikes: crosshairEnabled,
    spikemode: "across",
    spikethickness: 1,
    spikedash: "solid",
    spikecolor: theme.spike,
  };

  const yaxis: Layout["yaxis"] = {
    gridcolor: theme.grid,
    showgrid: settings.grid,
    zeroline: false,
    tickfont: { size: 10, color: theme.textDim },
    side: "left",
    domain: priceDomain(showVolume),
    // Prices are quoted in PKR; two decimals is the venue convention.
    tickformat: ",.2f",
    range: axisRange.y,
    showspikes: crosshairEnabled,
    spikemode: "across",
    spikethickness: 1,
    spikedash: "solid",
    spikecolor: theme.spike,
    autorange: false,
  };

  const layout: Partial<Layout> = {
    uirevision,
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: theme.textDim, size: 11, family: "inherit" },
    margin: { ...PLOT_MARGINS },
    showlegend: false,
    dragmode,
    hovermode: crosshairEnabled ? "x unified" : "closest",
    hoverlabel: {
      bgcolor: theme.tooltipBg,
      bordercolor: theme.tooltipBorder,
      font: { color: theme.tooltipText, size: 11 },
    },
    xaxis,
    yaxis,
    bargap: 0,
    // The annotation layer owns drawings/price levels, so Plotly needs no shapes.
    shapes: [],
    annotations: [],
  };

  if (showVolume) {
    layout.yaxis2 = {
      domain: [0, VOLUME_FRACTION],
      range: [0, maxVolume * 4],
      fixedrange: true,
      visible: false,
      type: "linear",
      gridcolor: "transparent",
      showgrid: false,
    };
  }

  return layout;
}

/**
 * Index of the candle closest to `timestamp` (binary search over a sorted
 * series), or -1 for an empty series.
 *
 * Needed because not every Plotly trace reports `pointIndex` on hover — the
 * candlestick trace does not — so the readout resolves the bar from the time
 * value when the index is missing.
 */
export function nearestIndexByTime(points: readonly { timestamp: number }[], timestamp: number): number {
  if (points.length === 0) return -1;
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid].timestamp < timestamp) lo = mid + 1;
    else hi = mid;
  }
  // `lo` now sits on the first candle at/after the timestamp; pick the closer of
  // it and its predecessor.
  if (lo > 0) {
    const before = points[lo - 1].timestamp;
    const after = points[lo].timestamp;
    return Math.abs(before - timestamp) <= Math.abs(after - timestamp) ? lo - 1 : lo;
  }
  return lo;
}

export function buildConfig(): Partial<Config> {
  return {
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
    scrollZoom: true,
    doubleClick: "reset",
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
  };
}

// ---------------------------------------------------------------------------
// Legend / readout model
// ---------------------------------------------------------------------------

export interface LegendRow {
  indicatorId: string;
  label: string;
  color: string;
  values: { label: string; value: number | null }[];
}

/** Which enabled indicators are actually plottable (for the legend header). */
export function enabledIndicators(indicators: readonly IndicatorConfig[]): IndicatorConfig[] {
  return indicators.filter((i) => i.enabled);
}
