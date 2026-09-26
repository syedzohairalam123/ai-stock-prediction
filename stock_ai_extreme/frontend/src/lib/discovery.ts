/**
 * Phase 19 — Advanced Market Discovery data layer.
 *
 * One typed client for every `/api/discover*` endpoint (spec §9–§15). The
 * rules this file mirrors from the backend contract:
 *
 *  - `null` everywhere means N/A. A metric no source published is `null` and
 *    must render as "N/A" — never as 0, never as a placeholder.
 *  - Every score ships its components, the weights actually used, and the
 *    signals that were missing, so the UI can explain itself.
 *  - Nothing here fabricates a number; formatting only.
 */
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// Types (mirror the backend contract field for field)
// ---------------------------------------------------------------------------

export type DiscoveryMode = "trending" | "new" | "popular" | "recent";

export type EntityType =
  | "stock"
  | "index"
  | "crypto"
  | "commodity"
  | "forex"
  | "news_topic"
  | "forecast_event";

export interface ActivityMetric {
  label: string;
  value: number | null;
  unit?: string | null;
  as_of?: string | null;
  note?: string | null;
}

export interface ScoreBlock {
  score: number | null;
  components: Record<string, number | null>;
  weightsUsed: Record<string, number>;
  missing: string[];
  unknown?: string[];
}

export interface EntityInterest {
  view: number;
  search: number;
  watchlist: number;
  total: number;
}

export interface PersonalSignals {
  watchlist: boolean;
  recentlyViewed: boolean;
  preferredCategory: boolean;
}

export interface DiscoverableEntity {
  id: string;
  type: EntityType;
  name: string;
  symbol: string | null;
  category: string;
  tags: string[];
  createdAt: string | null;
  updatedAt: string | null;
  activity: ActivityMetric | null;
  source: string;
  dataMode: "LIVE" | "DELAYED" | "DEMO" | "UNAVAILABLE";
  status: string;
  route: string | null;
  provenance: Record<string, unknown> | null;
  trend: ScoreBlock;
  popularity: ScoreBlock;
  scoreComponents: Record<string, number | null>;
  signals: Record<string, unknown>;
  interest: EntityInterest;
  personal: PersonalSignals;
  /** Present only when the request asked for personalization. */
  personalized?: boolean;
  /** Rank actually used for sorting (score × boost) — disclosed, not hidden. */
  rankScore?: number | null;
  personalBoostApplied?: boolean;
}

export interface SourceReport {
  source: string;
  status: "OK" | "DEGRADED" | "UNAVAILABLE";
  count: number;
  requested: number | null;
  failed: string[];
  reason: string | null;
  checkedAt: string;
}

export interface EngineMeta {
  trendWeights: Record<string, number>;
  popularityWeights: Record<string, number>;
  recencyHalfLifeHours: number;
  saturations: Record<string, number>;
  note: string;
}

export interface PersonalizationMeta {
  enabled: boolean;
  signals: string[];
  boost: number;
  note: string;
}

export interface DiscoveryFeed {
  mode: DiscoveryMode;
  items: DiscoverableEntity[];
  total: number;
  offset: number;
  limit: number;
  hasMore: boolean;
  generatedAt: string;
  sources: SourceReport[];
  engine: EngineMeta;
  filters: Record<string, string | null>;
  personalization: PersonalizationMeta;
  excludedNoCreatedAt: number;
  recordedSearches: number;
  sampledObservations: number;
  notes: string[];
}

export interface TaxonomyCategory {
  name: string;
  count: number;
}

export interface TaxonomyTag {
  name: string;
  count: number;
  categories: string[];
}

export interface DiscoveryTaxonomy {
  categories: TaxonomyCategory[];
  tags: TaxonomyTag[];
  generatedAt: string;
  sources: SourceReport[];
  note: string;
}

export interface TrendPoint {
  timestamp: string;
  activity: number | null;
  score: number | null;
  popularity?: number | null;
  source?: string;
}

export interface TrendAnalytics {
  count: number;
  available: boolean;
  reason: string | null;
  activitySeries: (number | null)[];
  scoreSeries: (number | null)[];
  scoreEma: (number | null)[];
  slopePerHour: number | null;
  accelerationPerHour2: number | null;
  zscore: number | null;
  anomaly: boolean;
  direction: "RISING" | "FALLING" | "STABLE";
  note?: string;
}

export interface TrendHistory {
  entityId: string;
  entity: DiscoverableEntity | null;
  hours: number;
  seriesSource: "sampled_observations" | "news_timeline" | null;
  points: TrendPoint[];
  analytics: TrendAnalytics;
  generatedAt: string;
  note: string;
}

export interface DiscoveryEngineMeta extends EngineMeta {
  feedModes: DiscoveryMode[];
  entityTypes: EntityType[];
  categories: string[];
  observationSampleIntervalSeconds: number;
  velocityLookbackHours: number;
  personalization: PersonalizationMeta;
}

// ---------------------------------------------------------------------------
// Query parameters
// ---------------------------------------------------------------------------

export interface DiscoveryQueryParams {
  mode: DiscoveryMode;
  category?: string | null;
  tag?: string | null;
  type?: EntityType | null;
  status?: string | null;
  source?: string | null;
  since?: string | null;
  q?: string | null;
  limit?: number;
  offset?: number;
  personalize?: boolean;
  prefer?: string[];
  refresh?: boolean;
}

