/**
 * Phase 21C — esports analytics data layer.
 *
 * Typed client for the `/api/v1/esports` analytics API, mirroring the backend
 * honesty contract exactly:
 *
 *  - every metric block carries `sample_size`, `date_range` and `sources`; the
 *    UI renders all three — a percentage with no sample size is never shown;
 *  - `null` means "the source did not publish this" and renders as the NA
 *    fallback, never 0;
 *  - trending signals that are absent arrive as `missing_signals` and lower
 *    `confidence`; the UI displays that disclosure instead of inventing activity.
 *
 * Weights live on the backend (`/analytics/engine`) — never in a component.
 */

import apiClient from "./axios";

// ---------------------------------------------------------------------------
// Shared metric primitives (mirror the backend `_metric_block`)
// ---------------------------------------------------------------------------

export interface MetricBlock<T> {
  value: T | null;
  sample_size: number;
  date_range: { from: string | null; to: string | null };
  sources: string[];
  data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
  available?: boolean;
  reason?: string | null;
}

export interface FormEntry {
  match_id: string;
  opponent_id: string;
  opponent_name: string | null;
  outcome: "win" | "loss" | "draw_or_unknown";
  score: string;
  tournament: string | null;
  played_at: string | null;
}

export interface TeamFormValue {
  wins: number;
  losses: number;
  win_rate: number | null;
  streak: string | null;
}

export interface TeamForm extends MetricBlock<TeamFormValue> {
  team_id: string;
  form: FormEntry[];
  decided_matches: number;
  undecided_matches: number;
}

export interface MapStat {
  map: string;
  played: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  loss_rate: number | null;
  recent_form: ("W" | "L")[];
  recent_win_rate: number | null;
  sample_size: number;
  data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
}

export interface MapAnalytics {
  available: boolean;
  reason: string | null;
  maps: MapStat[];
  sample_size: number;
  incomplete_records?: number;
  date_range: { from: string | null; to: string | null };
  sources: string[];
  data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
}

export interface DurationStats extends MetricBlock<{
  mean_seconds: number;
  median_seconds: number;
  std_seconds: number;
  min_seconds: number;
  max_seconds: number;
  rolling_mean_seconds: number[];
}> {
  available: boolean;
}

export interface PlayerMetric {
  key: string;
  label: string;
  value: number;
}

export interface PlayerAnalyticsPlayer {
  id: string;
  name: string;
  handle: string | null;
  role: string | null;
  country: string | null;
  avatar_url: string | null;
  team_id: string | null;
  metrics: PlayerMetric[];
  metric_count: number;
}

export interface PlayerAnalyticsPayload {
  available: boolean;
  reason: string | null;
  game_id: string;
  players: PlayerAnalyticsPlayer[];
  sample_size: number;
  metric_schema?: string[];
  data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
}

export interface AnomalyFinding {
  label: "ANOMALY DETECTED";
  method: string;
  index: number;
  reference?: string | null;
  value?: number;
  z_score?: number;
  score?: number;
  direction?: "high" | "low";
  features?: number[];
  /** Hub-level scan provenance (additive fields from the anomaly worker). */
  game_id?: string;
  check?: string;
}

export interface AnomalyCheck {
  available: boolean;
  reason: string | null;
  method: string;
  sample_size: number;
  anomalies: AnomalyFinding[];
}

export interface QualityComponents {
  freshness: number | null;
  completeness: number | null;
  sequence_integrity: number | null;
  source_reliability: number | null;
  provider_health: number | null;
}

export interface MatchQuality {
  match_id: string;
  game_id: string;
  score: number;
  label: "HIGH" | "MEDIUM" | "LOW";
  components: QualityComponents;
  weights_used: Record<string, number>;
  data_age_seconds: number | null;
  missing_fields: string[];
  sequence_issues: string[];
  provider_status: string | null;
  source: string | null;
  reasons: string[];
  evaluated_at: string;
}

export interface AggregateQuality {
  label: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
  score: number | null;
  evaluated: number;
  counts?: Record<string, number>;
}

export interface Discrepancy {
  label: "SOURCE DISCREPANCY";
  kind: string;
  field: string;
  sources: (string | null)[];
  values: unknown[];
  match_ids: (string | null)[];
  note: string;
}

export interface SourceConsistency {
  label: "SOURCE DISCREPANCY" | "CONSISTENT";
  discrepancies: Discrepancy[];
  count: number;
  matches_checked: number;
  cross_source_groups_compared: number;
  note: string;
  checked_at: string;
}

// ---------------------------------------------------------------------------
// Endpoint payloads
// ---------------------------------------------------------------------------

