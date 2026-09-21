/**
 * Phase 11 — Professional charting & technical-analysis engine: shared models.
 *
 * Everything the chart workspace renders is described by the types in this
 * file. They are deliberately transport-agnostic and serializable so the whole
 * workspace (instances, indicators, drawings, price levels) can be persisted by
 * the existing zustand-persist architecture and round-tripped through undo/redo
 * without touching React.
 *
 * Coordinate system
 * -----------------
 * Drawings are stored in **data space**, never in screen pixels:
 *
 *   t = time-axis value (epoch ms; fractional values are allowed so a point can
 *       sit between two bars)
 *   p = price
 *
 * `lib/charting/geometry.ts` is the only module allowed to convert between data
 * space and pixels, so zooming / resizing / switching timeframe can never break
 * a drawing's meaning (spec §16, §21).
 */
import type { StockRange } from "../timeframes";

/** What a chart is plotting — drives which market-data provider is used. */
export type EntityType = "STOCK" | "INDEX";

/**
 * Chart render styles (spec §5).
 *  - `candles`        OHLC candlesticks
 *  - `volume-candles` candlesticks with the volume histogram under the price
 *  - `line`           closing-price line
 */
export type ChartStyle = "candles" | "volume-candles" | "line";

/**
 * Indicator families supported by the calculation engine (spec §8).
 *
 * Phase 11 additions: RSI, MACD, Stochastic and ATR. These are oscillators and
 * render in their own sub-pane rather than over the price.
 */
export type IndicatorType = "SMA" | "EMA" | "VWAP" | "BB" | "RSI" | "MACD" | "STOCH" | "ATR";

/** Indicator families that belong in a separate sub-pane below the price. */
export const SUB_PANE_INDICATORS: readonly IndicatorType[] = ["RSI", "MACD", "STOCH", "ATR"];

export function isSubPaneIndicator(type: IndicatorType): boolean {
  return SUB_PANE_INDICATORS.includes(type);
}

/**
 * One configurable indicator overlay.
 *
 * `id` is a stable, human-readable key (e.g. `SMA:20`) so persisted drawings and
 * user preferences survive reloads and future additions of new indicators.
 */
export interface IndicatorConfig {
  id: string;
  type: IndicatorType;
  enabled: boolean;
  /** Look-back window. Ignored by VWAP (it is cumulative by definition). */
  period: number;
  /** Standard-deviation multiplier — Bollinger Bands only. */
  stdDev?: number;
  color: string;
  lineWidth: number;
  /** Allow the user to retune the period / multiplier from the UI. */
  configurable?: boolean;
  /**
   * Phase 11 — where the indicator draws. Overlays default to `main`; the
   * oscillators default to `sub` and get their own pane regardless of this
   * hint, so a stale persisted value can never misplace them.
   */
  pane?: "main" | "sub";
  /** Fast EMA period — MACD only. */
  fastPeriod?: number;
  /** Slow EMA period — MACD only. */
  slowPeriod?: number;
  /** Signal period — MACD and Stochastic only. */
  signalPeriod?: number;
}

/**
 * A single normalized OHLCV observation.
 *
 * `timestamp` is epoch milliseconds (timezone-independent storage); `hasVolume`
 * records whether the provider actually supplied volume — a missing volume is
 * rendered as zero and surfaced in the UI, never fabricated (spec §6).
 */
export interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  hasVolume: boolean;
}

/** Alias kept for readability in the indicator/geometry modules. */
export type OHLCVPoint = Candle;

/**
 * Persisted zoom window (`xRange` in epoch ms, `yRange` in price).
 *
 * `fitKey` ties the window to the exact dataset it was captured for, so a stale
 * window can never be re-applied to a different symbol/timeframe — the chart
 * simply re-fits instead.
 */
export interface Viewport {
  xRange: [number, number];
  yRange: [number, number];
  fitKey: string;
}

/** A data-space point: time-axis value (epoch ms) + price. */
export interface Point2D {
  t: number;
  p: number;
}

