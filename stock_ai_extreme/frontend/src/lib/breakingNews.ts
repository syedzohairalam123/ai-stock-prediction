/**
 * Phase 17 — Real-Time Breaking News + Trending Topics + Market Impact
 * Intelligence: typed client for every `/api/breaking-news` endpoint.
 *
 * Contract notes that the UI must respect rather than hide:
 *
 * * `published_at` is the **publisher's** timestamp. Nothing here ever derives a
 *   display time from when the fetch happened.
 * * Anything that could not be measured comes back `null` / `false` /
 *   `window_available: false`. The UI renders "unavailable", never a placeholder
 *   number.
 * * Market movement is an observed historical relationship
 *   ("price movement observed after publication"), so the copy that renders it
 *   must not claim causation.
 * * `ai_summary*` is always labelled as AI-generated, and a summary only exists
 *   when the configured AI provider actually produced one.
 */
import { useEffect, useRef, useState } from "react";
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// enums (mirrors app/breaking_news/schemas.py)
// ---------------------------------------------------------------------------

export type BreakingLevel = "BREAKING" | "SIGNIFICANT" | "NORMAL";
export type TrendDirection = "RISING" | "FALLING" | "STABLE";
export type ImpactMagnitude = "HIGH" | "MEDIUM" | "LOW" | "NONE";
export type DataMode = "LIVE" | "RECENT" | "STALE" | "UNKNOWN";
export type SourceStatus = "ACTIVE" | "DEGRADED" | "INACTIVE";
export type ObservationWindow = "5m" | "15m" | "30m" | "1h" | "4h" | "24h";
export type EntityType = "STOCK" | "INDEX" | "COMMODITY" | "FOREX" | "CRYPTO" | "FORECAST" | "AUTO";
export type StreamTransport = "websocket" | "sse" | "polling" | "connecting";

export const OBSERVATION_WINDOWS: ObservationWindow[] = ["5m", "15m", "30m", "1h", "4h", "24h"];

export const WINDOW_LABELS: Record<ObservationWindow, string> = {
  "5m": "5 minutes",
  "15m": "15 minutes",
  "30m": "30 minutes",
  "1h": "1 hour",
  "4h": "4 hours",
  "24h": "24 hours",
};

// ---------------------------------------------------------------------------
// response contracts
// ---------------------------------------------------------------------------

export interface ScoreBreakdown {
  score: number;
  level: BreakingLevel;
  components?: Record<string, number>;
  weights?: Record<string, number>;
}

export interface BreakingNewsEvent {
  id: string;
  article_id: number | null;
  article_url: string | null;
  title: string;
  publisher: string;
  published_at: string;
  url: string;
  image: string | null;
  excerpt: string | null;
  category: string | null;
  source: string | null;
  data_mode: DataMode;

  breaking_score: number;
  breaking_level: BreakingLevel;
  entity_importance: number | null;
  mention_velocity: number | null;
  topic_acceleration: number | null;
  source_reliability: number | null;
  score_components: Record<string, number> | null;
  score_weights: Record<string, number> | null;

  cluster_id: string | null;
  cluster_size: number;
  related_articles: number[];

  affected_entities: string[];
  affected_indices: string[];
  topics: string[];
  market_associations: Record<string, unknown>;
  impact_detected: boolean;
  impact_data: Record<string, unknown> | null;

  ai_summary: string | null;
  ai_summary_model: string | null;
  ai_summary_generated_at: string | null;
  ai_summary_is_ai_generated: boolean;

