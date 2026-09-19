/**
 * Phase 7 — Forex & Commodities data layer.
 *
 * Same layering the rest of the terminal uses (spec L: keep the API isolated):
 *
 *   page  ->  ForexService / CommodityService  ->  lib/api (fetch)  ->  FastAPI
 *
 * Every value that reaches the UI is validated first (spec N). Real feeds hand
 * back nulls, inverted quotes and undated values, and a trading screen must show
 * an explicit missing state — never `NaN`, `Infinity` or `undefined`.
 *
 * The backend already reports a freshness state per quote; `getDataFreshness`
 * exists here too (spec O) because freshness *decays while the page stays open*.
 * The page re-evaluates it on a timer so a rate that was FRESH when fetched
 * stops being labelled fresh once it ages, without issuing another request.
 */
import { getJSON } from "./api";

// ---------------------------------------------------------------------------
// Types (mirroring the backend contract)
// ---------------------------------------------------------------------------

export type DataMode = "LIVE" | "DELAYED" | "DEMO" | "UNAVAILABLE";
export type Freshness = "FRESH" | "AGING" | "STALE" | "UNKNOWN";
export type FreshnessThresholds = { live_seconds: number; aging_seconds: number; stale_seconds: number };

export interface ForexQuote {
  symbol: string;
  base_currency: string;
  quote_currency: string;
  name: string;
  /** null, never 0, when the source published no usable side */
  bid: number | null;
  ask: number | null;
  mid: number | null;
  spread: number | null;
  spread_percent: number | null;
  change: number | null;
  change_percent: number | null;
  timestamp: string | null;
  timestamp_epoch: number | null;
  source: string;
  data_mode: DataMode;
  freshness: Freshness;
  previous_close: number | null;
  granularity: string;
  bid_ask_note: string | null;
  error: string | null;
}

export interface ForexResponse {
  base: string;
  count: number;
  quotes: ForexQuote[];
  failed: string[];
  rejected_currencies: string[];
  live_count: number;
  delayed_count: number;
  sources: string[];
  fallback_source: string | null;
  fallback_error: string | null;
  generated_at: string;
  thresholds: FreshnessThresholds;
  label: string;
  disclaimer: string;
  data_meta?: { source?: string; status?: string };
}

export interface CommodityQuote {
  id: string;
  symbol: string;
  name: string;
  type: string;
  purity: string;
  fineness: number | null;
  unit: string;
  unit_key: string;
  currency: string;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  previous_price: number | null;
  timestamp: string | null;
  timestamp_epoch: number | null;
  source: string;
  data_mode: DataMode;
  freshness: Freshness;
  is_primary_unit: boolean;
  usd_per_troy_ounce: number | null;
  usdpkr: number | null;
  bid_ask_note: string | null;
  error: string | null;
  sparkline_pkr: number[];
}

export interface MetalGroup {
  key: string;
  symbol: string;
  name: string;
  type: string;
  purity: string;
  fineness: number | null;
  primary_unit: string;
  units: { unit: string; unit_key: string }[];
}

export interface CommodityResponse {
  currency: string;
  count: number;
  items: CommodityQuote[];
  by_metal: MetalGroup[];
  unavailable: string[];
  inputs: Record<string, any>;
  units: { troy_ounce_grams: number; tola_grams: number; definition: string };
  derivation: string;
  generated_at: string;
  thresholds: FreshnessThresholds;
  priced_count: number;
  label: string;
  disclaimer: string;
  data_meta?: { source?: string; status?: string };
}

// ---------------------------------------------------------------------------
// Numbers — nothing unresolvable ever reaches a cell
// ---------------------------------------------------------------------------

export function isUsableNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Returns the number, or null when it is missing/NaN/Infinity. */
export function safeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Rate display precision by magnitude. A JPY/PKR rate (≈1.80) needs more
 * decimals than USD/PKR (≈277) to stay informative, and neither should show
 * twelve invented digits.
 */
export function rateDigits(value: number | null | undefined): number {
  const v = safeNumber(value);
  if (v === null) return 2;
  const abs = Math.abs(v);
  if (abs >= 100) return 2;
  if (abs >= 1) return 4;
  return 6;
}

export function formatRate(value: number | null | undefined): string {
  const v = safeNumber(value);
  if (v === null) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: rateDigits(v),
    maximumFractionDigits: rateDigits(v),
  });
}

