/**
 * Phase 11 — technical indicator calculation engine (spec §8–§13).
 *
 * Pure functions only: no React, no DOM, no fetching. `computeIndicators` turns
 * a candle series + the user's indicator configs into lightweight series that a
 * chart can plot directly (`lines`) plus an honest list of what could not be
 * computed and why (`unavailable`).
 *
 * Results are memoized by dataset key + config signature so re-renders, mouse
 * movement, chart-style switches and the second split panel never trigger a
 * recalculation (spec §9, §27).
 */
import type { Candle, IndicatorConfig } from "./types";
import { rollingMean, rollingStdev, stdev } from "./math";

/** A single plottable indicator line, aligned 1:1 with the candle array. */
export interface IndicatorLine {
  /** Stable key, unique within one compute call. */
  key: string;
  /** Legend label, e.g. `SMA 20`. */
  label: string;
  /** Parent indicator id, e.g. `SMA:20`. */
  indicatorId: string;
  role: "main" | "middle" | "band" | "signal" | "hist";
  /** Phase 11 — which pane this line draws in (defaults to the price pane). */
  pane?: "main" | "sub";
  color: string;
  width: number;
  dash: "solid" | "dash" | "dot";
  /** `null` where the indicator legitimately has no value yet. */
  values: (number | null)[];
}

/** An indicator the user asked for that the current dataset cannot support. */
export interface IndicatorUnavailable {
  indicatorId: string;
  label: string;
  reason: string;
}

export interface IndicatorComputeResult {
  lines: IndicatorLine[];
  unavailable: IndicatorUnavailable[];
}

export interface BollingerBands {
  middle: (number | null)[];
  upper: (number | null)[];
  lower: (number | null)[];
}

/** Simple moving average. `SMA = Σ close / period` (spec §10). */
export function calculateSMA(values: readonly number[], period: number): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return new Array(values.length).fill(null);
  return rollingMean(values, Math.floor(period));
}

/**
 * Exponential moving average with the standard smoothing factor
 * `k = 2 / (period + 1)`, seeded by the SMA of the first `period` observations
 * so values before the window is complete stay `null` (spec §11).
 */
export function calculateEMA(values: readonly number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  const p = Math.floor(period);
  if (!Number.isFinite(period) || p < 1 || values.length < p) return out;

  const k = 2 / (p + 1);
  let seed = 0;
  for (let i = 0; i < p; i++) seed += values[i];
  let ema = seed / p;
  out[p - 1] = ema;
  for (let i = p; i < values.length; i++) {
    ema = values[i] * k + ema * (1 - k);
    out[i] = ema;
  }
  return out;
}

/**
 * Volume-weighted average price using the typical price `(H + L + C) / 3`.
 *
 * VWAP is a cumulative intraday measure: it resets each session. It is only
 * meaningful when the dataset really carries intraday bars *and* real volume, so
 * this returns nulls (the caller then reports "unavailable") rather than
 * inventing a number from daily closes (spec §12).
 */
export function calculateVWAP(candles: readonly Candle[]): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null);
  let cumulativePV = 0;
  let cumulativeVolume = 0;
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const typical = (c.high + c.low + c.close) / 3;
    const volume = c.hasVolume ? c.volume : 0;
    if (volume <= 0) {
      // No tradeable volume for this bar: hold the running VWAP (no fabrication).
      out[i] = cumulativeVolume > 0 ? cumulativePV / cumulativeVolume : null;
      continue;
    }
    cumulativePV += typical * volume;
    cumulativeVolume += volume;
    out[i] = cumulativePV / cumulativeVolume;
  }
  return cumulativeVolume > 0 ? out : new Array(candles.length).fill(null);
}

/** Bollinger Bands: SMA middle band ± `multiplier` rolling standard deviations. */
export function calculateBollingerBands(
  values: readonly number[],
  period: number,
  multiplier = 2
): BollingerBands {
  const p = Math.floor(period);
  const middle = calculateSMA(values, p);
  const deviation = rollingStdev(values, p);
  const upper: (number | null)[] = new Array(values.length).fill(null);
  const lower: (number | null)[] = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    const m = middle[i];
    const sd = deviation[i];
    if (m === null || sd === null) continue;
    upper[i] = m + multiplier * sd;
    lower[i] = m - multiplier * sd;
  }
  return { middle, upper, lower };
}

/**
 * Wilder's Relative Strength Index.
 *
 * Uses Wilder's smoothing (an EMA with `α = 1/period`) seeded by the simple
 * average of the first `period` gains/losses, so the first value lands at index
 * `period` — matching every charting platform's convention.
 */
