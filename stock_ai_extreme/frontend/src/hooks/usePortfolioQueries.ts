/**
 * Phase 9 — React hooks over the Phase 9 services (spec E: the UI reads
 * server state through hooks, never storage/axios directly).
 *
 * `usePortfolioData` loads transactions + a live price for every held symbol
 * through the SAME provider layer the rest of the app uses (spec P — no
 * duplicated price dataset inside portfolio components) and computes the
 * portfolio client-side with the shared `finance` utilities, so the dashboard
 * updates immediately after every add/remove (spec D).
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  portfolioService,
  watchlistService,
  transactionService,
  type WatchlistItem,
  type StoredTransaction,
  type TransactionFilter,
} from "../lib/portfolioStorage";
import {
  calculatePosition,
  calculatePortfolioSummary,
  calculateUnrealizedPnl,
  calculateTotalReturn,
  formatPkr,
  formatPct,
  type Position,
} from "../lib/finance";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

/** Live quote through the backend provider layer (same as everywhere else). */
export async function fetchQuote(symbol: string): Promise<{ price: number | null; changePercent: number | null; status: string }> {
  try {
    const res = await fetch(
      `${API}/api/stocks/${encodeURIComponent(symbol.toUpperCase())}/snapshot`
    );
    if (!res.ok) return { price: null, changePercent: null, status: "UNAVAILABLE" };
    const data = await res.json();
    const price = typeof data?.price === "number" && Number.isFinite(data.price) ? data.price : null;
    return {
      price,
      changePercent: typeof data?.change_percent === "number" ? data.change_percent : null,
      status: data?.data_meta?.status ?? "UNKNOWN",
    };
  } catch {
    return { price: null, changePercent: null, status: "UNAVAILABLE" };
  }
}

// ---------------------------------------------------------------------------
// Watchlist
// ---------------------------------------------------------------------------

