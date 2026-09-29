/**
 * Phase 21B — esports React Query hooks.
 *
 * The only place components read esports server state. Caching, de-duplication,
 * background refresh and loading/error states are handled once here, so a game
 * filter change or route navigation never blanks the page (§9, §25, §26).
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import {
  EsportsService,
  type FeaturedResponse,
  type GamesSummaryResponse,
  type MatchDetail,
  type MatchFeedParams,
  type MatchFeedResponse,
  type TournamentDetail,
} from "../lib/esports";

export const esportsKeys = {
  games: ["esports", "games"] as const,
  summary: ["esports", "games", "summary"] as const,
  gameSummary: (gameId: string) => ["esports", "games", gameId, "summary"] as const,
  featured: (gameId: string | null) => ["esports", "featured", gameId ?? "all"] as const,
  feed: (params: MatchFeedParams) => ["esports", "feed", params] as const,
  match: (matchId: string) => ["esports", "match", matchId] as const,
  tournament: (tournamentId: string) => ["esports", "tournament", tournamentId] as const,
  sources: ["esports", "sources"] as const,
  gameTournaments: (gameId: string) => ["esports", "games", gameId, "tournaments"] as const,
};

/** Per-game activity cards (§5). */
export function useGamesSummary() {
  return useQuery<GamesSummaryResponse>({
    queryKey: esportsKeys.summary,
    queryFn: () => EsportsService.getGamesSummary(),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** The backend's featured-match ranking (§3) — the UI follows the backend. */
export function useFeaturedMatch(gameId?: string | null) {
  return useQuery<FeaturedResponse>({
    queryKey: esportsKeys.featured(gameId ?? null),
    queryFn: () => EsportsService.getFeatured(gameId ?? null),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** The cross-game match feed with server-side filtering (§6, §24). */
export function useMatchFeed(params: MatchFeedParams) {
  return useQuery<MatchFeedResponse>({
    queryKey: esportsKeys.feed(params),
    queryFn: () => EsportsService.getMatches(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** Full live-match payload (§11). */
export function useMatchDetail(matchId: string | undefined) {
  return useQuery<MatchDetail>({
    queryKey: esportsKeys.match(matchId ?? ""),
    queryFn: () => EsportsService.getMatchDetail(matchId as string),
    enabled: Boolean(matchId),
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 1,
  });
}

/** One tournament plus its real related matches (§14). */
export function useTournamentDetail(tournamentId: string | undefined) {
  return useQuery<TournamentDetail>({
    queryKey: esportsKeys.tournament(tournamentId ?? ""),
    queryFn: () => EsportsService.getTournament(tournamentId as string),
    enabled: Boolean(tournamentId),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** Per-provider data-source status (§15). */
export function useEsportsSources() {
  return useQuery({
    queryKey: esportsKeys.sources,
    queryFn: () => EsportsService.getSources(),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** Tournaments for one game (used by the hub's game view). */
export function useGameTournaments(gameId: string | undefined) {
  return useQuery({
    queryKey: esportsKeys.gameTournaments(gameId ?? ""),
    queryFn: () => EsportsService.getGameTournaments(gameId as string),
    enabled: Boolean(gameId),
    staleTime: 120_000,
    retry: 1,
  });
}