export interface TeamAnalytics {
  team_id: string;
  game_id: string | null;
  generated_at: string;
  sample_size: number;
  date_range: { from: string | null; to: string | null };
  sources: string[];
  form: TeamForm;
  series_win_rate: MetricBlock<{ wins: number; losses: number; win_rate: number | null }>;
  map_analytics: MapAnalytics;
  duration: DurationStats;
  score_progression: MetricBlock<{
    differential_mean: number;
    differential_std: number;
    rolling_differential: number[];
    trend: "RISING" | "FALLING" | "STABLE" | null;
  }>;
  historical_consistency: {
    value: number | null;
    sample_size: number;
    date_range: { from: string | null; to: string | null };
    sources: string[];
    data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
  };
  data_quality: AggregateQuality;
  source_consistency: SourceConsistency;
  cache?: "hit" | "miss";
}

export interface PlayerAnalytics {
  player_id: string;
  team_id: string | null;
  game_id: string | null;
  scanned_teams?: number;
  generated_at: string;
  available: boolean;
  reason: string | null;
  players: PlayerAnalyticsPlayer[];
  sample_size: number;
  metric_schema?: string[];
  data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
  cache?: "hit" | "miss";
}

export interface MatchAnalytics {
  match_id: string;
  game_id: string;
  generated_at: string;
  status: string;
  event_frequency: {
    available: boolean;
    reason: string | null;
    total_events: number;
    span_minutes: number | null;
    events_per_minute: number | null;
    by_type: Record<string, number>;
    by_type_per_minute: Record<string, number>;
    sample_size: number;
    date_range: { from: string | null; to: string | null };
    sources: string[];
    data_quality: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";
  };
  duration_stats: DurationStats;
  anomaly_detection: {
    label: "ANOMALY DETECTED" | "NO ANOMALY";
    count: number;
    findings: AnomalyFinding[];
    checks: {
      event_interval: AnomalyCheck;
      duration: AnomalyCheck;
      multivariate: AnomalyCheck;
    };
    note: string;
  };
  team_a: { team_id: string; form: TeamForm };
  team_b: { team_id: string; form: TeamForm };
  data_quality: MatchQuality;
  source_consistency: SourceConsistency;
  cache?: "hit" | "miss";
}

export type TrendingSignalKey = "live" | "event" | "start_rate" | "search" | "watchlist" | "viewer";

export interface TrendingGame {
  game_id: string;
  name: string;
  short_name: string | null;
  signals: Record<TrendingSignalKey, number | null>;
  live_matches: number | null;
  activity_metric: { label: string; value: number | null; source: string | null };
  last_updated: string | null;
  data_mode: string | null;
  score: number | null;
  score_0_100: number | null;
  components: Record<TrendingSignalKey, number | null>;
  contributions: Partial<Record<TrendingSignalKey, number>>;
  missing_signals: TrendingSignalKey[];
  available_weight: number;
  total_weight: number;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  confidence_ratio: number;
}

export interface TrendingGamesResponse {
  games: TrendingGame[];
  generated_at: string;
  window_hours: number;
  engine: {
    weights: Record<TrendingSignalKey, number>;
    saturation: number;
    signals: { key: string; weight: string; label: string }[];
    note: string;
  };
  interest_totals?: Record<string, number>;
  cache?: "hit" | "miss";
}

export interface TrendingMatchRow {
  match_id: string;
  game_id: string;
  status: string;
  score: number;
  components: {
    live_state: number;
    events_observed: number;
    starts_observed: number;
    recency: number;
  };
  match: {
    id: string;
    game_id: string;
    tournament_name: string | null;
    status: string;
    score_a: number;
    score_b: number;
    team_a: { id: string; name: string | null; logo_url: string | null };
    team_b: { id: string; name: string | null; logo_url: string | null };
    scheduled_at: string | null;
    last_updated: string | null;
    data_quality: string;
    source: string;
  };
}

export interface TrendingMatchesResponse {
  matches: TrendingMatchRow[];
  count: number;
  limit?: number;
  offset?: number;
  generated_at: string;
  selection: {
    method: string;
    weights: Record<string, number>;
    note: string;
  };
  cache?: "hit" | "miss";
}