function buildParams(params: DiscoveryQueryParams): Record<string, string | number | boolean> {
  const query: Record<string, string | number | boolean> = { mode: params.mode };
  if (params.category) query.category = params.category;
  if (params.tag) query.tag = params.tag;
  if (params.type) query.type = params.type;
  if (params.status) query.status = params.status;
  if (params.source) query.source = params.source;
  if (params.since) query.since = params.since;
  if (params.q) query.q = params.q;
  if (params.limit) query.limit = params.limit;
  if (params.offset) query.offset = params.offset;
  if (params.personalize) query.personalize = true;
  if (params.prefer?.length) query.prefer = params.prefer.join(",");
  if (params.refresh) query.refresh = true;
  return query;
}

// ---------------------------------------------------------------------------
// Service — the only place discovery URLs live
// ---------------------------------------------------------------------------

export const DiscoveryService = {
  /** One feed (trending / new / popular / recent) with filters + paging. */
  async getFeed(params: DiscoveryQueryParams): Promise<DiscoveryFeed> {
    const res = await apiClient.get<DiscoveryFeed>("/api/discover", { params: buildParams(params) });
    return res.data;
  },

  /** Live category + sub-tag navigation with real entity counts. */
  async getTaxonomy(): Promise<DiscoveryTaxonomy> {
    const res = await apiClient.get<DiscoveryTaxonomy>("/api/discover/taxonomy");
    return res.data;
  },

  /** The scoring contract: weights, saturations, honesty notes. */
  async getEngineMeta(): Promise<DiscoveryEngineMeta> {
    const res = await apiClient.get<DiscoveryEngineMeta>("/api/discover/engine");
    return res.data;
  },

  /** Stored trend observations + explainable analytics for one entity. */
  async getTrendHistory(entityId: string, hours?: number): Promise<TrendHistory> {
    const res = await apiClient.get<TrendHistory>(
      `/api/discover/trends/${encodeURIComponent(entityId)}`,
      { params: hours ? { hours } : undefined }
    );
    return res.data;
  },

  /**
   * Record one real interest event (the card was opened / matched). Fire and
   * forget — a failed recording must never block navigation, and the backend
   * reports `recorded: false` rather than pretending.
   */
  async recordEvent(entityId: string, kind: "view" | "search" = "view"): Promise<void> {
    try {
      await apiClient.post("/api/discover/events", { entityId, kind });
    } catch {
      /* intentionally silent: interest tracking is best-effort */
    }
  },
};

// ---------------------------------------------------------------------------
// Display helpers (formatting only — no invented values)
// ---------------------------------------------------------------------------

export const ENTITY_LABELS: Record<EntityType, string> = {
  stock: "Stock",
  index: "Index",
  crypto: "Crypto",
  commodity: "Commodity",
  forex: "Forex",
  news_topic: "News topic",
  forecast_event: "Forecast event",
};

export const MODE_LABELS: Record<DiscoveryMode, string> = {
  trending: "Trending",
  new: "New",
  popular: "Popular",
  recent: "Recently updated",
};

export const MODE_DESCRIPTIONS: Record<DiscoveryMode, string> = {
  trending: "Ranked by the transparent trend score over real activity, velocity and recency.",
  new: "Entities with a genuine creation timestamp — nothing is dressed up as new.",
  popular: "Ranked by interest this app actually recorded: views, searches and watchlist saves.",
  recent: "Ordered by the newest real update timestamp from each source.",
};

export const SIGNAL_LABELS: Record<string, string> = {
  recency: "Recency",
  activity: "Activity",
  velocity: "Velocity",
  interest: "Interest",
  news: "News",
};

/** "N/A" for every missing metric — the honest rendering of `null`. */
export const NA = "N/A";

export function relTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return NA;
  const diff = Date.now() - then;
  if (diff < 0) return "just now";
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Format an activity value with its unit; `null` → "N/A". */
export function formatActivity(activity: ActivityMetric | null | undefined): string {
  if (!activity || activity.value === null || activity.value === undefined) return NA;
  const { value, unit } = activity;
  if (unit === "%") return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  if (unit === "USD") return `$${Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`;
  if (unit === "traders") return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
  if (Number.isInteger(value)) return Intl.NumberFormat("en").format(value);
  return value.toFixed(2);
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return NA;
  return score.toFixed(1);
}

export function dataModeLabel(mode: string): string {
  return mode.charAt(0) + mode.slice(1).toLowerCase();
}

// ---------------------------------------------------------------------------
// Personalization storage (explicit selections only — spec §14)
// ---------------------------------------------------------------------------

const PREFERRED_KEY = "nm-discover-preferred-categories";

/** Categories this client explicitly starred (localStorage; never inferred). */
export function getPreferredCategories(): string[] {
  try {
    const raw = window.localStorage.getItem(PREFERRED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function togglePreferredCategory(category: string): string[] {
  const current = getPreferredCategories();
  const next = current.includes(category)
    ? current.filter((c) => c !== category)
    : [...current, category];
  try {
    window.localStorage.setItem(PREFERRED_KEY, JSON.stringify(next));
  } catch {
    /* storage disabled — selections simply don't persist */
  }
  return next;
}