  /** Relative age computed server-side from the publisher timestamp. */
  time_ago: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BreakingFeedMeta {
  hours: number;
  min_score: number;
  generated_at: string;
  total_events: number;
  breaking_count: number;
  significant_count: number;
  articles_analyzed: number;
  clusters_found: number;
  sources_consulted: number;
  providers: ProviderReport[];
  disclaimer: string;
}

export interface BreakingFeedResponse {
  items: BreakingNewsEvent[];
  meta: BreakingFeedMeta;
}

export interface NewsTopic {
  id: string;
  topic_name: string;
  normalized_name: string;
  topic_type: string;
  category: string | null;
  mention_count: number;
  article_count: number;
  article_velocity: number | null;
  source_count: number;
  recency_score: number | null;
  related_activity: number | null;
  trend_score: number;
  trend_direction: TrendDirection;
  trend_velocity: number | null;
  trend_components: Record<string, number> | null;
  trend_weights: Record<string, number> | null;
  related_entities: string[];
  related_stocks: string[];
  related_indices: string[];
  first_seen: string | null;
  last_seen: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TopicTimelinePoint {
  id: string;
  topic_id: string;
  timestamp: string;
  mention_count: number;
  article_count: number;
  source_count: number;
  trend_score: number | null;
  related_activity: number | null;
}

export interface TopicArticle {
  id: number;
  title: string;
  publisher: string | null;
  published_at: string | null;
  url: string;
  excerpt: string | null;
  impact_score: number | null;
  event_type: string | null;
  symbols: string[];
  data_mode: DataMode;
}

export interface TopicDetail {
  topic: NewsTopic;
  timeline: TopicTimelinePoint[];
  articles: TopicArticle[];
  impact_events: MarketImpactEvent[];
  sources: string[];
  generated_at: string;
}

export interface TopicsResponse {
  topics: NewsTopic[];
  meta: Record<string, unknown>;
}

export interface ImpactSeriesPoint {
  timestamp: string;
  close: number | null;
  volume: number | null;
}

export interface MarketImpactEvent {
  id: string | null;
  article_id: number | null;
  breaking_news_id: string | null;
  entity: string;
  entity_type: string;
  provider_symbol: string | null;
  data_source: string | null;

  news_published_at: string;
  observation_window: string;
  observation_started_at: string | null;
  observation_ended_at: string | null;
  bars_before: number;
  bars_after: number;
  window_available: boolean;

  market_data_before: Record<string, unknown> | null;
  market_data_after: Record<string, unknown> | null;
  series: ImpactSeriesPoint[];

  price_change: number | null;
  price_change_percent: number | null;
  volume_change: number | null;
  volume_change_percent: number | null;
  max_favorable_excursion_percent: number | null;
  max_adverse_excursion_percent: number | null;
  realized_volatility_percent: number | null;

