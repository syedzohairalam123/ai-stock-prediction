import { useMutation, useQuery } from "@tanstack/react-query";
import { ForecastService, type ForecastHistoryRange, type ForecastSimulation, type ForecastSimulationOptions } from "../lib/forecasting";
import type { CombinationEventInput, CombineOptions, CorrelationAnalysisResult } from "../lib/combination";
import { CorrelationAdjustedCalculator } from "../lib/combinationApi";

export const forecastKeys = { markets: ["forecast-markets"] as const, market: (id: string) => ["forecast-market", id] as const, history: (id: string, range: ForecastHistoryRange) => ["forecast-history", id, range] as const };
export function useForecastMarkets() { return useQuery({ queryKey: forecastKeys.markets, queryFn: ForecastService.getForecastMarkets, staleTime: 60_000, refetchInterval: 60_000, retry: 0 }); }
export function useForecastMarket(id: string) { return useQuery({ queryKey: forecastKeys.market(id), queryFn: () => ForecastService.getForecastById(id), enabled: Boolean(id), staleTime: 60_000, retry: 0 }); }
export function useForecastHistory(id: string, range: ForecastHistoryRange) { return useQuery({ queryKey: forecastKeys.history(id, range), queryFn: () => ForecastService.getForecastHistory(id, range), enabled: Boolean(id), staleTime: 60_000, retry: 0 }); }

/** Phase 14.3 — run a Monte-Carlo simulation for the given market. */
export function useForecastSimulation(id: string) {
  return useMutation<ForecastSimulation, Error, ForecastSimulationOptions>({
    mutationFn: (options) => ForecastService.simulateForecast(id, options),
  });
}

/** Phase 15.1 — correlation-adjusted combination analysis. */
export function useCorrelationCombine() {
  return useMutation<CorrelationAnalysisResult, Error, { events: CombinationEventInput[]; options?: CombineOptions }>({
    mutationFn: ({ events, options }) => CorrelationAdjustedCalculator.combine(events, options),
  });
}
