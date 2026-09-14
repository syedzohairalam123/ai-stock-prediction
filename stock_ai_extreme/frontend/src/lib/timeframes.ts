/**
 * Stock chart timeframes (Phase 5).
 *
 * Maps each UI range to the exact API window (start/end + bar interval) so the
 * chart, the stat strip and any deep-link all agree on one definition. Intraday
 * ranges ask for minute bars; longer ranges use daily bars. If a provider has no
 * intraday data for a symbol, that range returns empty and the UI says so —
 * nothing is fabricated to fill it.
 */
export type StockRange = "1D" | "7D" | "1M" | "6M" | "1Y" | "3Y" | "5Y";

export const STOCK_RANGES: StockRange[] = ["1D", "7D", "1M", "6M", "1Y", "3Y", "5Y"];

export interface RangeWindow {
  start: string;
  end: string;
  interval: string;
  /** Intraday bars can't carry a daily forecast overlay. */
  intraday: boolean;
  /** Calendar days of history requested. */
  days: number;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Resolve a range to a concrete API window relative to `now`. */
export function rangeWindow(range: StockRange, now: Date = new Date()): RangeWindow {
  const day = 86_400_000;
  const cfg: Record<StockRange, { days: number; interval: string; intraday: boolean }> = {
    "1D": { days: 2, interval: "5m", intraday: true },
    "7D": { days: 7, interval: "30m", intraday: true },
    "1M": { days: 31, interval: "1d", intraday: false },
    "6M": { days: 183, interval: "1d", intraday: false },
    "1Y": { days: 365, interval: "1d", intraday: false },
    "3Y": { days: 1095, interval: "1d", intraday: false },
    "5Y": { days: 1825, interval: "1d", intraday: false },
  };
  const { days, interval, intraday } = cfg[range];
  // `end` is exclusive in the provider, so add a day to include today.
  const end = new Date(now.getTime() + day);
  const start = new Date(now.getTime() - days * day);
  return { start: iso(start), end: iso(end), interval, intraday, days };
}

export function isStockRange(v: unknown): v is StockRange {
  return typeof v === "string" && (STOCK_RANGES as string[]).includes(v);
}