  impact_magnitude: ImpactMagnitude;
  correlation_score: number | null;
  confidence: number | null;
  notes: string | null;
  created_at: string | null;
}

export interface ImpactWindowAnalysis {
  entity: string;
  entity_type: string;
  news_published_at: string;
  windows: MarketImpactEvent[];
  unavailable_windows: string[];
  disclaimer: string;
}

export interface ObservedMovementRef {
  entity: string | null;
  entity_type: string | null;
  observation_window: string | null;
  price_change_percent: number | null;
  news_published_at: string | null;
  breaking_news_id: string | null;
  article_id: number | null;
}

/**
 * Descriptive statistics over a sample of *measured* movement rows.
 * `sample_size` counts only observations with a real measured move;
 * `unavailable_samples` counts rows that could not be measured and are excluded.
 */
export interface ObservedMovementStats {
  sample_size: number;
  unavailable_samples: number;
  up: number;
  down: number;
  flat: number;
  hit_rate_up: number | null;
  mean_percent: number | null;
  median_percent: number | null;
  stdev_percent: number | null;
  mean_absolute_percent: number | null;
  max_gain_percent: number | null;
  max_loss_percent: number | null;
  mean_max_favorable_percent: number | null;
  mean_max_adverse_percent: number | null;
  mean_realized_volatility_percent: number | null;
  mean_confidence: number | null;
  magnitude_breakdown: Record<string, number>;
  first_observed_at: string | null;
  last_observed_at: string | null;
  best: ObservedMovementRef | null;
  worst: ObservedMovementRef | null;
}

export interface ImpactStudyGroup {
  key: string;
  label: string;
  entity_type: string | null;
  observation_window: string | null;
  sufficient_sample: boolean;
  stats: ObservedMovementStats;
}

/** Aggregate of price movements observed after publication (never causal). */
export interface ImpactStudy {
  generated_at: string;
  hours: number;
  min_sample: number;
  window: string | null;
  entity_type: string | null;
  samples_considered: number;
  measured_samples: number;
  unavailable_samples: number;
  sufficient_groups: number;
  overall: ObservedMovementStats;
  by_entity: ImpactStudyGroup[];
  by_entity_type: ImpactStudyGroup[];
  by_window: ImpactStudyGroup[];
  note: string;
  disclaimer: string;
}

export interface ProbabilityMovement {
  id: string;
  article_id: number | null;
  breaking_news_id: string | null;
  market_id: string;
  market_name: string | null;
  market_url: string | null;
  news_published_at: string;
  observation_window: string;
  probability_before: number | null;
  probability_after: number | null;
  probability_change: number | null;
  movement_direction: string;
  impact_magnitude: ImpactMagnitude;
  source_name: string | null;
  source_url: string | null;
  series: Record<string, unknown>[];
  source_reliability: number | null;
  created_at: string | null;
}

export interface SourceMetadata {
  id: string;
  publisher: string;
  source_url: string | null;
  source_type: string;
  region: string | null;
  category: string | null;
  feed_key: string | null;
  reliability_score: number;
  accuracy_score: number | null;
  timeliness_score: number | null;
  completeness_score: number | null;
  article_count: number;
  breaking_count: number;
  last_published: string | null;
  last_retrieved: string | null;
  status: SourceStatus;
  error_count: number;
  consecutive_errors: number;
  last_error: string | null;
  additional_data: Record<string, unknown> | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SourcesResponse {
  sources: SourceMetadata[];
  summary: Record<string, unknown>;
  feed_health: Array<Record<string, unknown>>;
  generated_at: string;
}

export interface ProviderReport {
  name: string;
  ok: boolean;
  fetched: number;
  normalized: number;
  rejected: number;
  duplicates: number;
  duration_ms: number | null;
  error: string | null;
  missing_fields: Record<string, number>;
}

export interface IngestReport {
  started_at: string;
  finished_at: string;
  duration_ms: number;
  stored_articles: number;
  corpus_articles: number;
  breaking_events: number;
  topics_updated: number;
  impact_events: number;
  probability_movements: number;
  providers: ProviderReport[];
  errors: string[];
  warnings: string[];
}

export interface Cluster {
  cluster_id: string;
  canonical_article_id: number | null;
  title: string;
  publisher: string | null;
  cluster_size: number;
  publishers: string[];
  article_ids: number[];
  first_seen: string | null;
  last_seen: string | null;
  time_span_hours: number;
  symbols: string[];
  terms: string[];
}

export interface BreakingHealth {
  status: string;
  phase: number;
  database: string;
  corpus_articles_24h: number;
  breaking_events: number;
  topics: number;
  market_impact_events: number;
  probability_movements: number;
  last_build_at: string | null;
  last_build_stats: Record<string, unknown> | null;
  last_ingest_report: Record<string, unknown> | null;
  stream: Record<string, unknown>;
  providers_configured: boolean;
  ai_summarization: { enabled: boolean; available: boolean; min_score: number };
  observation_windows: string[];
  settings: {
    breaking_threshold: number;
    significant_threshold: number;
    detection_weights: Record<string, number>;
    topic_trend_weights: Record<string, number>;
  };
  generated_at: string;
}

export interface DigestSnapshot {
  generated_at: string;
  hours: number;
  events: Array<{
    id: string;
    title: string;
    publisher: string;
    published_at: string | null;
    time_ago: string | null;
    url: string;
    image: string | null;
    breaking_score: number;
    breaking_level: BreakingLevel;
    cluster_size: number;
    affected_entities: string[];
    data_mode: DataMode;
    ai_summary: boolean;
  }>;
  topics: Array<{
    id: string;
    topic_name: string;
    trend_score: number;
    trend_direction: TrendDirection;
    mention_count: number;
    source_count: number;
    related_stocks: string[];
  }>;
  counts: { events: number; breaking: number; significant: number };
  meta: Record<string, unknown>;
}

export interface EventSummary {
  status?: string;
  summary?: string;
  model?: string;
  generated_at?: string;
  is_ai_generated?: boolean;
  label?: string;
  /** Present when the AI provider is unavailable or declined the request. */
  reason?: string;
  message?: string;
  [key: string]: unknown;
}

export interface FeedQuery {
  hours?: number;
  minScore?: number;
  level?: BreakingLevel;
  category?: string;
  entity?: string;
  limit?: number;
  rebuild?: boolean;
}

// ---------------------------------------------------------------------------
// endpoints
// ---------------------------------------------------------------------------

const BASE = "/breaking-news";

export async function fetchBreakingFeed(query: FeedQuery = {}): Promise<BreakingFeedResponse> {
  const { data } = await apiClient.get<BreakingFeedResponse>(`${BASE}/feed`, {
    params: {
      hours: query.hours ?? 24,
      min_score: query.minScore ?? 0,
      level: query.level,
      category: query.category,
      entity: query.entity,
      limit: query.limit ?? 50,
      rebuild: query.rebuild ? true : undefined,
    },
  });
  return data;
}

export async function fetchBreakingOnly(hours = 6, limit = 25): Promise<BreakingFeedResponse> {
  const { data } = await apiClient.get<BreakingFeedResponse>(`${BASE}/breaking`, { params: { hours, limit } });
  return data;
}

export async function fetchDigest(hours = 24, limit = 15): Promise<DigestSnapshot> {
  const { data } = await apiClient.get<DigestSnapshot>(`${BASE}/digest`, { params: { hours, limit } });
  return data;
}

export async function fetchClusters(hours = 24, minSize = 1): Promise<Cluster[]> {
  const { data } = await apiClient.get<Cluster[]>(`${BASE}/clusters`, { params: { hours, min_size: minSize } });
  return data;
}

export async function fetchTopics(options: {
  limit?: number;
  minTrendScore?: number;
  category?: string;
  topicType?: string;
} = {}): Promise<TopicsResponse> {
  const { data } = await apiClient.get<TopicsResponse>(`${BASE}/topics`, {
    params: {
      limit: options.limit ?? 20,
      min_trend_score: options.minTrendScore ?? 0,
      category: options.category,
      topic_type: options.topicType,
    },
  });
  return data;
}

export async function fetchTopicDetail(topicId: string, options: { hours?: number; limit?: number } = {}): Promise<TopicDetail> {
  const { data } = await apiClient.get<TopicDetail>(`${BASE}/topics/${encodeURIComponent(topicId)}`, {
    params: { hours: options.hours ?? 72, limit: options.limit ?? 50 },
  });
  return data;
}

export async function fetchTopicTimeline(topicId: string, hours = 72): Promise<TopicTimelinePoint[]> {
  const { data } = await apiClient.get<TopicTimelinePoint[]>(
    `${BASE}/topics/${encodeURIComponent(topicId)}/timeline`,
    { params: { hours } },
  );
  return data;
}

export async function fetchTopicArticles(topicId: string, options: { hours?: number; limit?: number } = {}): Promise<TopicArticle[]> {
  const { data } = await apiClient.get<TopicArticle[]>(`${BASE}/topics/${encodeURIComponent(topicId)}/articles`, {
    params: { hours: options.hours ?? 72, limit: options.limit ?? 50 },
  });
  return data;
}

export async function fetchEventDetail(newsId: string): Promise<BreakingNewsEvent> {
  const { data } = await apiClient.get<BreakingNewsEvent>(`${BASE}/${encodeURIComponent(newsId)}`);
  return data;
}

export async function summarizeEvent(newsId: string, force = false): Promise<EventSummary> {
  const { data } = await apiClient.post<EventSummary>(
    `${BASE}/${encodeURIComponent(newsId)}/summary`,
    undefined,
    { params: { force: force ? true : undefined }, timeout: 60000 },
  );
  return data;
}

export async function analyzeImpact(body: {
  article_id?: number;
  url?: string;
  entity?: string;
  entity_type?: EntityType;
  observation_window?: ObservationWindow;
  published_at?: string;
  refresh?: boolean;
}): Promise<ImpactWindowAnalysis> {
  const { data } = await apiClient.post<ImpactWindowAnalysis>(`${BASE}/impact`, body, { timeout: 60000 });
  return data;
}

export async function fetchImpactStudy(options: {
  hours?: number;
  window?: ObservationWindow;
  entityType?: Exclude<EntityType, "AUTO">;
  minSample?: number;
} = {}): Promise<ImpactStudy> {
  const { data } = await apiClient.get<ImpactStudy>(`${BASE}/impact/study`, {
    params: {
      hours: options.hours ?? 168,
      window: options.window,
      entity_type: options.entityType,
      min_sample: options.minSample,
    },
  });
  return data;
}

export async function fetchEntityImpactHistory(
  entity: string,
  options: { hours?: number; limit?: number } = {},
): Promise<MarketImpactEvent[]> {
  const { data } = await apiClient.get<MarketImpactEvent[]>(
    `${BASE}/impact/entity/${encodeURIComponent(entity)}`,
    { params: { hours: options.hours ?? 168, limit: options.limit ?? 50 } },
  );
  return data;
}

export async function fetchEventImpactWindows(newsId: string, refresh = false): Promise<ImpactWindowAnalysis> {
  const { data } = await apiClient.get<ImpactWindowAnalysis>(
    `${BASE}/impact/${encodeURIComponent(newsId)}/windows`,
    { params: { refresh: refresh ? true : undefined }, timeout: 60000 },
  );
  return data;
}

export async function fetchProbabilityMovements(body: {
  market_id?: string;
  article_id?: number;
  observation_window?: ObservationWindow;
}): Promise<ProbabilityMovement[]> {
  const { data } = await apiClient.post<ProbabilityMovement[]>(`${BASE}/probability`, body, { timeout: 60000 });
  return data;
}

export async function fetchMarketProbabilityHistory(marketId: string, hours = 168): Promise<ProbabilityMovement[]> {
  const { data } = await apiClient.get<ProbabilityMovement[]>(
    `${BASE}/probability/${encodeURIComponent(marketId)}`,
    { params: { hours } },
  );
  return data;
}

export async function fetchSources(): Promise<SourcesResponse> {
  const { data } = await apiClient.get<SourcesResponse>(`${BASE}/sources`);
  return data;
}

export async function refreshBreakingNews(options: {
  live?: boolean;
  region?: string;
  analyzeImpacts?: boolean;
} = {}): Promise<IngestReport> {
  const { data } = await apiClient.post<IngestReport>(
    `${BASE}/refresh`,
    undefined,
    {
      params: {
        live: options.live ?? true,
        region: options.region,
        analyze_impacts: options.analyzeImpacts ? true : undefined,
      },
      timeout: 180000,
    },
  );
  return data;
}

export async function fetchBreakingHealth(): Promise<BreakingHealth> {
  const { data } = await apiClient.get<BreakingHealth>(`${BASE}/health`);
  return data;
}

// ---------------------------------------------------------------------------
// real-time transport (spec §15)
// ---------------------------------------------------------------------------

/**
 * Pick the best transport the deployment actually supports.
 *
 * Order of preference: WebSocket → Server-Sent Events → polling. Each level is
 * only used after the previous one has definitively failed, and the active
 * transport is surfaced in the UI so nobody has to guess whether "LIVE" means
 * live.
 */
function websocketUrl(): string | null {
  const configured = import.meta.env.VITE_BREAKING_NEWS_WS_URL as string | undefined;
  if (configured) return configured;
  if (typeof window === "undefined") return null;
  try {
    const wsUrl = import.meta.env.VITE_WS_URL as string | undefined;
    if (wsUrl && /^wss?:/i.test(wsUrl)) {
      const wsBase = wsUrl.replace(/\/+$/, "");
      const apiBase = /\/api$/i.test(wsBase) ? wsBase : `${wsBase}/api`;
      return `${apiBase}${BASE}/ws`;
    }
    const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
    const origin = apiUrl && /^https?:/i.test(apiUrl) ? new URL(apiUrl).origin : window.location.origin;
    const scheme = origin.startsWith("https") ? "wss" : "ws";
    const base = origin.replace(/^https?:/i, scheme);
    const apiPath = apiUrl && /^https?:/i.test(apiUrl) ? new URL(apiUrl).pathname.replace(/\/+$/, "") : "/api";
    const prefix = /\/api$/i.test(apiPath) ? apiPath : `${apiPath}/api`;
    return `${base}${prefix}${BASE}/ws`;
  } catch {
    return null;
  }
}

function sseUrl(): string {
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined;
  if (apiUrl && /^https?:/i.test(apiUrl)) {
    const base = apiUrl.replace(/\/+$/, "");
    return `${/\/api$/i.test(base) ? base : `${base}/api`}${BASE}/stream`;
  }
  return `/api${BASE}/stream`;
}

export interface StreamState {
  transport: StreamTransport;
  snapshot: DigestSnapshot | null;
  lastMessageAt: string | null;
  /** Pushed by the server when new events land, so the feed can refetch. */
  updateToken: number;
  error: string | null;
}

/**
 * Subscribe to the breaking-news desk.
 *
 * `onUpdate` fires whenever the backend signals that the digest changed. The
 * hook does not fetch the feed itself — the caller owns that so the same
 * refresh path is used for the initial load, a manual refresh and a push.
 */
export function useBreakingNewsStream(options: {
  enabled?: boolean;
  pollMs?: number;
  onUpdate?: (snapshot: DigestSnapshot | null) => void;
} = {}): StreamState {
  const { enabled = true, pollMs = 30000, onUpdate } = options;
  const [state, setState] = useState<StreamState>({
    transport: "connecting",
    snapshot: null,
    lastMessageAt: null,
    updateToken: 0,
    error: null,
  });

  // Kept in a ref so a changing callback never tears the transport down.
  const updateRef = useRef(onUpdate);
  updateRef.current = onUpdate;

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let events: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let wsTimer: ReturnType<typeof setTimeout> | null = null;
    let consecutiveErrors = 0;

    const push = (snapshot: DigestSnapshot | null, transport: StreamTransport | null = null) => {
      if (disposed) return;
      updateRef.current?.(snapshot);
      setState((prev) => ({
        transport: transport ?? prev.transport,
        snapshot: snapshot ?? prev.snapshot,
        lastMessageAt: new Date().toISOString(),
        updateToken: prev.updateToken + 1,
        error: null,
      }));
    };

    const teardownSocket = () => {
      if (wsTimer) { clearTimeout(wsTimer); wsTimer = null; }
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onerror = null;
        socket.onclose = null;
        try { socket.close(); } catch { /* already closed */ }
        socket = null;
      }
    };

