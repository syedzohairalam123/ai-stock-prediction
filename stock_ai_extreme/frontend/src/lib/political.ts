/**
 * Phase 18 — Political & Geopolitical Data Mapping / Forecast Visualization.
 *
 * Data-access layer, mirroring the backend contract 1:1 so the UI never
 * touches transport details and the official sources can be swapped without
 * changing a single component.
 *
 * Neutrality is enforced by construction here too:
 *   * every measurement carries `source`, `measured_at`, `measurement_type`;
 *   * `MEASUREMENT_TYPE_META` maps those types to labels — never merged;
 *   * `REGION_STATE_META` maps a region's DATA-AVAILABILITY state to a colour,
 *     and none of those colours is a political/party colour.
 */
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// enums (identical to the backend)
// ---------------------------------------------------------------------------

export type MeasurementType = "POLL" | "FORECAST" | "MODEL" | "HISTORICAL_RESULT";
export type RegionDataState = "AVAILABLE" | "NO_DATA" | "OUTDATED" | "CONTESTED" | "RESOLVED";
export type SourceStatus = "OK" | "DEGRADED" | "UNAVAILABLE" | "DISABLED";
export type PoliticalCategory =
  | "ELECTION" | "REFERENDUM" | "GOVERNMENT" | "INTERNATIONAL"
  | "POLICY" | "CONFLICT" | "OTHER";

// ---------------------------------------------------------------------------
// shapes
// ---------------------------------------------------------------------------

export interface SourceInfo {
  id: string;
  name: string;
  kind: string;
  source_url: string | null;
  description: string;
  attribution: string | null;
  status: SourceStatus;
  capabilities: string[];
  last_fetch_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_errors: number;
  fetch_count: number;
  requires_key: boolean;
  key_configured: boolean;
}

export interface ProviderReport {
  provider_id: string;
  ok: boolean;
  status: SourceStatus;
  items: number;
  duration_ms: number | null;
  error: string | null;
}

export interface RetrievalMeta {
  generated_at: string;
  providers: ProviderReport[];
  cache: string;
}

export interface GeometryRef {
  format: string;
  provider: string;
  location_mode: string;
  location_key: string | null;
  reference_url: string | null;
}

export interface PopulationContext {
  population: number | null;
  as_of: string | null;
  source: string | null;
  source_url: string | null;
  note: string | null;
}

export interface PoliticalRegion {
  id: string;
  name: string;
  country: string;
  country_name: string;
  state_code: string | null;
  fips_code: string | null;
  geometry: GeometryRef;
  population_context: PopulationContext | null;
  source: string;
  source_url: string | null;
  region_type: "STATE" | "DISTRICT" | "COUNTRY";
}

export interface RegionStateDetail {
  region_id: string;
  state: RegionDataState;
  reason: string | null;
  election_id: string | null;
  measurement_count: number;
  source_ids: string[];
  last_measurement_at: string | null;
  /** Present on `/overview` (RegionStatusSchema), absent on `/regions`. */
  last_measured_by?: string | null;
  measurement_types?: MeasurementType[];
}

export interface Uncertainty {
  kind: string;
  low: number | null;
  high: number | null;
  margin: number | null;
  level: number | null;
  unit: string;
  raw: string | null;
}

export interface ForecastMeasurement {
  id: string;
  region_id: string | null;
  election_id: string | null;
  candidate_or_outcome: string;
  probability: number | null;
  measurement_type: MeasurementType;
  source: string;
  source_id: string;
  source_url: string | null;
  measured_at: string | null;
  updated_at: string | null;
  retrieved_at: string | null;
  methodology: string | null;
  population: string | null;
  sample_size: number | null;
  uncertainty: Uncertainty | null;
  activity: Record<string, unknown> | null;
  is_current: boolean;
  notes: string | null;
}

export interface PoliticalEvent {
  id: string;
  name: string;
  jurisdiction: string | null;
  jurisdiction_type: string | null;
  election_date: string | null;
  election_date_basis: string | null;
  category: PoliticalCategory;
  source: string;
  source_id: string;
  source_url: string | null;
  updated_at: string | null;
  retrieved_at: string | null;
  status: string;
  office: string | null;
  election_id: string | null;
  country: string;
  region_ids: string[];
  notes: string | null;
}

export interface TimelineEvent {
  id: string;
  timestamp: string;
  title: string;
  url: string | null;
  source: string;
  source_url: string | null;
  category: PoliticalCategory;
  classification_basis: string;
  location: string | null;
  location_basis: string | null;
  affected_regions: string[];
  language: string | null;
  notes: string | null;
}

export interface MeasurementBundle {
  region_id: string | null;
  election_id: string | null;
  measurements: ForecastMeasurement[];
  by_type: Record<string, ForecastMeasurement[]>;
  sources_disagree: boolean;
  conflict_note: string | null;
  disclaimer: string;
}

export interface PoliticalMeta {
  measurement_types: MeasurementType[];
  region_states: RegionDataState[];
  categories: PoliticalCategory[];
  freshness_window_days: number;
  stale_after_days: number;
  conflict_threshold: number;
  geometry_sources: Record<string, string>[];
  neutrality: Record<string, string>;
}