export function calculateRSI(values: readonly number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  const p = Math.floor(period);
  if (!Number.isFinite(period) || p < 1 || values.length <= p) return out;

  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= p; i++) {
    const change = values[i] - values[i - 1];
    if (change >= 0) gain += change;
    else loss -= change;
  }
  let avgGain = gain / p;
  let avgLoss = loss / p;
  out[p] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = p + 1; i < values.length; i++) {
    const change = values[i] - values[i - 1];
    avgGain = (avgGain * (p - 1) + (change > 0 ? change : 0)) / p;
    avgLoss = (avgLoss * (p - 1) + (change < 0 ? -change : 0)) / p;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

export interface MACDResult {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
}

/** MACD: EMA(fast) − EMA(slow), with an EMA(signal) of that line plus its histogram. */
export function calculateMACD(
  values: readonly number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9
): MACDResult {
  const fastEma = calculateEMA(values, fast);
  const slowEma = calculateEMA(values, slow);
  const macd: (number | null)[] = values.map((_value, index) => {
    const f = fastEma[index];
    const s = slowEma[index];
    return f === null || s === null ? null : f - s;
  });

  const signal: (number | null)[] = new Array(values.length).fill(null);
  const histogram: (number | null)[] = new Array(values.length).fill(null);
  const firstIndex = macd.findIndex((value) => value !== null);
  if (firstIndex >= 0) {
    // The signal line is an EMA over the MACD's defined region only, so its
    // warm-up is measured from where MACD itself becomes defined.
    const compact = macd.slice(firstIndex) as number[];
    const signalCompact = calculateEMA(compact, signalPeriod);
    for (let i = 0; i < compact.length; i++) {
      const value = signalCompact[i];
      signal[firstIndex + i] = value;
      if (value !== null) histogram[firstIndex + i] = compact[i] - value;
    }
  }
  return { macd, signal, histogram };
}

export interface StochasticResult {
  k: (number | null)[];
  d: (number | null)[];
}

/**
 * Stochastic oscillator: %K = (close − lowₙ) / (highₙ − lowₙ) × 100, and %D a
 * simple moving average of %K. A zero-width range (limit-locked bar) yields a
 * neutral 50 rather than a divide-by-zero.
 */
export function calculateStochastic(
  candles: readonly Candle[],
  kPeriod = 14,
  dPeriod = 3
): StochasticResult {
  const k: (number | null)[] = new Array(candles.length).fill(null);
  const p = Math.floor(kPeriod);
  if (!Number.isFinite(kPeriod) || p < 1) return { k, d: new Array(candles.length).fill(null) };

  for (let i = p - 1; i < candles.length; i++) {
    let highest = -Infinity;
    let lowest = Infinity;
    for (let j = i - p + 1; j <= i; j++) {
      if (candles[j].high > highest) highest = candles[j].high;
      if (candles[j].low < lowest) lowest = candles[j].low;
    }
    const range = highest - lowest;
    k[i] = range === 0 ? 50 : ((candles[i].close - lowest) / range) * 100;
  }

  const d: (number | null)[] = new Array(candles.length).fill(null);
  const firstIndex = k.findIndex((value) => value !== null);
  if (firstIndex >= 0) {
    const compact = k.slice(firstIndex) as number[];
    const smoothed = rollingMean(compact, Math.max(1, Math.floor(dPeriod)));
    for (let i = 0; i < compact.length; i++) d[firstIndex + i] = smoothed[i];
  }
  return { k, d };
}

/**
 * Average True Range (Wilder). True range accounts for gaps against the prior
 * close, which a bare high−low window misses.
 */
export function calculateATR(candles: readonly Candle[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null);
  const p = Math.floor(period);
  if (!Number.isFinite(period) || p < 1 || candles.length <= p) return out;

  const trueRange = candles.map((candle, index) => {
    if (index === 0) return candle.high - candle.low;
    const previousClose = candles[index - 1].close;
    return Math.max(
      candle.high - candle.low,
      Math.abs(candle.high - previousClose),
      Math.abs(candle.low - previousClose)
    );
  });

  let sum = 0;
  for (let i = 1; i <= p; i++) sum += trueRange[i];
  let atr = sum / p;
  out[p] = atr;
  for (let i = p + 1; i < candles.length; i++) {
    atr = (atr * (p - 1) + trueRange[i]) / p;
    out[i] = atr;
  }
  return out;
}

/** Indicator label used across the legend, toggles and hover readout. */
export function indicatorLabel(
  config: Pick<IndicatorConfig, "type" | "period" | "stdDev" | "fastPeriod" | "slowPeriod" | "signalPeriod">
): string {
  switch (config.type) {
    case "SMA":
      return `SMA ${config.period}`;
    case "EMA":
      return `EMA ${config.period}`;
    case "VWAP":
      return "VWAP";
    case "BB":
      return `BB ${config.period} / ${config.stdDev ?? 2}`;
    case "RSI":
      return `RSI ${config.period}`;
    case "MACD":
      return `MACD ${config.fastPeriod ?? 12} / ${config.slowPeriod ?? 26} / ${config.signalPeriod ?? 9}`;
    case "STOCH":
      return `Stoch ${config.period} / ${config.signalPeriod ?? 3}`;
    case "ATR":
      return `ATR ${config.period}`;
    default:
      return config.type;
  }
}

export const VWAP_UNAVAILABLE_REASON = "VWAP unavailable for this dataset";

// ---------------------------------------------------------------------------
// Compute + memoize
// ---------------------------------------------------------------------------

export interface ComputeIndicatorOptions {
  /** True when the dataset is intraday (1D / 7D) — required for VWAP. */
  intraday: boolean;
  /** Stable dataset identity (symbol + timeframe) used as the cache key. */
  datasetKey?: string;
}

function configSignature(configs: readonly IndicatorConfig[]): string {
  return configs
    .filter((c) => c.enabled)
    .map((c) => `${c.id}:${c.period}:${c.stdDev ?? 2}:${c.fastPeriod ?? 12}:${c.slowPeriod ?? 26}:${c.signalPeriod ?? 9}:${c.color}:${c.lineWidth}`)
    .join("|");
}

function computeIndicatorsUncached(
  candles: readonly Candle[],
  configs: readonly IndicatorConfig[],
  options: ComputeIndicatorOptions
): IndicatorComputeResult {
  const closes = candles.map((c) => c.close);
  const lines: IndicatorLine[] = [];
  const unavailable: IndicatorUnavailable[] = [];

  for (const config of configs) {
    if (!config.enabled) continue;
    const label = indicatorLabel(config);

    if (config.type === "SMA") {
      lines.push({
        key: `${config.id}:line`,
        label,
        indicatorId: config.id,
        role: "main",
        color: config.color,
        width: config.lineWidth,
        dash: "solid",
        values: calculateSMA(closes, config.period),
      });
      continue;
    }

    if (config.type === "EMA") {
      lines.push({
        key: `${config.id}:line`,
        label,
        indicatorId: config.id,
        role: "main",
        color: config.color,
        width: config.lineWidth,
        dash: "solid",
        values: calculateEMA(closes, config.period),
      });
      continue;
    }

    if (config.type === "VWAP") {
      if (!options.intraday) {
        unavailable.push({ indicatorId: config.id, label, reason: VWAP_UNAVAILABLE_REASON });
        continue;
      }
      if (!candles.some((c) => c.hasVolume && c.volume > 0)) {
        unavailable.push({ indicatorId: config.id, label, reason: "VWAP needs volume data, which this series has none of" });
        continue;
      }
      const values = calculateVWAP(candles);
      if (values.every((v) => v === null)) {
        unavailable.push({ indicatorId: config.id, label, reason: VWAP_UNAVAILABLE_REASON });
        continue;
      }
      lines.push({
        key: `${config.id}:line`,
        label,
        indicatorId: config.id,
        role: "main",
        color: config.color,
        width: config.lineWidth,
        dash: "dot",
        values,
      });
      continue;
    }

    // Bollinger Bands — three lines derived from the same window.
    const bands = calculateBollingerBands(closes, config.period, config.stdDev ?? 2);
    lines.push(
      {
        key: `${config.id}:upper`,
        label: `${label} upper`,
        indicatorId: config.id,
        role: "band",
        color: config.color,
        width: Math.max(1, config.lineWidth - 0.5),
        dash: "dash",
        values: bands.upper,
      },
      {
        key: `${config.id}:middle`,
        label: `${label} mid`,
        indicatorId: config.id,
        role: "middle",
        color: config.color,
        width: Math.max(1, config.lineWidth - 0.5),
        dash: "dot",
        values: bands.middle,
      },
      {
        key: `${config.id}:lower`,
        label: `${label} lower`,
        indicatorId: config.id,
        role: "band",
        color: config.color,
        width: Math.max(1, config.lineWidth - 0.5),
        dash: "dash",
        values: bands.lower,
      }
    );
    continue;
  }

  for (const config of configs) {
    if (!config.enabled) continue;
    const label = indicatorLabel(config);

    if (config.type === "RSI") {
      lines.push({
        key: `${config.id}:line`,
        label,
        indicatorId: config.id,
        role: "main",
        pane: "sub",
        color: config.color,
        width: config.lineWidth,
        dash: "solid",
        values: calculateRSI(closes, config.period),
      });
      continue;
    }

    if (config.type === "MACD") {
      const macd = calculateMACD(closes, config.fastPeriod ?? 12, config.slowPeriod ?? 26, config.signalPeriod ?? 9);
      lines.push(
        {
          key: `${config.id}:macd`,
          label: `${label} line`,
          indicatorId: config.id,
          role: "main",
          pane: "sub",
          color: config.color,
          width: config.lineWidth,
          dash: "solid",
          values: macd.macd,
        },
        {
          key: `${config.id}:signal`,
          label: `${label} signal`,
          indicatorId: config.id,
          role: "signal",
          pane: "sub",
          color: "#DE9255",
          width: Math.max(1, config.lineWidth - 0.4),
          dash: "dot",
          values: macd.signal,
        },
        {
          key: `${config.id}:hist`,
          label: `${label} histogram`,
          indicatorId: config.id,
          role: "hist",
          pane: "sub",
          color: "#9daed9",
          width: Math.max(1, config.lineWidth - 0.6),
          dash: "solid",
          values: macd.histogram,
        }
      );
      continue;
    }

    if (config.type === "STOCH") {
      const stochastic = calculateStochastic(candles, config.period, config.signalPeriod ?? 3);
      lines.push(
        {
          key: `${config.id}:k`,
          label: `${label} %K`,
          indicatorId: config.id,
          role: "main",
          pane: "sub",
          color: config.color,
          width: config.lineWidth,
          dash: "solid",
          values: stochastic.k,
        },
        {
          key: `${config.id}:d`,
          label: `${label} %D`,
          indicatorId: config.id,
          role: "signal",
          pane: "sub",
          color: "#DE9255",
          width: Math.max(1, config.lineWidth - 0.4),
          dash: "dot",
          values: stochastic.d,
        }
      );
      continue;
    }

    if (config.type === "ATR") {
      if (!candles.some((candle) => candle.hasVolume)) {
        // ATR itself does not need volume, but a dataset this thin is usually
        // a placeholder series; report it rather than plotting noise.
        unavailable.push({
          indicatorId: config.id,
          label,
          reason: "ATR needs real OHLC bars, which this series does not have",
        });
        continue;
      }
      lines.push({
        key: `${config.id}:line`,
        label,
        indicatorId: config.id,
        role: "main",
        pane: "sub",
        color: config.color,
        width: config.lineWidth,
        dash: "solid",
        values: calculateATR(candles, config.period),
      });
      continue;
    }
  }

  return { lines, unavailable };
}

/** Bounded cache so a long session cannot grow memory without limit. */
const CACHE_LIMIT = 48;
const cache = new Map<string, IndicatorComputeResult>();

/**
 * Compute every enabled indicator for a dataset.
 *
 * Memoized on `datasetKey + enabled config signature`, so hovering, panning and
 * even re-mounting a panel all reuse the previous result (spec §27).
 */
export function computeIndicators(
  candles: readonly Candle[],
  configs: readonly IndicatorConfig[],
  options: ComputeIndicatorOptions
): IndicatorComputeResult {
  const key = `${options.datasetKey ?? "ds"}|${candles.length}|${candles[0]?.timestamp ?? 0}|${
    candles[candles.length - 1]?.timestamp ?? 0
  }|${options.intraday ? "i" : "d"}|${configSignature(configs)}`;

  const hit = cache.get(key);
  if (hit) return hit;

  const result = computeIndicatorsUncached(candles, configs, options);

  if (cache.size >= CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, result);
  return result;
}

/** Value of a line at one bar index (null when out of range / not yet defined). */
export function lineValueAt(line: IndicatorLine, index: number): number | null {
  if (index < 0 || index >= line.values.length) return null;
  return line.values[index];
}

/**
 * Aggregate one indicator's lines into a single representative reading for the
 * legend when it is drawn as a band (Bollinger shows mid/upper/lower).
 */
export function legendValuesAt(
  lines: readonly IndicatorLine[],
  index: number
): { indicatorId: string; label: string; color: string; values: { label: string; value: number | null }[] }[] {
  const grouped = new Map<string, { indicatorId: string; label: string; color: string; values: { label: string; value: number | null }[] }>();
  for (const line of lines) {
    const entry =
      grouped.get(line.indicatorId) ??
      { indicatorId: line.indicatorId, label: line.label.replace(/ (upper|mid|lower)$/, ""), color: line.color, values: [] };
    entry.values.push({ label: line.role === "main" ? "value" : line.role, value: lineValueAt(line, index) });
    grouped.set(line.indicatorId, entry);
  }
  return Array.from(grouped.values());
}

/** Test/inspection helper: expose the raw statistical primitives. */
export { rollingMean, rollingStdev, stdev };