/**
 * Interactive drawing primitives (spec §15).
 *
 * Phase 11 additions: Fibonacci retracement/extension, ray, horizontal and
 * vertical lines, parallel channel, and the measurement tool. The five original
 * primitives are unchanged, so existing persisted drawings keep working.
 */
export type DrawingType =
  | "trendline"
  | "rectangle"
  | "circle"
  | "parabola"
  | "semicircle"
  | "fib-retracement"
  | "fib-extension"
  | "ray"
  | "hline"
  | "vline"
  | "channel"
  | "measure";

/** One derived Fibonacci level for a two-anchor retracement/extension. */
export interface FibonacciLevel {
  ratio: number;
  /** Data-space price of this level. */
  price: number;
  /** Display label, e.g. `61.8%`. */
  label: string;
}

/** Measurement result between two data-space anchors. */
export interface MeasurementResult {
  priceChange: number;
  percentChange: number;
  /** Number of bars spanned (when a bar spacing is known). */
  bars: number | null;
  durationMs: number;
}

/** Toolbar selection: `select` manipulates existing shapes, others create. */
export type DrawingTool = "select" | DrawingType;

export interface DrawingStyle {
  color: string;
  width: number;
  dash: "solid" | "dash" | "dot";
  /** 0–0.6 wash used inside closed shapes. */
  fillOpacity: number;
}

/**
 * A persisted, interactive chart drawing (spec §16).
 * Every supported primitive is defined by two anchor points in data space.
 */
export interface DrawingShape {
  id: string;
  type: DrawingType;
  coordinates: Point2D[];
  style: DrawingStyle;
  visible: boolean;
  locked: boolean;
}

/** Analyst price levels (spec §20). */
export type PriceLevelType = "SUPPORT" | "RESISTANCE" | "ENTRY" | "STOP_LOSS" | "TARGET";

/**
 * A horizontal price annotation. Only the *price* is stored — the pixel position
 * is always derived, so the line stays glued to its level through zoom, resize,
 * timeframe changes and viewport moves (spec §21).
 */
export interface PriceLevel {
  id: string;
  type: PriceLevelType;
  price: number;
  label: string;
  visible: boolean;
  locked: boolean;
}

/** Per-chart display preferences exposed by the toolbar's Settings menu. */
export interface ChartSettings {
  grid: boolean;
  lastPriceLine: boolean;
  legend: boolean;
  /** Log-ish vertical padding for the auto-fit, keeps long uptrends readable. */
  paddedFit: boolean;
}

/** Undo/redo snapshot — the analyst-owned, mutable part of a chart. */
export interface ChartSnapshot {
  drawings: DrawingShape[];
  priceLevels: PriceLevel[];
}

/**
 * One independent chart panel (spec §4).
 * Chart A and Chart B each own an instance; mutating one never touches the other.
 */
export interface ChartInstance {
  id: string;
  symbol: string;
  entityType: EntityType;
  timeframe: StockRange;
  chartType: ChartStyle;
  indicators: IndicatorConfig[];
  drawings: DrawingShape[];
  priceLevels: PriceLevel[];
  viewport: Viewport | null;
  volumeVisible: boolean;
  crosshairEnabled: boolean;
  settings: ChartSettings;
}

/**
 * Workspace layout (spec §3).
 *
 *   single  only the active panel is on screen
 *   split   every open panel, stacked in one column (A above B, and so on)
 *   grid    every open panel in a multi-column grid
 *
 * `single`/`split` keep their original meaning for the two seed panels, so a
 * workspace saved before the grid existed restores exactly as it was.
 */
export type ChartLayout = "single" | "split" | "grid";

/** How many columns the grid layout uses (clamped by the store). */
export const GRID_COLUMN_OPTIONS = [1, 2, 3] as const;
export type GridColumns = (typeof GRID_COLUMN_OPTIONS)[number];

/** Normalized OHLCV payload plus an honest account of what was repaired. */
export interface NormalizedDataset {
  points: Candle[];
  stats: {
    received: number;
    kept: number;
    rejected: number;
    duplicates: number;
    outOfOrder: number;
    repaired: number;
    missingVolume: number;
  };
}