export interface DataQualityResponse {
  game_id: string | null;
  aggregate: AggregateQuality;
  matches: MatchQuality[];
  providers: {
    name: string;
    status: string;
    last_success?: string | null;
    request_count?: number;
    error_count?: number;
    avg_latency_ms?: number;
    data_mode?: string | null;
    refresh?: string | null;
    error?: string;
  }[];
  source_consistency: SourceConsistency;
  generated_at: string;
  anomaly_scan?: {
    generated_at: string;
    /** Per-game nested results produced by the background anomaly worker. */
    games?: Record<
      string,
      {
        label: string;
        count: number;
        duration?: { anomalies?: AnomalyFinding[]; [key: string]: unknown };
        score_margin?: { anomalies?: AnomalyFinding[]; [key: string]: unknown };
      }
    >;
    total_findings?: number;
    /** Flat derived array over the per-game nested findings. */
    findings?: AnomalyFinding[];
    /** Sum of per-game score-margin sample sizes (each match = one sample). */
    matches_scanned?: number;
    matches_scanned_note?: string;
    note?: string;
  } | null;
  cache?: "hit" | "miss";
}

export interface LatencySummary {
  count: number;
  p50: number | null;
  p95: number | null;
  p99: number | null;
  avg: number | null;
  max: number | null;
  last: number | null;
}

export interface ObservabilityResponse {
  observability: {
    uptime_seconds: number;
    event_ingestion_rate_per_second: number;
    error_rate_per_second: number;
    events_recorded_by_game: Record<string, number>;
    provider_latency_ms: Record<string, LatencySummary>;
    websocket_broadcast_latency_ms: LatencySummary;
    event_processing_ms: LatencySummary;
    analytics_job_ms: LatencySummary;
    analytics_jobs: Record<string, { runs: number; last_ms: number | null; avg_ms: number }>;
    database_write_ms: LatencySummary;
    cache_lag_seconds: number | null;
    connected_clients?: number;
    ws_channels_with_subscribers?: number;
    analytics_store?: Record<string, unknown>;
    dirty_games?: number;
    captured_at: number;
  };
  manager_stats: Record<string, unknown> | null;
  generated_at: string;
}

export interface AnalyticsEngineInfo {
  trending_weights: Record<TrendingSignalKey, number>;
  trending_signals: { key: string; label: string }[];
  saturation: number;
  min_sample: number;
  anomaly_z_threshold: number;
  player_metric_schema: Record<string, string[]>;
  note: string;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

function encodeId(value: string): string {
  return encodeURIComponent(value);
}

export const EsportsAnalyticsService = {
  async getEngine(): Promise<AnalyticsEngineInfo> {
    const res = await apiClient.get<AnalyticsEngineInfo>("/api/v1/esports/analytics/engine");
    return res.data;
  },

  async getTeamAnalytics(teamId: string, gameId?: string | null): Promise<TeamAnalytics> {
    const res = await apiClient.get<TeamAnalytics>(
      `/api/v1/esports/analytics/team/${encodeId(teamId)}`,
      { params: gameId ? { game_id: gameId } : undefined }
    );
    return res.data;
  },

  async getPlayerAnalytics(playerId: string, opts?: { teamId?: string | null; gameId?: string | null }): Promise<PlayerAnalytics> {
    const params: Record<string, string> = {};
    if (opts?.teamId) params.team_id = opts.teamId;
    if (opts?.gameId) params.game_id = opts.gameId;
    const res = await apiClient.get<PlayerAnalytics>(
      `/api/v1/esports/analytics/player/${encodeId(playerId)}`,
      { params }
    );
    return res.data;
  },

  async getMatchAnalytics(matchId: string): Promise<MatchAnalytics> {
    const res = await apiClient.get<MatchAnalytics>(
      `/api/v1/esports/analytics/match/${encodeId(matchId)}`
    );
    return res.data;
  },

  async getTrendingGames(): Promise<TrendingGamesResponse> {
    const res = await apiClient.get<TrendingGamesResponse>("/api/v1/esports/trending/games");
    return res.data;
  },

  async getTrendingMatches(gameId?: string | null, limit = 10, offset = 0): Promise<TrendingMatchesResponse> {
    const params: Record<string, string | number> = { limit, offset };
    if (gameId) params.game_id = gameId;
    const res = await apiClient.get<TrendingMatchesResponse>("/api/v1/esports/trending/matches", { params });
    return res.data;
  },

  async getDataQuality(gameId?: string | null, limit = 50): Promise<DataQualityResponse> {
    const params: Record<string, string | number> = { limit };
    if (gameId) params.game_id = gameId;
    const res = await apiClient.get<DataQualityResponse>("/api/v1/esports/data-quality", { params });
    return res.data;
  },

  async getObservability(): Promise<ObservabilityResponse> {
    const res = await apiClient.get<ObservabilityResponse>("/api/v1/esports/observability");
    return res.data;
  },

  async recordInterest(gameId: string, kind: "view" | "search" | "follow", matchId?: string | null): Promise<void> {
    await apiClient.post("/api/v1/esports/interest", {
      game_id: gameId,
      kind,
      match_id: matchId ?? null,
    });
  },
};