export function useWatchlistItems() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await watchlistService.list();
      setItems(list);
      setOffline(false);
    } catch {
      // backend unreachable — degrade to the local adapter honestly
      try {
        portfolioService.useLocalFallback();
        const list = await watchlistService.list();
        setItems(list);
        setOffline(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load watchlist");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const add = useCallback(
    async (symbol: string, notes?: string) => {
      await watchlistService.add(symbol, notes);
      await reload();
    },
    [reload]
  );

  const remove = useCallback(
    async (symbol: string) => {
      await watchlistService.remove(symbol);
      await reload();
    },
    [reload]
  );

  const setNotes = useCallback(
    async (symbol: string, notes: string | null) => {
      await watchlistService.setNotes(symbol, notes);
      await reload();
    },
    [reload]
  );

  const reorder = useCallback(
    async (orderedIds: Array<string | number>) => {
      // Optimistic: apply locally first so the UI moves instantly (spec D).
      setItems((prev) => {
        const map = new Map(prev.map((i) => [String(i.id), i]));
        const next = orderedIds
          .map((id) => map.get(String(id)))
          .filter((i): i is WatchlistItem => Boolean(i));
        // keep any items that were not part of the drag at the end
        const rest = prev.filter((i) => !orderedIds.map(String).includes(String(i.id)));
        return [...next, ...rest];
      });
      try {
        const list = await watchlistService.reorder(orderedIds);
        setItems(list);
      } catch {
        await reload(); // revert on failure
      }
    },
    [reload]
  );

  const symbols = useMemo(() => new Set(items.map((i) => i.symbol)), [items]);

  return { items, symbols, loading, error, offline, reload, add, remove, setNotes, reorder };
}

// ---------------------------------------------------------------------------
// Portfolio
// ---------------------------------------------------------------------------

export interface HoldingRow {
  position: Position;
  currentPrice: number | null;
  priceStatus: string;
  marketValue: number | null;
  unrealized: { amount: number | null; percent: number | null };
  totalReturn: { amount: number | null; percent: number | null };
  allocationPct: number | null;
}

export function usePortfolioData() {
  const [transactions, setTransactions] = useState<StoredTransaction[]>([]);
  const [priceMap, setPriceMap] = useState<Record<string, { price: number | null; status: string }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let txs: StoredTransaction[];
      try {
        txs = await transactionService.list();
        setOffline(false);
      } catch {
        portfolioService.useLocalFallback();
        txs = await transactionService.list();
        setOffline(true);
      }
      setTransactions(txs);

      // One live price per distinct held symbol, through the provider layer.
      const symbols = [...new Set(txs.map((t) => t.symbol))];
      const results = await Promise.all(
        symbols.map(async (s) => [s, await fetchQuote(s)] as const)
      );
      const map: Record<string, { price: number | null; status: string }> = {};
      for (const [s, q] of results) map[s] = { price: q.price, status: q.status };
      setPriceMap(map);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load portfolio");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** Available quantity per symbol — powers SELL validation (spec N). */
  const availableQty = useCallback(
    (symbol: string): number => calculatePosition(transactions, symbol)?.quantity ?? 0,
    [transactions]
  );

  const addTransaction = useCallback(
    async (input: { symbol: string; side: "BUY" | "SELL"; quantity: string; price: string; fees: string; date: string }) => {
      await transactionService.create(input);
      await reload(); // spec D: UI updates immediately
    },
    [reload]
  );

  const removeTransaction = useCallback(
    async (id: string) => {
      await transactionService.remove(id);
      await reload();
    },
    [reload]
  );

  /** Enriched holdings rows for the table (spec L). */
  const holdings: HoldingRow[] = useMemo(() => {
    const symbols = [...new Set(transactions.map((t) => t.symbol))];
    const positions = symbols
      .map((s) => calculatePosition(transactions, s))
      .filter((p): p is Position => p !== null);

    const rows: HoldingRow[] = positions.map((p) => {
      const q = priceMap[p.symbol];
      const price = q?.price ?? null;
      const marketValue =
        price !== null && Number.isFinite(price) ? p.quantity * price : null;
      const unrealized = calculateUnrealizedPnl(p, price);
      const totalReturn = calculateTotalReturn(p, price);
      return {
        position: p,
        currentPrice: price,
        priceStatus: q?.status ?? "UNAVAILABLE",
        marketValue,
        unrealized,
        totalReturn,
        allocationPct: null, // filled below once the total is known
      };
    });

    const totalMv = rows.reduce((s, r) => s + (r.marketValue ?? 0), 0);
    for (const r of rows) {
      r.allocationPct =
        r.marketValue !== null && totalMv > 0 ? (r.marketValue / totalMv) * 100 : null;
    }
    rows.sort((a, b) => (b.marketValue ?? 0) - (a.marketValue ?? 0));
    return rows;
  }, [transactions, priceMap]);

  const summary = useMemo(
    () =>
      calculatePortfolioSummary(
        transactions,
        Object.fromEntries(
          Object.entries(priceMap).map(([k, v]) => [k, v.price])
        )
      ).summary,
    [transactions, priceMap]
  );

  return {
    transactions,
    holdings,
    summary,
    loading,
    error,
    offline,
    availableQty,
    addTransaction,
    removeTransaction,
    reload,
    formatPkr,
    formatPct,
  };
}

// ---------------------------------------------------------------------------
// Portfolio performance — equity curve + risk metrics from the backend engine
// (real daily closes replayed against the real transaction log; spec P: same
// provider layer, no duplicated price dataset here)
// ---------------------------------------------------------------------------

export interface PerformancePoint {
  date: string;
  value: number;
}

export interface PerformanceMetrics {
  current_value: number;
  invested_capital: number;
  realized_proceeds: number;
  net_pnl: number;
  net_return_pct: number | null;
  irr_pct: number | null;
  cagr_pct: number | null;
  volatility_pct: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct?: number | null;
}

export interface PerformanceResponse {
  points: PerformancePoint[];
  metrics: PerformanceMetrics | null;
  message?: string;
  unavailable_symbols?: string[];
}

/** Loads the performance curve; fails soft with `message` (never fake data). */
export function usePortfolioPerformance(days = 180) {
  const [data, setData] = useState<PerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/portfolio/performance?days=${days}`);
      if (!res.ok) throw new Error(`Performance unavailable (${res.status})`);
      setData((await res.json()) as PerformanceResponse);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load performance");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, loading, error, reload };
}

// ---------------------------------------------------------------------------
// Transaction history filtering (spec M)
// ---------------------------------------------------------------------------

export function useTransactionFilter(transactions: StoredTransaction[]) {
  const [side, setSide] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [symbol, setSymbol] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const symbols = useMemo(
    () => [...new Set(transactions.map((t) => t.symbol))].sort(),
    [transactions]
  );

  const filtered = useMemo(() => {
    return transactions
      .filter((t) => (side === "ALL" ? true : t.side === side))
      .filter((t) =>
        symbol.trim() ? t.symbol.includes(symbol.trim().toUpperCase()) : true
      )
      .filter((t) => (dateFrom ? t.date >= dateFrom : true))
      .filter((t) => (dateTo ? t.date <= `${dateTo}T23:59:59` : true))
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [transactions, side, symbol, dateFrom, dateTo]);

  return {
    side,
    setSide,
    symbol,
    setSymbol,
    dateFrom,
    setDateFrom,
    dateTo,
    setDateTo,
    symbols,
    filtered,
  };
}

export type { TransactionFilter };
