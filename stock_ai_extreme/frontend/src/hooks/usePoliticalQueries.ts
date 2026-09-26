/**
 * Phase 18 — React Query hooks for the political/geopolitical module.
 *
 * Screens read server state only through these hooks, so caching, retries and
 * loading/error handling are defined once. `retry: 0` is deliberate: a source
 * being down is reported honestly by the backend, it is not something a retry
 * storm fixes.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PoliticalService,
  type MeasurementType,
  type PoliticalCategory,
  type RegionDataState,
} from "../lib/political";

export const politicalKeys = {
  meta: ["political", "meta"] as const,
  sources: ["political", "sources"] as const,
  overview: (electionId?: string) => ["political", "overview", electionId ?? "ALL"] as const,
  regions: (state?: RegionDataState) => ["political", "regions", state ?? "ALL"] as const,
  regionDetail: (regionId: string, electionId?: string) => ["political", "region", regionId, electionId ?? "ALL"] as const,
  events: (country?: string, sourceId?: string, upcomingOnly?: boolean) =>
    ["political", "events", country ?? "ALL", sourceId ?? "ALL", upcomingOnly ?? false] as const,
  measurements: (regionId?: string, electionId?: string, type?: MeasurementType, sourceId?: string) =>
    ["political", "measurements", regionId ?? "ALL", electionId ?? "ALL", type ?? "ALL", sourceId ?? "ALL"] as const,
  headToHead: (electionId?: string, regionId?: string) =>
    ["political", "head-to-head", electionId ?? "ALL", regionId ?? "ALL"] as const,
  timeline: (hours: number, category?: PoliticalCategory, country?: string) =>
    ["political", "timeline", hours, category ?? "ALL", country ?? "ALL"] as const,
};

export function usePoliticalMeta() {
  return useQuery({
    queryKey: politicalKeys.meta,
    queryFn: () => PoliticalService.getMeta(),
    staleTime: 30 * 60_000,
    retry: 0,
  });
}

export function usePoliticalSources() {
  return useQuery({
    queryKey: politicalKeys.sources,
    queryFn: () => PoliticalService.getSources(),
    staleTime: 60_000,
    retry: 0,
  });
}

export function usePoliticalOverview(electionId?: string) {
  return useQuery({
    queryKey: politicalKeys.overview(electionId),
    queryFn: () => PoliticalService.getOverview(electionId),
    staleTime: 5 * 60_000,
    retry: 0,
  });
}

export function usePoliticalRegions(state?: RegionDataState) {
  return useQuery({
    queryKey: politicalKeys.regions(state),
    queryFn: () => PoliticalService.getRegions(state),
    staleTime: 5 * 60_000,
    retry: 0,
  });
}

export function usePoliticalRegionDetail(regionId: string | null, electionId?: string) {
  return useQuery({
    queryKey: politicalKeys.regionDetail(regionId ?? "NONE", electionId),
    queryFn: () => PoliticalService.getRegionDetail(regionId as string, electionId),
    enabled: Boolean(regionId),
    staleTime: 2 * 60_000,
    retry: 0,
  });
}

export function usePoliticalEvents(options: { country?: string; sourceId?: string; upcomingOnly?: boolean } = {}) {
  return useQuery({
    queryKey: politicalKeys.events(options.country, options.sourceId, options.upcomingOnly),
    queryFn: () => PoliticalService.getEvents(options),
    staleTime: 5 * 60_000,
    retry: 0,
  });
}

export function usePoliticalMeasurements(filters: {
  regionId?: string; electionId?: string; measurementType?: MeasurementType; sourceId?: string;
} = {}) {
  return useQuery({
    queryKey: politicalKeys.measurements(filters.regionId, filters.electionId, filters.measurementType, filters.sourceId),
    queryFn: () => PoliticalService.getMeasurements(filters),
    staleTime: 2 * 60_000,
    retry: 0,
  });
}

export function useHeadToHead(electionId?: string, regionId?: string) {
  return useQuery({
    queryKey: politicalKeys.headToHead(electionId, regionId),
    queryFn: () => PoliticalService.getHeadToHead(electionId, regionId),
    enabled: Boolean(electionId || regionId),
    staleTime: 2 * 60_000,
    retry: 0,
  });
}

export function usePoliticalTimeline(hours = 72, category?: PoliticalCategory, country?: string) {
  return useQuery({
    queryKey: politicalKeys.timeline(hours, category, country),
    queryFn: () => PoliticalService.getTimeline({ hours, limit: 80, category, country }),
    staleTime: 3 * 60_000,
    retry: 0,
  });
}

/** Force a full provider re-fetch and invalidate every political query. */
export function usePoliticalRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => PoliticalService.refresh(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["political"] }),
  });
}
