/**
 * Data hooks (Phase 5) — the only place components read server state.
 *
 * Built on React Query so caching, de-duplication, retries, background
 * refresh and loading/error states are handled once instead of per component.
 * Screens consume these hooks and never call `fetch`/`axios` themselves.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MarketService, type HistoryRow } from "../lib/services";
import { rangeWindow, type StockRange } from "../lib/timeframes";

export const queryKeys = {
  snapshot: (ticker: string) => ["stock", "snapshot", ticker] as const,
  history: (ticker: string, range: StockRange) => ["stock", "history", ticker, range] as const,
  watchlist: ["watchlist", "quotes"] as const,
};

/** Consolidated stock-detail payload for the header + stat strip. */
export function useStockSnapshot(ticker: string) {
  return useQuery({
    queryKey: queryKeys.snapshot(ticker),
    queryFn: () => MarketService.getStockSnapshot(ticker),
    enabled: Boolean(ticker),
    refetchInterval: 60_000,
    retry: 0,
  });
}

/** OHLCV rows for one timeframe, cached per (ticker, range). */
export function useStockHistory(ticker: string, range: StockRange) {
  const win = rangeWindow(range);
  return useQuery({
    queryKey: queryKeys.history(ticker, range),
    queryFn: () => MarketService.getHistory(ticker, win.start, win.end, win.interval),
    enabled: Boolean(ticker),
    refetchInterval: 60_000,
    retry: 0,
    select: (data): HistoryRow[] => (Array.isArray(data?.rows) ? data.rows : []),
  });
}

/** Priced watchlist + add/remove mutations that invalidate the cache. */
export function useWatchlist() {
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: queryKeys.watchlist,
    queryFn: () => MarketService.getWatchlistQuotes(),
    refetchInterval: 60_000, // Reduced frequency to prevent errors
    retry: 0, // No retries to avoid console spam
  });

  const add = useMutation({
    mutationFn: (ticker: string) => MarketService.addWatchlist(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.watchlist }),
  });

  const remove = useMutation({
    mutationFn: (ticker: string) => MarketService.removeWatchlist(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.watchlist }),
  });

  return { ...query, add, remove };
}
