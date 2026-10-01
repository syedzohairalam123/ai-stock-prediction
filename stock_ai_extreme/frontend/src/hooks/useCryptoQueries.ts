/**
 * Phase 22A — Crypto Market Data & Multi-Timeframe engine: React Query hooks.
 *
 * The only place crypto components read *server* state. Caching, de-duplication,
 * background refresh and loading/error states live here once, so switching asset
 * or timeframe never blanks the page. Fast-changing *live* state (ticks, live
 * candle tails) is deliberately NOT here — it is fed by the WebSocket gateway
 * into `store/useCryptoStore.ts`.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  CryptoService,
  type AnalyticsResponse,
  type CandlesResponse,
  type CryptoAssetsResponse,
  type CryptoHealthResponse,
  type DriftResponse,
  type ForecastHistoryResponse,
  type ForecastPerformanceResponse,
  type ForecastResponse,
  type IndustryResponse,
  type InstitutionsResponse,
  type MultiTimeframeResponse,
  type OnDateResponse,
  type PreSessionResponse,
  type ProbeResponse,
  type QuotePayload,
  type SourcesResponse,
  type TargetsResponse,
  type ThresholdResponse,
  type TimeframesResponse,
} from "../lib/crypto";

export const cryptoKeys = {
  assets: ["crypto", "assets"] as const,
  timeframes: ["crypto", "timeframes"] as const,
  sources: ["crypto", "sources"] as const,
  quote: (symbol: string) => ["crypto", "quote", symbol] as const,
  candles: (symbol: string, timeframe: string, limit: number) =>
    ["crypto", "candles", symbol, timeframe, limit] as const,
  analytics: (symbol: string, timeframe: string) =>
    ["crypto", "analytics", symbol, timeframe] as const,
  multiTimeframe: (symbol: string) => ["crypto", "multi-timeframe", symbol] as const,
  health: ["crypto", "health"] as const,
  probe: ["crypto", "health", "probe"] as const,
  // Phase 22C
  forecast: (symbol: string, timeframe: string, horizon: number) =>
    ["crypto", "forecast", symbol, timeframe, horizon] as const,
  forecastHistory: (symbol: string, timeframe: string) =>
    ["crypto", "forecast-history", symbol, timeframe] as const,
  performance: (symbol: string | null) => ["crypto", "forecast-performance", symbol ?? "all"] as const,
  targets: (symbol: string) => ["crypto", "targets", symbol] as const,
  targetHistory: (symbol: string) => ["crypto", "targets", symbol, "history"] as const,
  threshold: (symbol: string, threshold: number, horizon: number) =>
    ["crypto", "threshold", symbol, threshold, horizon] as const,
  onDate: (symbol: string, date: string, threshold: number) =>
    ["crypto", "on-date", symbol, date, threshold] as const,
  preSession: ["crypto", "categories", "pre-session"] as const,
  institutions: (symbol: string) => ["crypto", "categories", "institutions", symbol] as const,
  industry: ["crypto", "categories", "industry"] as const,
};

/** The documented asset catalogue (spec §5). */
export function useCryptoAssets() {
  return useQuery<CryptoAssetsResponse>({
    queryKey: cryptoKeys.assets,
    queryFn: async () => (await CryptoService.getAssets()).data,
    staleTime: 10 * 60_000,
    retry: 1,
  });
}

/** The centralized timeframe registry + per-provider capability report (§9/§10). */
export function useCryptoTimeframes() {
  return useQuery<TimeframesResponse>({
    queryKey: cryptoKeys.timeframes,
    queryFn: async () => (await CryptoService.getTimeframes()).data,
    staleTime: 10 * 60_000,
    retry: 1,
  });
}

