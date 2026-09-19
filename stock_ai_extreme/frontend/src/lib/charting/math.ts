/**
 * Phase 11 — reusable mathematical primitives for the indicator engine.
 *
 * Kept deliberately small and dependency-free: every indicator in
 * `indicators.ts` is expressed with these helpers so the maths lives in one
 * place and is directly unit-testable (spec §13).
 */

/** Arithmetic mean. Returns NaN for an empty window, never 0 (`0` would lie). */
export function mean(values: readonly number[]): number {
  if (values.length === 0) return NaN;
  let sum = 0;
  for (let i = 0; i < values.length; i++) sum += values[i];
  return sum / values.length;
}

/**
 * Standard deviation over `values`.
 *
 * `sample = false` (default) uses the population formula (÷ n) — the convention
 * used by Bollinger Bands; `sample = true` uses Bessel's correction (÷ n−1).
 */
export function stdev(values: readonly number[], sample = false): number {
  const n = values.length;
  if (n === 0) return NaN;
  if (n === 1) return 0;
  const m = mean(values);
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const d = values[i] - m;
    acc += d * d;
  }
  return Math.sqrt(acc / (sample ? n - 1 : n));
}

/**
 * Rolling mean aligned to the input array.
 *
 * Index `period - 1` holds the first complete window; earlier indices are `null`
 * so a chart never draws an indicator that does not yet have enough
 * observations (spec §10, §11).
 */
export function rollingMean(values: readonly number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/** Rolling population standard deviation aligned to the input array. */
export function rollingStdev(values: readonly number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    sum += v;
    sumSq += v * v;
    if (i >= period) {
      const out0 = values[i - period];
      sum -= out0;
      sumSq -= out0 * out0;
    }
    if (i >= period - 1) {
      const m = sum / period;
      // max(0, …) guards against tiny negative values from float rounding.
      out[i] = Math.sqrt(Math.max(0, sumSq / period - m * m));
    }
  }
  return out;
}

export function clamp(value: number, lo: number, hi: number): number {
  return value < lo ? lo : value > hi ? hi : value;
}

/** Linear interpolation: `t = 0` → a, `t = 1` → b. */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/**
 * Inverse linear interpolation: where does `v` sit between lo and hi?
 * Returns 0.5 for a zero-width span so callers never divide by zero.
 */
export function unlerp(lo: number, hi: number, v: number): number {
  if (hi === lo) return 0.5;
  return (v - lo) / (hi - lo);
}

/** Numeric guard used throughout the data pipeline. */
export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Coerce unknown input (string numbers included) to a finite number or null. */
export function toFiniteNumber(v: unknown): number | null {
  if (isFiniteNumber(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}