    const startPolling = () => {
      if (disposed || pollTimer) return;
      setState((prev) => ({ ...prev, transport: "polling" }));
      let signature = "";
      const tick = async () => {
        try {
          const digest = await fetchDigest();
          const next = `${digest.generated_at}|${digest.counts.events}|${digest.counts.breaking}`;
          if (next !== signature) {
            signature = next;
            push(digest, "polling");
          } else {
            setState((prev) => ({ ...prev, lastMessageAt: new Date().toISOString() }));
          }
        } catch (err) {
          setState((prev) => ({ ...prev, error: err instanceof Error ? err.message : "Digest poll failed" }));
        }
      };
      void tick();
      pollTimer = setInterval(() => void tick(), pollMs);
    };

    const startSse = () => {
      if (disposed) return;
      try {
        events = new EventSource(sseUrl());
      } catch {
        startPolling();
        return;
      }
      events.addEventListener("snapshot", (event) => {
        try {
          push(JSON.parse((event as MessageEvent).data) as DigestSnapshot, "sse");
        } catch { /* ignore a malformed frame */ }
      });
      events.addEventListener("breaking_news_update", (event) => {
        try {
          // The broadcaster frames SSE payloads as `{type, etag, data}` and the
          // WebSocket as `{type, data}`; both must be read or the SSE transport
          // would receive every push without its snapshot and refetch blindly.
          const payload = JSON.parse((event as MessageEvent).data) as {
            snapshot?: DigestSnapshot;
            data?: DigestSnapshot;
          };
          push(payload.data ?? payload.snapshot ?? null, "sse");
        } catch {
          push(null, "sse");
        }
      });
      events.addEventListener("events_available", () => push(null, "sse"));
      events.onopen = () => {
        consecutiveErrors = 0;
        setState((prev) => ({ ...prev, transport: "sse", error: null }));
      };
      events.onerror = () => {
        consecutiveErrors += 1;
        // EventSource auto-reconnects; only give up on it once it keeps failing.
        if (consecutiveErrors >= 3) {
          events?.close();
          events = null;
          startPolling();
        }
      };
    };