/** Configured providers, their roles and last-known health (§52). */
export function useCryptoSources() {
  return useQuery<SourcesResponse>({
    queryKey: cryptoKeys.sources,
    queryFn: async () => (await CryptoService.getSources()).data,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** Latest real quote for one symbol (§6). */
export function useCryptoQuote(symbol: string | undefined) {
  return useQuery<QuotePayload>({
    queryKey: cryptoKeys.quote(symbol ?? ""),
    queryFn: async () => (await CryptoService.getQuote(symbol as string)).data,
    enabled: Boolean(symbol),
    staleTime: 5_000,
    // The socket carries intra-bar updates; REST only reconciles the day stats.
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** Normalized OHLCV history + parse stats + gap report for one timeframe (§7). */
export function useCryptoCandles(
  symbol: string | undefined,
  timeframe: string | undefined,
  limit: number,
  options: { displayPoints?: number; raw?: boolean } = {}
) {
  return useQuery<CandlesResponse>({
    queryKey: cryptoKeys.candles(symbol ?? "", timeframe ?? "", limit),
    queryFn: async () =>
      (
        await CryptoService.getCandles(symbol as string, {
          timeframe,
          limit,
          display_points: options.displayPoints,
          raw: options.raw,
        })
      ).data,
    enabled: Boolean(symbol) && Boolean(timeframe),
    staleTime: 20_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** Indicators + volatility regime + micro-trend for one timeframe (§11/§12/§13). */
export function useCryptoAnalytics(
  symbol: string | undefined,
  timeframe: string | undefined
) {
  return useQuery<AnalyticsResponse>({
    queryKey: cryptoKeys.analytics(symbol ?? "", timeframe ?? ""),
    queryFn: async () => (await CryptoService.getAnalytics(symbol as string, timeframe)).data,
    enabled: Boolean(symbol),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** All timeframes side by side for one symbol (§9). */
export function useCryptoMultiTimeframe(symbol: string | undefined) {
  return useQuery<MultiTimeframeResponse>({
    queryKey: cryptoKeys.multiTimeframe(symbol ?? ""),
    queryFn: async () => (await CryptoService.getMultiTimeframe(symbol as string)).data,
    enabled: Boolean(symbol),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** Cheap last-known provider health (no upstream probe). */
export function useCryptoHealth() {
  return useQuery<CryptoHealthResponse>({
    queryKey: cryptoKeys.health,
    queryFn: async () => (await CryptoService.getHealth()).data,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** Explicit reachability probe against every provider (§52). */
export function useCryptoProbe(enabled: boolean) {
  return useQuery<ProbeResponse>({
    queryKey: cryptoKeys.probe,
    queryFn: async () => (await CryptoService.probeHealth()).data,
    enabled,
    staleTime: 20_000,
    retry: 0,
  });
}

// ---------------------------------------------------------------------------
// Phase 22C — forecasting / targets / thresholds / subcategories
// ---------------------------------------------------------------------------

/**
 * A versioned, validation-backed forecast for one (symbol, timeframe, horizon).
 * Expensive on the server, so it is cached and refreshed on a long interval.
 */
export function useCryptoForecast(
  symbol: string | undefined,
  timeframe: string | undefined,
  horizon: number,
  enabled = true
) {
  return useQuery<ForecastResponse>({
    queryKey: cryptoKeys.forecast(symbol ?? "", timeframe ?? "", horizon),
    queryFn: async () =>
      (await CryptoService.getForecast(symbol as string, { timeframe, horizon })).data,
    enabled: Boolean(symbol) && Boolean(timeframe) && enabled,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** Append-only stored forecast history for one symbol/timeframe. */
export function useCryptoForecastHistory(
  symbol: string | undefined,
  timeframe: string | undefined,
  enabled = false
) {
  return useQuery<ForecastHistoryResponse>({
    queryKey: cryptoKeys.forecastHistory(symbol ?? "", timeframe ?? ""),
    queryFn: async () =>
      (await CryptoService.getForecastHistory(symbol as string, timeframe, 25)).data,
    enabled: Boolean(symbol) && Boolean(timeframe) && enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Real retrospective performance of stored forecasts (not a promise). */
export function useCryptoForecastPerformance(symbol?: string | null) {
  return useQuery<ForecastPerformanceResponse>({
    queryKey: cryptoKeys.performance(symbol ?? null),
    queryFn: async () => (await CryptoService.getForecastPerformance(symbol)).data,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** Active + derived targets, each evaluated against real candles server-side. */
export function useCryptoTargets(symbol: string | undefined) {
  return useQuery<TargetsResponse>({
    queryKey: cryptoKeys.targets(symbol ?? ""),
    queryFn: async () => (await CryptoService.getTargets(symbol as string)).data,
    enabled: Boolean(symbol),
    staleTime: 30_000,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** Historical target touch events (real timestamps). */
export function useCryptoTargetHistory(symbol: string | undefined, enabled = false) {
  return useQuery({
    queryKey: cryptoKeys.targetHistory(symbol ?? ""),
    queryFn: async () => (await CryptoService.getTargetHistory(symbol as string)).data,
    enabled: Boolean(symbol) && enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Modelled probability that the asset is above/below a threshold. */
export function useCryptoThreshold(
  symbol: string | undefined,
  timeframe: string | undefined,
  threshold: number | null,
  horizon: number,
  enabled = true
) {
  return useQuery<ThresholdResponse>({
    queryKey: cryptoKeys.threshold(symbol ?? "", threshold ?? 0, horizon),
    queryFn: async () =>
      (
        await CryptoService.getThreshold(symbol as string, {
          threshold: threshold as number,
          timeframe,
          horizon,
        })
      ).data,
    enabled: Boolean(symbol) && threshold !== null && threshold > 0 && enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Factual "was the asset above X on date Y?" — an observation, or UNAVAILABLE. */
export function useCryptoOnDate(
  symbol: string | undefined,
  date: string | null,
  threshold: number | null,
  enabled = false
) {
  return useQuery<OnDateResponse>({
    queryKey: cryptoKeys.onDate(symbol ?? "", date ?? "", threshold ?? 0),
    queryFn: async () =>
      (
        await CryptoService.getOnDate(symbol as string, {
          date: date as string,
          threshold: threshold ?? undefined,
        })
      ).data,
    enabled: Boolean(symbol) && Boolean(date) && enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

/** Continuous-market session boundaries (never a fake stock-style open). */
export function useCryptoPreSession() {
  return useQuery<PreSessionResponse>({
    queryKey: cryptoKeys.preSession,
    queryFn: async () => (await CryptoService.getPreSession()).data,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** Publicly disclosed institutional holdings (or NO VERIFIED DATA). */
export function useCryptoInstitutions(symbol: string | undefined) {
  return useQuery<InstitutionsResponse>({
    queryKey: cryptoKeys.institutions(symbol ?? ""),
    queryFn: async () => (await CryptoService.getInstitutions(symbol as string)).data,
    enabled: Boolean(symbol),
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

/** Documented industry taxonomy + real provider categories. */
export function useCryptoIndustry() {
  return useQuery<IndustryResponse>({
    queryKey: cryptoKeys.industry,
    queryFn: async () => (await CryptoService.getIndustry()).data,
    staleTime: 10 * 60_000,
    retry: 1,
  });
}
