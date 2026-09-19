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
