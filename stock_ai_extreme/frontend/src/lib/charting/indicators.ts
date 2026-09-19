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
  role: "main" | "middle" | "band";
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

/** Indicator label used across the legend, toggles and hover readout. */
export function indicatorLabel(config: Pick<IndicatorConfig, "type" | "period" | "stdDev">): string {
  switch (config.type) {
    case "SMA":
      return `SMA ${config.period}`;
    case "EMA":
      return `EMA ${config.period}`;
    case "VWAP":
      return "VWAP";
    case "BB":
      return `BB ${config.period} / ${config.stdDev ?? 2}`;
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
    .map((c) => `${c.id}:${c.period}:${c.stdDev ?? 2}:${c.color}:${c.lineWidth}`)
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