export function formatPkr(value: number | null | undefined, digits = 2): string {
  const v = safeNumber(value);
  if (v === null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// ---------------------------------------------------------------------------
// Freshness (spec O) — thresholds are configurable
// ---------------------------------------------------------------------------

export const DEFAULT_THRESHOLDS: FreshnessThresholds = {
  live_seconds: 900,
  aging_seconds: 86400,
  stale_seconds: 604800,
};

export function getDataFreshness(
  timestamp: string | number | null | undefined,
  thresholds: FreshnessThresholds = DEFAULT_THRESHOLDS,
  /** injectable for tests and for re-running against an older "now" */
  now: number = Date.now(),
): Freshness {
  let ms: number | null = null;
  if (typeof timestamp === "number" && Number.isFinite(timestamp)) {
    // The API sends epoch seconds; tolerate a millisecond value too.
    ms = timestamp > 1e12 ? timestamp : timestamp * 1000;
  } else if (typeof timestamp === "string" && timestamp.trim()) {
    const parsed = Date.parse(timestamp);
    ms = Number.isFinite(parsed) ? parsed : null;
  }
  if (ms === null) return "UNKNOWN";
  if (ms < Date.parse("2000-01-01T00:00:00Z") || ms > now + 86400000) return "UNKNOWN";

  const ageSeconds = (now - ms) / 1000;
  if (ageSeconds < 0) return "FRESH";
  if (ageSeconds <= thresholds.live_seconds) return "FRESH";
  if (ageSeconds <= thresholds.aging_seconds) return "AGING";
  return "STALE";
}

/** Age in seconds, or null when the timestamp cannot be trusted. */
export function ageSeconds(timestamp: string | number | null | undefined, now: number = Date.now()): number | null {
  if (typeof timestamp === "number" && Number.isFinite(timestamp)) {
    const ms = timestamp > 1e12 ? timestamp : timestamp * 1000;
    return Math.max(0, Math.round((now - ms) / 1000));
  }
  if (typeof timestamp === "string" && timestamp.trim()) {
    const parsed = Date.parse(timestamp);
    if (Number.isFinite(parsed)) return Math.max(0, Math.round((now - parsed) / 1000));
  }
  return null;
}

export function formatAge(seconds: number | null): string {
  if (seconds === null) return "unknown";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/**
 * Re-derives the freshness of a whole payload against a moving clock. Used by
 * the page's timer so an on-screen rate stops claiming FRESH as it ages.
 */
export function refreshFreshness<T extends { timestamp_epoch?: number | null; timestamp?: string | null; freshness?: Freshness }>(
  rows: T[],
  thresholds: FreshnessThresholds = DEFAULT_THRESHOLDS,
  now: number = Date.now(),
): T[] {
  return rows.map((row) => ({
    ...row,
    freshness: getDataFreshness(row.timestamp_epoch ?? row.timestamp ?? null, thresholds, now),
  }));
}

// ---------------------------------------------------------------------------
// Validation (spec N) — reject rather than render something misleading
// ---------------------------------------------------------------------------

export function validateForexQuote(quote: ForexQuote): string[] {
  const issues: string[] = [];
  if (!quote.symbol) issues.push("missing symbol");
  if (quote.bid !== null && quote.ask !== null && quote.bid > quote.ask) {
    issues.push(`bid ${quote.bid} is above ask ${quote.ask}`);
  }
  for (const [field, value] of Object.entries({ bid: quote.bid, ask: quote.ask, mid: quote.mid, spread: quote.spread })) {
    if (value !== null && !isUsableNumber(value)) issues.push(`${field} is not a finite number`);
  }
  if (quote.spread !== null && quote.spread < 0) issues.push("negative spread");
  if (!quote.quote_currency || quote.quote_currency.length !== 3) issues.push("invalid quote currency code");
  if (!quote.base_currency || quote.base_currency.length !== 3) issues.push("invalid base currency code");
  return issues;
}

export function validateCommodityQuote(quote: CommodityQuote): string[] {
  const issues: string[] = [];
  if (!quote.id || !quote.symbol) issues.push("missing id/symbol");
  if (quote.price !== null && !(isUsableNumber(quote.price) && quote.price > 0)) issues.push("price must be a positive number");
  if (!quote.unit) issues.push("missing unit — values must never be unitless");
  if (quote.change_percent !== null && !isUsableNumber(quote.change_percent)) issues.push("change % is not finite");
  return issues;
}

/** True when a quote can be displayed as a real rate rather than an error row. */
export function isDisplayable(mid: number | null, dataMode: DataMode): boolean {
  return isUsableNumber(mid) && dataMode !== "UNAVAILABLE";
}

// ---------------------------------------------------------------------------
// Search + sorting (spec E / F) — always on raw numeric values
// ---------------------------------------------------------------------------

/** `USD`, `US Dollar`, `USD/PKR`, `usdpkr` all match. */
export function forexMatches(quote: ForexQuote, term: string): boolean {
  const q = term.trim().toLowerCase();
  if (!q) return true;
  const haystack = [quote.symbol, quote.base_currency, quote.quote_currency, quote.name, quote.symbol.replace("/", ""), quote.source]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

export type ForexSortKey = "currency" | "pair" | "bid" | "ask" | "spread" | "change_percent" | "timestamp";

export const FOREX_SORT_LABELS: Record<ForexSortKey, string> = {
  currency: "Currency",
  pair: "Pair",
  bid: "Bid",
  ask: "Ask",
  spread: "Spread",
  change_percent: "Change %",
  timestamp: "Updated",
};

/**
 * Numeric comparator over raw fields (spec F). Missing values always sink to
 * the bottom, whichever direction is active — sorting must never pretend a
 * null is a zero.
 */
export function sortForexQuotes(quotes: ForexQuote[], key: ForexSortKey, direction: "asc" | "desc"): ForexQuote[] {
  const pick = (q: ForexQuote): number | string | null => {
    switch (key) {
      case "currency":
        return q.base_currency || null;
      case "pair":
        return q.symbol || null;
      case "bid":
        return safeNumber(q.bid);
      case "ask":
        return safeNumber(q.ask);
      case "spread":
        return safeNumber(q.spread);
      case "change_percent":
        return safeNumber(q.change_percent);
      case "timestamp":
        return safeNumber(q.timestamp_epoch);
      default:
        return null;
    }
  };

  const sign = direction === "asc" ? 1 : -1;
  return [...quotes].sort((a, b) => {
    const av = pick(a);
    const bv = pick(b);
    const aMissing = av === null || av === undefined || av === "";
    const bMissing = bv === null || bv === undefined || bv === "";
    if (aMissing && bMissing) return a.symbol.localeCompare(b.symbol);
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv)) * sign;
    }
    return ((av as number) - (bv as number)) * sign;
  });
}

export function commodityMatches(quote: CommodityQuote, term: string): boolean {
  const q = term.trim().toLowerCase();
  if (!q) return true;
  return [quote.name, quote.symbol, quote.type, quote.purity, quote.unit, quote.unit_key]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(q);
}

// ---------------------------------------------------------------------------
// Services (spec L / M) — the only place endpoint strings live
// ---------------------------------------------------------------------------

export interface FetchOptions {
  /** bypass the server's TTL cache — backs the Refresh action */
  refresh?: boolean;
  signal?: AbortSignal;
}

async function fetchWithSignal<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!signal) return getJSON<T>(path);
  // lib/api's helper doesn't take a signal; inline the same contract so a
  // refresh can cancel an in-flight request instead of racing it.
  const base = import.meta.env.VITE_API_URL || "/api";
  const res = await fetch(`${base}${path}`, { signal });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const ForexService = {
  /** All PKR-quoted pairs with their real bid/ask/mid/spread. */
  async getForexQuotes(options: FetchOptions = {}): Promise<ForexResponse> {
    const query = options.refresh ? "?refresh=true" : "";
    return fetchWithSignal<ForexResponse>(`/api/forex${query}`, options.signal);
  },

  /**
   * One pair. Resolved from the list endpoint on purpose: the grid already has
   * every pair, so a per-symbol request would only add load (spec R).
   */
  async getForexQuote(symbol: string, options: FetchOptions = {}): Promise<ForexQuote | null> {
    const wanted = symbol.trim().toUpperCase();
    const payload = await this.getForexQuotes(options);
    return (
      payload.quotes.find((q) => q.symbol.toUpperCase() === wanted || q.base_currency.toUpperCase() === wanted) ?? null
    );
  },

  /** Force-refreshes every rate (spec G). */
  async refreshMarketRates(): Promise<ForexResponse> {
    return this.getForexQuotes({ refresh: true });
  },
};

export const CommodityService = {
  /** Gold 24K/22K, Silver and Platinum, each unit stated explicitly. */
  async getCommodityQuotes(options: FetchOptions = {}): Promise<CommodityResponse> {
    const query = options.refresh ? "?refresh=true" : "";
    return fetchWithSignal<CommodityResponse>(`/api/commodities${query}`, options.signal);
  },

  async getCommodityQuote(symbol: string, options: FetchOptions = {}): Promise<CommodityQuote | null> {
    const wanted = symbol.trim().toUpperCase();
    const payload = await this.getCommodityQuotes(options);
    return payload.items.find((i) => i.symbol.toUpperCase() === wanted && i.is_primary_unit) ?? null;
  },

  async refreshMarketRates(): Promise<CommodityResponse> {
    return this.getCommodityQuotes({ refresh: true });
  },
};

/** Rows for one metal, primary unit first — used by the cards. */
export function rowsForMetal(items: CommodityQuote[], symbol: string): CommodityQuote[] {
  return items
    .filter((i) => i.symbol.toUpperCase() === symbol.toUpperCase())
    .sort((a, b) => Number(b.is_primary_unit) - Number(a.is_primary_unit));
}
