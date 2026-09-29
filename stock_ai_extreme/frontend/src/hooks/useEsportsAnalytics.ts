/**
 * Phase 21C — React Query hooks for the esports analytics API.
 *
 * Mirrors `useEsportsQueries`: caching, de-duplication and background refresh
 * live here once so no component re-fetches. Analytics payloads are heavier
 * than live feeds, so their `staleTime` is longer and polling slower — the
 * backend recomputes on its own worker cadence (§13) and the client simply
 * follows it.
 */
import { useQuery } from "@tanstack/react-query";

import {
  EsportsAnalyticsService,
  type AnalyticsEngineInfo,
  type DataQualityResponse,
  type MatchAnalytics,
  type ObservabilityResponse,
  type TeamAnalytics,
  type TrendingGamesResponse,
  type TrendingMatchesResponse,
} from "../lib/esportsAnalytics";

export const esportsAnalyticsKeys = {
  engine: ["esports-analytics", "engine"] as const,
  trendingGames: ["esports-analytics", "trending", "games"] as const,
  trendingMatches: (gameId: string | null) => ["esports-analytics", "trending", "matches", gameId ?? "all"] as const,
  team: (teamId: string, gameId: string | null) => ["esports-analytics", "team", teamId, gameId ?? "all"] as const,
  player: (playerId: string) => ["esports-analytics", "player", playerId] as const,
  match: (matchId: string) => ["esports-analytics", "match", matchId] as const,
  dataQuality: (gameId: string | null) => ["esports-analytics", "quality", gameId ?? "all"] as const,
  observability: ["esports-analytics", "observability"] as const,
};

/** §8 — the TRENDING NOW sidebar feed (backend-ranked, cached 60s server-side). */
export function useTrendingGames() {
  return useQuery<TrendingGamesResponse>({
    queryKey: esportsAnalyticsKeys.trendingGames,
    queryFn: () => EsportsAnalyticsService.getTrendingGames(),
    staleTime: 60_000,
    refetchInterval: 90_000,
    retry: 1,
  });
}

/** §9 — trending matches ranked by measured activity, not a hardcoded list. */
export function useTrendingMatches(gameId?: string | null, limit = 8) {
  return useQuery<TrendingMatchesResponse>({
    queryKey: esportsAnalyticsKeys.trendingMatches(gameId ?? null),
    queryFn: () => EsportsAnalyticsService.getTrendingMatches(gameId ?? null, limit),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** §1–§4 — team analytics (form, maps, durations) with sample sizes. */
export function useTeamAnalytics(teamId: string | null | undefined, gameId?: string | null) {
  return useQuery<TeamAnalytics>({
    queryKey: esportsAnalyticsKeys.team(teamId ?? "", gameId ?? null),
    queryFn: () => EsportsAnalyticsService.getTeamAnalytics(teamId as string, gameId ?? null),
    enabled: Boolean(teamId),
    staleTime: 120_000,
    retry: 1,
  });
}

/** §5 — player analytics in the game's own metric schema. */
export function usePlayerAnalytics(playerId: string | null | undefined) {
  return useQuery<PlayerAnalyticsPayloadLike>({
    queryKey: esportsAnalyticsKeys.player(playerId ?? ""),
    queryFn: () => EsportsAnalyticsService.getPlayerAnalytics(playerId as string),
    enabled: Boolean(playerId),
    staleTime: 120_000,
    retry: 1,
  });
}

/** §10 — match analytics with labelled anomaly detection. */
export function useMatchAnalytics(matchId: string | null | undefined) {
  return useQuery<MatchAnalytics>({
    queryKey: esportsAnalyticsKeys.match(matchId ?? ""),
    queryFn: () => EsportsAnalyticsService.getMatchAnalytics(matchId as string),
    enabled: Boolean(matchId),
    staleTime: 60_000,
    refetchInterval: 180_000,
    retry: 1,
  });
}

/** §11/§12 — the data-quality feed and source discrepancies. */
export function useDataQuality(gameId?: string | null, limit = 50) {
  return useQuery<DataQualityResponse>({
    queryKey: esportsAnalyticsKeys.dataQuality(gameId ?? null),
    queryFn: () => EsportsAnalyticsService.getDataQuality(gameId ?? null, limit),
    staleTime: 60_000,
    refetchInterval: 180_000,
    retry: 1,
  });
}

/** §17 — live pipeline observability (latencies, rates, clients). */
export function useObservability() {
  return useQuery<ObservabilityResponse>({
    queryKey: esportsAnalyticsKeys.observability,
    queryFn: () => EsportsAnalyticsService.getObservability(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** §7 — the engine contract itself (weights/schemas for display). */
export function useAnalyticsEngine() {
  return useQuery<AnalyticsEngineInfo>({
    queryKey: esportsAnalyticsKeys.engine,
    queryFn: () => EsportsAnalyticsService.getEngine(),
    staleTime: 300_000,
    retry: 1,
  });
}

// The player endpoint returns null-ish payloads as 404; the query layer treats
// that as "no data" rather than an error state.
export type PlayerAnalyticsPayloadLike = Awaited<ReturnType<typeof EsportsAnalyticsService.getPlayerAnalytics>>;