    const startSocket = () => {
      const url = websocketUrl();
      if (!url) { startSse(); return; }
      try {
        socket = new WebSocket(url);
      } catch {
        startSse();
        return;
      }
      // If the handshake does not complete, this deployment cannot proxy WS.
      wsTimer = setTimeout(() => {
        if (socket && socket.readyState !== WebSocket.OPEN) {
          teardownSocket();
          startSse();
        }
      }, 4000);

      socket.onopen = () => {
        if (wsTimer) { clearTimeout(wsTimer); wsTimer = null; }
        setState((prev) => ({ ...prev, transport: "websocket", error: null }));
      };
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(message.data) as { type?: string; data?: DigestSnapshot; snapshot?: DigestSnapshot };
          if (payload.type === "snapshot") push(payload.data ?? null, "websocket");
          else if (payload.type === "breaking_news_update") push(payload.snapshot ?? payload.data ?? null, "websocket");
          else if (payload.type === "events_available") push(null, "websocket");
          else if (payload.type === "heartbeat") setState((prev) => ({ ...prev, lastMessageAt: new Date().toISOString() }));
        } catch { /* ignore a malformed frame */ }
      };
      socket.onerror = () => { /* onclose carries the decision */ };
      socket.onclose = () => {
        if (disposed) return;
        teardownSocket();
        startSse();
      };
    };

