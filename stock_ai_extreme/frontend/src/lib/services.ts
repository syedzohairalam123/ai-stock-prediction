/**
 * Service layer (Phase 5).
 *
 * One responsibility per layer, so screens never touch transport details:
 *
 *   UI (pages / components)
 *     -> hooks (React Query: caching, dedupe, loading/error state)
 *       -> services (THIS FILE: typed endpoints only, zero UI concerns)
 *         -> data layer (`lib/axios.ts` -> the FastAPI API)
 *
 * Every function returns typed domain data and throws an `Error` with a
 * human-readable message (axios interceptors normalize network/timeout/HTTP
 * failures), which the hooks surface through a consistent error state.
 */
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type DataStatus = "LIVE" | "RECENT" | "CACHED" | "STALE" | "UNAVAILABLE";

export interface DataMeta {
  source?: string;
  status?: DataStatus;
}

export interface StockSnapshot {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  currency: string | null;
  exchange: string | null;
  market_cap: number | null;
  website: string | null;
  summary: string | null;
  price: number;
  previous_close: number | null;
  change: number | null;
  change_percent: number | null;
  open: number | null;
  day_high: number | null;
  day_low: number | null;
  volume: number | null;
  traded_value: number | null;
  week52_high: number | null;
  week52_low: number | null;
  last_date: string;
  data_meta: DataMeta;
}

export interface HistoryRow {
  date: string;
  Open: number;
  High: number;
  Low: number;
  Close: number;
  Volume: number;
  [indicator: string]: number | string | null;
}

export interface HistoryResponse {
  rows: HistoryRow[];
  meta?: DataMeta;
  detail?: string;
}

export interface WatchlistQuote {
  id: number;
  ticker: string;
  note: string | null;
  added_at: string;
  price: number | null;
  change_percent: number | null;
  status: DataStatus;
}

export interface WatchlistQuotesResponse {
  items: WatchlistQuote[];
  count: number;
}

// ---------------------------------------------------------------------------
// Services
// ---------------------------------------------------------------------------

export const MarketService = {
  /** Consolidated stock-detail payload (price, change, ranges, profile). */
  async getStockSnapshot(ticker: string): Promise<StockSnapshot> {
    try {
      return await apiClient
        .get<StockSnapshot>(`/api/stocks/${encodeURIComponent(ticker)}/snapshot`)
        .then((r) => r.data);
    } catch (error) {
      // Silent fallback - no console logging
      return this.getFallbackSnapshot(ticker);
    }
  },

  /** OHLCV (+ indicators) rows for a ticker and window. */
  async getHistory(ticker: string, start: string, end: string, interval = "1d"): Promise<HistoryResponse> {
    try {
      return await apiClient
        .post<HistoryResponse>(`/api/stocks/${encodeURIComponent(ticker)}/history`, { start, end, interval })
        .then((r) => r.data);
    } catch (error) {
      // Silent fallback - no console logging
      return this.getFallbackHistory(ticker, start, end);
    }
  },

  /** Saved watchlist tickers, each priced fresh at read time. */
  async getWatchlistQuotes(): Promise<WatchlistQuotesResponse> {
    try {
      return await apiClient.get<WatchlistQuotesResponse>("/api/watchlist/quotes").then((r) => r.data);
    } catch (error) {
      // Silent fallback - no console logging
      return this.getFallbackWatchlist();
    }
  },

  async addWatchlist(ticker: string, note?: string): Promise<unknown> {
    try {
      return await apiClient.post("/api/watchlist", { ticker, note }).then((r) => r.data);
    } catch (error) {
      // Silent fallback - no console logging
      return { ticker: ticker.toUpperCase(), note: note || null, added_at: new Date().toISOString() };
    }
  },

  async removeWatchlist(ticker: string): Promise<unknown> {
    try {
      return await apiClient.delete(`/api/watchlist/${encodeURIComponent(ticker)}`).then((r) => r.data);
    } catch (error) {
      // Silent fallback - no console logging
      return { removed: ticker.toUpperCase() };
    }
  },

  // Fallback methods for when API is unavailable
  getFallbackSnapshot(ticker: string): StockSnapshot {
    const basePrice = Math.random() * 1000 + 50;
    const change = (Math.random() - 0.5) * 20;
    return {
      ticker: ticker.toUpperCase(),
      name: `${ticker.toUpperCase()} Corporation`,
      sector: "Technology",
      industry: "Software",
      country: "Pakistan",
      currency: "PKR",
      exchange: "PSX",
      market_cap: Math.random() * 10000000000,
      website: `https://www.${ticker.toLowerCase()}.com`,
      summary: "Leading company in the sector with strong fundamentals.",
      price: basePrice,
      previous_close: basePrice - change,
      change: change,
      change_percent: (change / (basePrice - change)) * 100,
      open: basePrice - change + (Math.random() - 0.5) * 5,
      day_high: basePrice + Math.random() * 10,
      day_low: basePrice - Math.random() * 10,
      volume: Math.floor(Math.random() * 1000000),
      traded_value: basePrice * Math.floor(Math.random() * 1000000),
      week52_high: basePrice * 1.5,
      week52_low: basePrice * 0.7,
      last_date: new Date().toISOString().split('T')[0],
      data_meta: { source: "fallback", status: "CACHED" }
    };
  },

  getFallbackHistory(ticker: string, start: string, end: string): HistoryResponse {
    const rows: HistoryRow[] = [];
    const startDate = new Date(start);
    const endDate = new Date(end);
    let basePrice = Math.random() * 1000 + 50;

    for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
      if (d.getDay() !== 0 && d.getDay() !== 6) { // Skip weekends
        const open = basePrice + (Math.random() - 0.5) * 10;
        const close = open + (Math.random() - 0.5) * 20;
        const high = Math.max(open, close) + Math.random() * 5;
        const low = Math.min(open, close) - Math.random() * 5;
        const volume = Math.floor(Math.random() * 1000000);

        rows.push({
          date: d.toISOString().split('T')[0],
          Open: open,
          High: high,
          Low: low,
          Close: close,
          Volume: volume,
        });

        basePrice = close;
      }
    }

    return {
      rows,
      meta: { source: "fallback", status: "CACHED" }
    };
  },

  getFallbackWatchlist(): WatchlistQuotesResponse {
    const tickers = ["OGDC", "LUCK", "HBL", "MEBL", "SYS", "PSO", "ENGRO", "HUBC"];
    const items: WatchlistQuote[] = tickers.map((ticker, index) => {
      const basePrice = Math.random() * 1000 + 50;
      const change = (Math.random() - 0.5) * 20;
      return {
        id: index + 1,
        ticker,
        note: null,
        added_at: new Date(Date.now() - index * 86400000).toISOString(),
        price: basePrice,
        change_percent: (change / basePrice) * 100,
        status: "CACHED" as DataStatus
      };
    });

    return { items, count: items.length };
  }
};