export interface OverviewResponse {
  generated_at: string;
  events: PoliticalEvent[];
  regions: PoliticalRegion[];
  region_states: RegionStateDetail[];
  measurements: ForecastMeasurement[];
  sources: SourceInfo[];
  election_ids: string[];
  retrieval: RetrievalMeta;
  neutrality: Record<string, string>;
  disclaimer: string;
}

export interface RegionsResponse {
  regions: PoliticalRegion[];
  region_states: RegionStateDetail[];
  retrieval: RetrievalMeta;
}

export interface RegionDetailResponse {
  region: PoliticalRegion;
  state: RegionStateDetail;
  measurements: MeasurementBundle;
  events: PoliticalEvent[];
  timeline: TimelineEvent[];
  historical: ForecastMeasurement[];
  retrieval: RetrievalMeta;
}

export interface EventsResponse {
  events: PoliticalEvent[];
  meta: Record<string, unknown>;
  retrieval: RetrievalMeta;
}

export interface MeasurementsResponse {
  measurements: ForecastMeasurement[];
  by_type: Record<string, ForecastMeasurement[]>;
  meta: Record<string, unknown>;
  retrieval: RetrievalMeta;
}

export interface HeadToHeadResponse {
  election_id: string | null;
  region_id: string | null;
  title: string;
  rows: ForecastMeasurement[];
  grouped_by_source: Record<string, ForecastMeasurement[]>;
  note: string;
  disclaimer: string;
  retrieval: RetrievalMeta;
}

export interface TimelineResponse {
  events: TimelineEvent[];
  meta: Record<string, unknown>;
  retrieval: RetrievalMeta;
}

export interface SourcesResponse {
  sources: SourceInfo[];
  summary: Record<string, number>;
  generated_at: string;
}

export interface PoliticalFilters {
  electionId?: string;
  country?: string;
  regionId?: string;
  dateFrom?: string;
  dateTo?: string;
  sourceId?: string;
  measurementType?: MeasurementType;
}

// ---------------------------------------------------------------------------
// presentation metadata (labels + *data-state* colours — never party colours)
// ---------------------------------------------------------------------------

export const MEASUREMENT_TYPE_META: Record<MeasurementType, { label: string; blurb: string }> = {
  POLL: { label: "Poll", blurb: "Opinion survey as published by the pollster." },
  FORECAST: { label: "Forecast", blurb: "A forecaster's published estimate." },
  MODEL: { label: "Model", blurb: "A model or market-implied estimate." },
  HISTORICAL_RESULT: { label: "Historical result", blurb: "A certified past outcome." },
};

/**
 * Colour encodes **data availability only**. This is deliberate: no red/blue
 * party palette exists anywhere in this module, so the map cannot be read as a
 * partisan projection even by accident.
 */
export const REGION_STATE_META: Record<RegionDataState, { label: string; color: string; blurb: string }> = {
  AVAILABLE: { label: "Available", color: "#2dd4bf", blurb: "A current sourced measurement exists." },
  NO_DATA: { label: "No data", color: "#3b4a63", blurb: "No external source currently provides data." },
  OUTDATED: { label: "Outdated", color: "#f59e0b", blurb: "Sourced data exists but is older than the freshness window." },
  CONTESTED: { label: "Contested", color: "#a78bfa", blurb: "Two or more sources disagree; both are shown." },
  RESOLVED: { label: "Resolved", color: "#22c55e", blurb: "Only historical / resolved sourced data exists." },
};

export const CATEGORY_META: Record<PoliticalCategory, { label: string; icon: string }> = {
  ELECTION: { label: "Election", icon: "🗳️" },
  REFERENDUM: { label: "Referendum", icon: "📜" },
  GOVERNMENT: { label: "Government", icon: "🏛️" },
  INTERNATIONAL: { label: "International", icon: "🌍" },
  POLICY: { label: "Policy", icon: "⚖️" },
  CONFLICT: { label: "Conflict", icon: "⚠️" },
  OTHER: { label: "Other", icon: "•" },
};

/** Stable z-ordering for the choropleth so the legend and map agree. */
export const REGION_STATE_ORDER: RegionDataState[] = [
  "AVAILABLE", "CONTESTED", "OUTDATED", "RESOLVED", "NO_DATA",
];

export function regionStateColor(state: RegionDataState): string {
  return REGION_STATE_META[state]?.color ?? REGION_STATE_META.NO_DATA.color;
}

// ---------------------------------------------------------------------------
// small formatters
// ---------------------------------------------------------------------------

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "date unavailable";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unavailable";
  return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "unknown";
  const ms = Date.now() - new Date(value).getTime();
  if (Number.isNaN(ms)) return "unknown";
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export function uncertaintyLabel(uncertainty: Uncertainty | null | undefined): string | null {
  if (!uncertainty) return null;
  const parts: string[] = [];
  if (uncertainty.kind) parts.push(uncertainty.kind.replace(/_/g, " "));
  if (uncertainty.low !== null && uncertainty.high !== null) {
    parts.push(`${uncertainty.low}–${uncertainty.high}`);
  }
  if (uncertainty.margin !== null) parts.push(`±${uncertainty.margin}`);
  if (uncertainty.level !== null) parts.push(`level ${uncertainty.level}`);
  if (uncertainty.raw) parts.push(`“${uncertainty.raw}”`);
  return parts.length ? parts.join(" · ") : null;
}

