/**
 * Phase 11 — OHLCV normalization (spec §6).
 *
 * Every candle that reaches a chart passes through `normalizeOHLCV`. The goal is
 * that chart geometry can never be broken by provider quirks, while still being
 * fully honest about what happened:
 *
 *   - malformed rows (non-numeric / non-positive prices, bad timestamps) are
 *     **rejected** and counted;
 *   - duplicate timestamps keep the **last** (most recent) print and are counted;
 *   - out-of-order rows are re-sorted ascending and counted;
 *   - OHLC relationships that contradict each other (e.g. `high < low`) are
 *     clamped into a coherent candle and counted — nothing is invented, only
 *     repaired;
 *   - a missing volume becomes `0` with `hasVolume: false` so the UI can say so
 *     instead of implying "zero traded".
 *
 * Missing candles (gaps in a calendar) are intentionally **not** fabricated.
 */
import type { Candle, NormalizedDataset } from "./types";
import { toFiniteNumber } from "./math";

/** Loosely-typed provider row — the input boundary of the engine. */
export interface RawCandle {
  timestamp?: unknown;
  time?: unknown;
  date?: unknown;
  open?: unknown;
  high?: unknown;
  low?: unknown;
  close?: unknown;
  volume?: unknown;
}

export interface NormalizeOptions {
  /**
   * When false, an incoherent OHLC row is rejected instead of repaired.
   * Defaults to true (repair) because a single bad provider tick should not
   * punch a hole in an otherwise valid series.
   */
  repair?: boolean;
}

/**
 * Parse a timestamp from epoch ms/s, an ISO string, or the PSX provider's
 * `"YYYY-MM-DD"` / `"YYYY-MM-DD HH:mm"` formats.
 *
 * Returns epoch milliseconds, or null when the value cannot be trusted.
 */
export function parseTimestamp(value: unknown): number | null {
  if (value instanceof Date) {
    const t = value.getTime();
    return Number.isFinite(t) ? t : null;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    // Accept seconds-since-epoch as well as milliseconds.
    return value > 0 && value < 1e11 ? Math.round(value * 1000) : Math.round(value);
  }
  if (typeof value === "string") {
    const raw = value.trim();
    if (!raw) return null;
    // Bare calendar days are parsed as UTC so the same row always maps to the
    // same instant regardless of the viewer's timezone.
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      const t = Date.parse(`${raw}T00:00:00Z`);
      return Number.isFinite(t) ? t : null;
    }
    // "YYYY-MM-DD HH:mm[:ss]" → ISO-ish (space separator is not portable).
    const t = Date.parse(raw.includes(" ") ? raw.replace(" ", "T") : raw);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

function pickTimestamp(row: RawCandle): number | null {
  return (
    parseTimestamp(row.timestamp) ??
    parseTimestamp(row.time) ??
    parseTimestamp(row.date) ??
    null
  );
}

/**
 * Normalize an arbitrary stream of provider rows into a clean, chronological,
 * gap-free-of-duplicates candle series.
 */
export function normalizeOHLCV(rows: readonly RawCandle[], options: NormalizeOptions = {}): NormalizedDataset {
  const repair = options.repair ?? true;
  const stats = {
    received: rows.length,
    kept: 0,
    rejected: 0,
    duplicates: 0,
    outOfOrder: 0,
    repaired: 0,
    missingVolume: 0,
  };

  // Keyed by timestamp so duplicates collapse in a single pass (last wins).
  const byTime = new Map<number, Candle>();
  let lastAcceptedTimestamp: number | null = null;

  for (const row of rows) {
    const timestamp = pickTimestamp(row);
    const open = toFiniteNumber(row.open);
    const high = toFiniteNumber(row.high);
    const low = toFiniteNumber(row.low);
    const close = toFiniteNumber(row.close);

    if (timestamp === null || open === null || high === null || low === null || close === null) {
      stats.rejected++;
      continue;
    }
    // Non-positive prices are meaningless for equity charts (and break log axes).
    if (open <= 0 || high <= 0 || low <= 0 || close <= 0) {
      stats.rejected++;
      continue;
    }

    let o = open;
    let h = high;
    let l = low;
    let c = close;

    const coherent = h >= l && h >= Math.max(o, c) && l <= Math.min(o, c);
    if (!coherent) {
      if (!repair) {
        stats.rejected++;
        continue;
      }
      h = Math.max(h, o, c, l);
      l = Math.min(l, o, c, h);
      stats.repaired++;
    }

    const rawVolume = toFiniteNumber(row.volume);
    const hasVolume = rawVolume !== null;
    if (!hasVolume) stats.missingVolume++;
    const volume = hasVolume ? Math.max(0, rawVolume) : 0;

    if (byTime.has(timestamp)) stats.duplicates++;
    if (lastAcceptedTimestamp !== null && timestamp < lastAcceptedTimestamp) stats.outOfOrder++;
    lastAcceptedTimestamp = timestamp;

    byTime.set(timestamp, { timestamp, open: o, high: h, low: l, close: c, volume, hasVolume });
  }

  const points = Array.from(byTime.values()).sort((a, b) => a.timestamp - b.timestamp);
  stats.kept = points.length;
  return { points, stats };
}

/**
 * Map the FastAPI history response (`date, Open, High, Low, Close, Volume`) onto
 * raw candles. Kept here so pages never hand-roll field aliases.
 */
export function historyRowsToRaw(rows: readonly Record<string, unknown>[]): RawCandle[] {
  return rows.map((r) => ({
    timestamp: r.date ?? r.time ?? r.timestamp,
    open: r.Open ?? r.open,
    high: r.High ?? r.high,
    low: r.Low ?? r.low,
    close: r.Close ?? r.close,
    volume: r.Volume ?? r.volume,
  }));
}

/** Map the deterministic PSX index series onto raw candles. */
export function psxPointsToRaw(
  points: readonly { time: string; open: number; high: number; low: number; close: number; volume: number }[]
): RawCandle[] {
  return points.map((p) => ({
    timestamp: p.time,
    open: p.open,
    high: p.high,
    low: p.low,
    close: p.close,
    volume: p.volume,
  }));
}

/** First/last timestamp of a series — handy for axis labels and cache keys. */
export function seriesSpan(points: readonly Candle[]): { first: number; last: number } | null {
  if (points.length === 0) return null;
  return { first: points[0].timestamp, last: points[points.length - 1].timestamp };
}
