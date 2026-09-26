/**
 * Phase 19 — discovery React Query hooks.
 *
 * The only place components read discovery server state: caching,
 * de-duplication, retries, background refresh and loading/error states are
 * handled once here (spec §15 — client caching; mode switches never require a
 * full page reload, spec §9).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DiscoveryService,
  type DiscoveryFeed,
  type DiscoveryEngineMeta,
  type DiscoveryQueryParams,
  type DiscoveryTaxonomy,
  type TrendHistory,
} from "../lib/discovery";

export const discoveryKeys = {
  feed: (params: DiscoveryQueryParams) => ["discovery", "feed", params] as const,
  taxonomy: ["discovery", "taxonomy"] as const,
  engine: ["discovery", "engine"] as const,
  history: (entityId: string, hours?: number) => ["discovery", "history", entityId, hours ?? null] as const,
};

/**
 * One discovery feed. `placeholderData: keepPreviousData` keeps the current
 * cards on screen while the next mode/filter page loads, so switching
 * Trending → New never blanks the grid (spec §9: no full reload).
 */
export function useDiscoveryFeed(params: DiscoveryQueryParams) {
  return useQuery<DiscoveryFeed>({
    queryKey: discoveryKeys.feed(params),
    queryFn: () => DiscoveryService.getFeed(params),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

/** Categories + sub-tags with live counts (spec §6, §13). */
export function useDiscoveryTaxonomy() {
  return useQuery<DiscoveryTaxonomy>({
    queryKey: discoveryKeys.taxonomy,
    queryFn: () => DiscoveryService.getTaxonomy(),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 1,
  });
}

/** The scoring contract (weights/saturations) — rarely changes. */
export function useDiscoveryEngineMeta() {
  return useQuery<DiscoveryEngineMeta>({
    queryKey: discoveryKeys.engine,
    queryFn: () => DiscoveryService.getEngineMeta(),
    staleTime: 10 * 60_000,
    retry: 1,
  });
}

/**
 * Trend observations for one entity's sparkline. Only enabled while the card
 * is asking for it, so a 24-card grid issues its history requests once and
 * then reuses the cache for the refetch window.
 */
export function useTrendHistory(entityId: string, options: { enabled?: boolean } = {}) {
  return useQuery<TrendHistory>({
    queryKey: discoveryKeys.history(entityId),
    queryFn: () => DiscoveryService.getTrendHistory(entityId),
    enabled: Boolean(entityId) && options.enabled !== false,
    staleTime: 120_000,
    refetchInterval: 300_000,
    retry: 0,
  });
}

/** Record one real interest event (best-effort, never blocks navigation). */
export function useRecordDiscoveryEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entityId, kind }: { entityId: string; kind?: "view" | "search" }) =>
      DiscoveryService.recordEvent(entityId, kind ?? "view"),
    onSuccess: () => {
      // Interest counts feed the POPULAR/TRENDING scores — refresh them on the
      // next read instead of hammering the feed now.
      queryClient.invalidateQueries({ queryKey: ["discovery", "feed"] });
    },
    retry: 0,
  });
}