/** Compact, source-explicit activity summary (volumes etc. relayed verbatim). */
export function activityLabel(activity: Record<string, unknown> | null | undefined): string | null {
  if (!activity) return null;
  const parts: string[] = [];
  if (typeof activity.volume_usd === "number") parts.push(`volume $${(activity.volume_usd as number).toLocaleString()}`);
  if (typeof activity.liquidity_usd === "number") parts.push(`liquidity $${(activity.liquidity_usd as number).toLocaleString()}`);
  if (typeof activity.total_votes_cast === "number") parts.push(`${(activity.total_votes_cast as number).toLocaleString()} votes cast`);
  return parts.length ? parts.join(" · ") : null;
}

// ---------------------------------------------------------------------------
// service
// ---------------------------------------------------------------------------

const BASE = "/political";

export const PoliticalService = {
  async getMeta(): Promise<PoliticalMeta> {
    return (await apiClient.get<PoliticalMeta>(`${BASE}/meta`)).data;
  },

  async getSources(): Promise<SourcesResponse> {
    return (await apiClient.get<SourcesResponse>(`${BASE}/sources`)).data;
  },

  async getOverview(electionId?: string, refresh = false): Promise<OverviewResponse> {
    const params = new URLSearchParams();
    if (electionId) params.set("election_id", electionId);
    if (refresh) params.set("refresh", "true");
    const query = params.toString();
    return (await apiClient.get<OverviewResponse>(`${BASE}/overview${query ? `?${query}` : ""}`)).data;
  },

  async getRegions(state?: RegionDataState): Promise<RegionsResponse> {
    const query = state ? `?state=${state}` : "";
    return (await apiClient.get<RegionsResponse>(`${BASE}/regions${query}`)).data;
  },

  async getRegionDetail(regionId: string, electionId?: string): Promise<RegionDetailResponse> {
    const params = new URLSearchParams();
    if (electionId) params.set("election_id", electionId);
    const query = params.toString();
    return (await apiClient.get<RegionDetailResponse>(
      `${BASE}/regions/${encodeURIComponent(regionId)}${query ? `?${query}` : ""}`,
    )).data;
  },

  async getEvents(filters: PoliticalFilters & { upcomingOnly?: boolean } = {}): Promise<EventsResponse> {
    const params = new URLSearchParams();
    if (filters.country) params.set("country", filters.country);
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    if (filters.sourceId) params.set("source_id", filters.sourceId);
    if (filters.upcomingOnly) params.set("upcoming_only", "true");
    const query = params.toString();
    return (await apiClient.get<EventsResponse>(`${BASE}/events${query ? `?${query}` : ""}`)).data;
  },

  async getMeasurements(filters: PoliticalFilters = {}): Promise<MeasurementsResponse> {
    const params = new URLSearchParams();
    if (filters.regionId) params.set("region_id", filters.regionId);
    if (filters.electionId) params.set("election_id", filters.electionId);
    if (filters.measurementType) params.set("measurement_type", filters.measurementType);
    if (filters.sourceId) params.set("source_id", filters.sourceId);
    const query = params.toString();
    return (await apiClient.get<MeasurementsResponse>(`${BASE}/measurements${query ? `?${query}` : ""}`)).data;
  },

  async getHeadToHead(electionId?: string, regionId?: string): Promise<HeadToHeadResponse> {
    const params = new URLSearchParams();
    if (electionId) params.set("election_id", electionId);
    if (regionId) params.set("region_id", regionId);
    const query = params.toString();
    return (await apiClient.get<HeadToHeadResponse>(`${BASE}/head-to-head${query ? `?${query}` : ""}`)).data;
  },

  async getTimeline(paramsIn: { hours?: number; limit?: number; category?: PoliticalCategory; country?: string; regionId?: string } = {}): Promise<TimelineResponse> {
    const params = new URLSearchParams();
    if (paramsIn.hours) params.set("hours", String(paramsIn.hours));
    if (paramsIn.limit) params.set("limit", String(paramsIn.limit));
    if (paramsIn.category) params.set("category", paramsIn.category);
    if (paramsIn.country) params.set("country", paramsIn.country);
    if (paramsIn.regionId) params.set("region_id", paramsIn.regionId);
    const query = params.toString();
    return (await apiClient.get<TimelineResponse>(`${BASE}/timeline${query ? `?${query}` : ""}`)).data;
  },

  async refresh(): Promise<Record<string, unknown>> {
    return (await apiClient.post(`${BASE}/refresh`)).data;
  },
};

/** Convenience: build a lookup from region id -> state detail. */
export function stateByRegionId(regionStates: RegionStateDetail[]): Map<string, RegionStateDetail> {
  return new Map(regionStates.map((s) => [s.region_id, s]));
}
