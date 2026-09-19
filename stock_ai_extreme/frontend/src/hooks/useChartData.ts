/**
 * Phase 11 — chart dataset hook.
 *
 * Goes through the existing React Query layer so two panels plotting the same
 * symbol/timeframe share one request, and re-mounting a panel (layout switch,
 * fullscreen) reuses the cached candles instead of refetching.
 *
 * Chart data is intentionally *not* polled aggressively: candles change at bar
 * close, and refetching every minute would thrash the drawing/viewport state for
 * no informational gain. A 60s staleness window keeps it fresh enough while the
 * user is analysing, and `refetchOnWindowFocus` stays on.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { loadChartDataset, type ChartDataset } from "../lib/charting/dataSource";
import type { EntityType } from "../lib/charting/types";
import type { StockRange } from "../lib/timeframes";

export const chartQueryKey = (symbol: string, entityType: EntityType, timeframe: StockRange) =>
  ["chart", "dataset", symbol, entityType, timeframe] as const;

export function useChartDataset(
  symbol: string,
  entityType: EntityType,
  timeframe: StockRange
): UseQueryResult<ChartDataset, Error> {
  return useQuery<ChartDataset, Error>({
    queryKey: chartQueryKey(symbol, entityType, timeframe),
    queryFn: () => loadChartDataset(symbol, entityType, timeframe),
    enabled: Boolean(symbol),
    staleTime: 60_000,
    gcTime: 10 * 60_000,
    retry: 0,
    refetchOnWindowFocus: true,
  });
}
