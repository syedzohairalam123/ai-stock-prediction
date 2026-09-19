import { useQuery } from "@tanstack/react-query";
import { ForecastService, type ForecastHistoryRange } from "../lib/forecasting";

export const forecastKeys = { markets: ["forecast-markets"] as const, market: (id: string) => ["forecast-market", id] as const, history: (id: string, range: ForecastHistoryRange) => ["forecast-history", id, range] as const };
export function useForecastMarkets() { return useQuery({ queryKey: forecastKeys.markets, queryFn: ForecastService.getForecastMarkets, staleTime: 60_000, refetchInterval: 60_000, retry: 0 }); }
export function useForecastMarket(id: string) { return useQuery({ queryKey: forecastKeys.market(id), queryFn: () => ForecastService.getForecastById(id), enabled: Boolean(id), staleTime: 60_000, retry: 0 }); }
export function useForecastHistory(id: string, range: ForecastHistoryRange) { return useQuery({ queryKey: forecastKeys.history(id, range), queryFn: () => ForecastService.getForecastHistory(id, range), enabled: Boolean(id), staleTime: 60_000, retry: 0 }); }
