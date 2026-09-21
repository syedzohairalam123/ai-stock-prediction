/**
 * Phase 11 — chart defaults & instance factory (spec §4, §5, §8, §14).
 *
 * One place defines what a fresh chart looks like, so a new panel, a reset and a
 * first-ever visit all agree. Defaults follow the spec's indicator panel exactly:
 * SMA 20 and SMA 50 start on, EMA 20 / VWAP / Bollinger Bands start off.
 */
import { rangeWindow, STOCK_RANGES, type StockRange } from "../timeframes";
import type { ChartInstance, ChartSettings, IndicatorConfig, IndicatorType } from "./types";

/** The two fixed panel ids — single and split layouts both use these. */
export const CHART_IDS = ["chart-a", "chart-b"] as const;
export type ChartId = (typeof CHART_IDS)[number];

export const DEFAULT_SETTINGS: ChartSettings = {
  grid: true,
  lastPriceLine: true,
  legend: true,
  paddedFit: true,
};

/**
 * The indicator catalog (spec §8 / §14). `id` doubles as the stable persistence
 * key, so toggles and colours survive a reload.
 */
export const INDICATOR_CATALOG: IndicatorConfig[] = [
  { id: "SMA:20", type: "SMA", enabled: true, period: 20, color: "#5E9FE8", lineWidth: 1.7, configurable: true },
  { id: "SMA:50", type: "SMA", enabled: true, period: 50, color: "#DE9255", lineWidth: 1.7, configurable: true },
  { id: "EMA:20", type: "EMA", enabled: false, period: 20, color: "#BF8EDA", lineWidth: 1.7, configurable: true },
  { id: "VWAP", type: "VWAP", enabled: false, period: 1, color: "#2dd4bf", lineWidth: 1.7, configurable: false },
  { id: "BB:20", type: "BB", enabled: false, period: 20, stdDev: 2, color: "#72BC8F", lineWidth: 1.2, configurable: true },
  // Phase 11 additions — oscillator sub-panes. All start disabled, so a fresh
  // chart looks exactly as it did before; enabling one adds its own pane.
  { id: "RSI", type: "RSI", enabled: false, period: 14, color: "#5E9FE8", lineWidth: 1.6, configurable: true, pane: "sub" },
  { id: "MACD", type: "MACD", enabled: false, period: 26, fastPeriod: 12, slowPeriod: 26, signalPeriod: 9, color: "#5E9FE8", lineWidth: 1.6, configurable: true, pane: "sub" },
  { id: "STOCH", type: "STOCH", enabled: false, period: 14, signalPeriod: 3, color: "#BF8EDA", lineWidth: 1.6, configurable: true, pane: "sub" },
  { id: "ATR", type: "ATR", enabled: false, period: 14, color: "#DE9255", lineWidth: 1.6, configurable: true, pane: "sub" },
];

/** Fresh copies (never the catalog objects themselves — they get mutated). */
export function defaultIndicators(): IndicatorConfig[] {
  return INDICATOR_CATALOG.map((c) => ({ ...c }));
}

/** Chart-style metadata for the selector (spec §5). */
export interface ChartStyleMeta {
  id: "candles" | "volume-candles" | "line";
  label: string;
  hint: string;
}

export const CHART_STYLES: ChartStyleMeta[] = [
  { id: "candles", label: "Candlestick", hint: "OHLC candlesticks" },
  { id: "volume-candles", label: "Volume Candles", hint: "Candlesticks with the volume histogram underneath" },
  { id: "line", label: "Line", hint: "Closing price line" },
];

/** An indicator belongs to the volume pane only when it *is* volume. */
export function isOverlayIndicator(type: IndicatorType): boolean {
  return type === "SMA" || type === "EMA" || type === "VWAP" || type === "BB";
}

/** Phase 11 — oscillators that render in their own sub-pane. */
export const SUB_PANE_TYPES: readonly IndicatorType[] = ["RSI", "MACD", "STOCH", "ATR"];

export function paneForIndicator(type: IndicatorType): "main" | "sub" {
  return SUB_PANE_TYPES.includes(type) ? "sub" : "main";
}

/** Intraday ranges (1D / 7D) are the only ones where VWAP is meaningful. */
export function isIntradayRange(range: StockRange): boolean {
  return rangeWindow(range).intraday;
}

export function createChartInstance(
  id: string,
  symbol: string,
  entityType: ChartInstance["entityType"] = "STOCK",
  timeframe: StockRange = "6M"
): ChartInstance {
  return {
    id,
    symbol: symbol.trim().toUpperCase(),
    entityType,
    timeframe,
    chartType: "volume-candles",
    indicators: defaultIndicators(),
    drawings: [],
    priceLevels: [],
    viewport: null,
    volumeVisible: true,
    crosshairEnabled: true,
    settings: { ...DEFAULT_SETTINGS },
  };
}

/**
 * Human label for a panel id. The two fixed panels and the single-letter grid
 * panels (chart-c …) get names; anything else (a Phase-12 widget id) passes
 * through untouched rather than being mangled.
 */
export function chartLabel(id: string): string {
  const known: Record<string, string> = { "chart-a": "Chart A", "chart-b": "Chart B" };
  if (known[id]) return known[id];
  const single = /^chart-([a-z])$/.exec(id);
  return single ? `Chart ${single[1].toUpperCase()}` : id;
}

/**
 * Phase 11 — extra grid panels the user can open. The two seed panels occupy
 * `chart-a`/`chart-b`, so new panels continue the alphabet; the cap keeps a
 * single-page grid from turning into an unbounded canvas.
 */
export const GRID_PANEL_LETTERS = ["c", "d", "e", "f"] as const;
export const MAX_GRID_PANELS = CHART_IDS.length + GRID_PANEL_LETTERS.length;

/**
 * The id a new grid panel should take, or `null` when the cap is reached.
 * Deterministic and gap-filling: closing `chart-c` frees that id for reuse, so
 * a workspace never accumulates `chart-c`/`chart-c-2`-style aliases.
 */
export function nextPanelId(existing: readonly { id: string }[]): string | null {
  const used = new Set(existing.map((c) => c.id));
  for (const letter of GRID_PANEL_LETTERS) {
    const id = `chart-${letter}`;
    if (!used.has(id)) return id;
  }
  return null;
}

/** In-memory only: the workspace opens on a recognisable PSX ticker. */
export const DEFAULT_SYMBOL = "OGDC";
export const DEFAULT_INDEX_SYMBOL = "KSE100";

/**
 * Identity of a dataset *shape*: symbol + timeframe + the exact bar window.
 *
 * A persisted viewport is only re-applied when this key still matches, so a
 * stale zoom captured for another symbol/timeframe can never distort a chart —
 * the panel simply re-fits instead.
 */
export function datasetFitKey(
  symbol: string,
  timeframe: StockRange,
  points: readonly { timestamp: number }[]
): string {
  const first = points[0]?.timestamp ?? 0;
  const last = points[points.length - 1]?.timestamp ?? 0;
  return `${symbol.toUpperCase()}|${timeframe}|${points.length}|${first}|${last}`;
}

/** Suggested symbols shown when a symbol is unknown (spec §29). */
export const TIMEFRAME_OPTIONS: StockRange[] = STOCK_RANGES;