    startSocket();

    return () => {
      disposed = true;
      teardownSocket();
      if (events) { events.close(); events = null; }
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    };
  }, [enabled, pollMs]);

  return state;
}

// ---------------------------------------------------------------------------
// presentation helpers
// ---------------------------------------------------------------------------

/** Relative label from a real ISO timestamp (falls back to "unknown time"). */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "time unavailable";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "time unavailable";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return "less than a minute ago";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "timestamp unavailable";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "timestamp unavailable";
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "--:--";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Signed number with an explicit sign; `null` renders as "unavailable". */
export function signed(value: number | null | undefined, digits = 2, suffix = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unavailable";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${suffix}`;
}

export function fixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unavailable";
  return value.toFixed(digits);
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unavailable";
  return `${(value * 100).toFixed(digits)}%`;
}

export function levelClass(level: BreakingLevel | string | undefined): string {
  switch (level) {
    case "BREAKING": return "bn-level-breaking";
    case "SIGNIFICANT": return "bn-level-significant";
    default: return "bn-level-normal";
  }
}

export function magnitudeClass(magnitude: ImpactMagnitude | string | undefined): string {
  switch (magnitude) {
    case "HIGH": return "bn-mag-high";
    case "MEDIUM": return "bn-mag-medium";
    case "LOW": return "bn-mag-low";
    default: return "bn-mag-none";
  }
}

export function directionClass(direction: TrendDirection | string | undefined): string {
  switch (direction) {
    case "RISING": return "bn-dir-rising";
    case "FALLING": return "bn-dir-falling";
    default: return "bn-dir-stable";
  }
}

export function statusClass(status: SourceStatus | string | undefined): string {
  switch (status) {
    case "ACTIVE": return "bn-status-active";
    case "DEGRADED": return "bn-status-degraded";
    default: return "bn-status-inactive";
  }
}

/** Weighted contributions in score order, largest first — for score breakdowns. */
export function rankedComponents(
  components: Record<string, number> | null | undefined,
  weights: Record<string, number> | null | undefined,
): Array<{ key: string; label: string; contribution: number; weight: number | null }> {
  if (!components) return [];
  return Object.entries(components)
    .map(([key, value]) => ({
      key,
      label: key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      contribution: value,
      weight: weights && typeof weights[key] === "number" ? weights[key] : null,
    }))
    .sort((a, b) => b.contribution - a.contribution);
}
