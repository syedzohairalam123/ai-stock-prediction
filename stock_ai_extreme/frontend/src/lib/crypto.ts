/**
 * Phase 22 — Ultra-Advanced Timeframe-Based Crypto Volatility & Forecasting
 * Intelligence Engine: typed data layer.
 *
 * One typed client for every `/api/v1/crypto` endpoint (also mounted at the
 * legacy `/api/crypto` alias). The honesty contract mirrored from the backend:
 *
 *  - `null`/`undefined` means the value is genuinely unavailable; it renders
 *    as the labelled `NA` fallback, never a fabricated 0 or placeholder;
 *  - `data_status` / `quality` are the source's own freshness labels;
 *  - every number carries a `value_origin` (SOURCE / CALCULATED / MODELLED /
 *    DERIVED) so the UI can label where it came from (spec §99);
 *  - forecasts and probabilities are MODELLED — never presented as guarantees.
 */
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// Envelope (spec §61)
// ---------------------------------------------------------------------------

export type DataStatusValue =
  | "LIVE"
  | "RECENT"
  | "DELAYED"
  | "STALE"
  | "HISTORICAL"
  | "UNAVAILABLE";

export type QualityValue = "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE";

export interface ResponseMeta {
  generated_at: string;
  source: string | null;
  data_status: DataStatusValue | null;
  quality: QualityValue | null;
  age_ms: number | null;
  timeframe: string | null;
  notes: string[];
}

export interface CryptoEnvelope<T> {
  data: T;
  meta: ResponseMeta;
  requestId: string;
  errors: string[];
}

/** Unwrap helper: every service call returns `data` + meta merged for ergonomics. */
export async function cryptoGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
): Promise<CryptoEnvelope<T>> {
  const clean: Record<string, string | number | boolean> = {};
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") clean[key] = value;
    }
  }
  const res = await apiClient.get<CryptoEnvelope<T>>(`/api/v1/crypto${path}`, {
    params: Object.keys(clean).length ? clean : undefined,
  });
  return res.data;
}

// ---------------------------------------------------------------------------
// Reference data
// ---------------------------------------------------------------------------

export interface CryptoAsset {
  symbol: string;
  name: string;
  display: string;
  binance_symbol: string | null;
  coingecko_id: string | null;
  industry: string;
  streaming: boolean;
}

export interface CryptoAssetsResponse {
  assets: CryptoAsset[];
  count: number;
  industries: Record<string, string[]>;
  note: string;
  origin: string;
}

export interface TimeframeConfig {
  id: string;
  label: string;
  duration_seconds: number;
  source_interval: string;
  aggregation_method: string;
  max_history_candles: number;
  enabled: boolean;
}

export interface TimeframeCapability {
  id: string;
  label: string;
  source_interval: string;
  native: boolean;
  aggregation_required: boolean;
  aggregation_method: string;
  supported: boolean;
  max_history_candles: number;
}

export interface TimeframesResponse {
  default: string;
  timeframes: TimeframeConfig[];
  capabilities: TimeframeCapability[];
  capability_provider: string;
  note: string;
  origin: string;
}

export interface SourceEntry {
  provider: string;
  role: string;
  native_intervals: string[];
  streaming: boolean;
  base_url: string | null;
  stats?: Record<string, unknown>;
}

export interface ProviderHealthEntry {
  provider: string;
  status: string;
  detail: string | null;
  latency_ms: number | null;
}

export interface SourcesResponse {
  sources: SourceEntry[];
  health: ProviderHealthEntry[];
  stats: Record<string, unknown>;
  note: string;
}

export interface CategoryDefinition {
  id: string;
  label: string;
  description: string;
  origin: string;
}

export interface CategoriesResponse {
  categories: CategoryDefinition[];
  currency: { base_currency: string; quote_asset: string; note: string };
}

// ---------------------------------------------------------------------------
// Market data
// ---------------------------------------------------------------------------

export interface CryptoCandle {
  timestamp: string;
  epoch_ms: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface GapReport {
  timeframe: string;
  expected_intervals: number;
  received_intervals: number;
  missing_intervals: number;
  duplicate_intervals: number;
  out_of_order: number;
  largest_gap_seconds: number;
  completeness: number;
  label: string;
}

export interface QualityAssessment {
  label: QualityValue;
  status: DataStatusValue;
  age_ms: number | null;
  completeness: number | null;
  driver: string | null;
  components: Record<string, unknown>;
}

export interface QuotePayload {
  symbol: string;
  price: number | null;
  bid: number | null;
  ask: number | null;
  volume_24h: number | null;
  quote_volume_24h?: number | null;
  high_24h?: number | null;
  low_24h?: number | null;
  open_24h?: number | null;
  change_24h?: number | null;
  change_percent_24h: number | null;
  timestamp: string | null;
  source_timestamp?: string | null;
  fetched_at?: string | null;
  source: string | null;
  status: DataStatusValue;
  age_ms: number | null;
  currency: string;
  origin: string;
  errors?: string[];
  origin_by_field?: Record<string, string>;
  reason?: string;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  timeframe_label: string;
  interval: string;
  aggregated: boolean;
  source: string | null;
  data_status: DataStatusValue;
  quality: QualityAssessment;
  gaps: GapReport;
  requested_limit: number | null;
  returned: number;
  raw_count: number;
  downsampled: boolean;
  downsample_note: string | null;
  notes: string[];
  candles: CryptoCandle[];
  origin: string;
}

export interface IndicatorsBundle {
  available: boolean;
  origin?: string;
  ema_fast?: number | null;
  ema_slow?: number | null;
  ema_fast_slope?: number | null;
  ema_slow_slope?: number | null;
  sma_slope?: number | null;
  rsi?: number | null;
  atr?: number | null;
  atr_percent?: number | null;
  momentum?: number | null;
  range_position?: number | null;
  range_expansion?: number | null;
  volume_change?: number | null;
}

export interface VolatilitySnapshot {
  timeframe: string;
  realized_volatility: number | null;
  rolling_std: number | null;
  atr: number | null;
  atr_percent: number | null;
  range_volatility: number | null;
  volatility_percentile: number | null;
  regime: "LOW" | "NORMAL" | "HIGH" | "EXTREME" | "INSUFFICIENT_DATA";
  window: number;
  sample_size: number;
  data_status: DataStatusValue;
  generated_at: string;
}

export interface MicroTrend {
  direction: "UP" | "DOWN" | "SIDEWAYS" | "INSUFFICIENT_DATA";
  strength: number;
  confidence: number;
  timeframe: string;
  recent_return: number | null;
  volatility_regime: string | null;
  factors: Record<string, unknown>;
  sample_size: number;
  data_status: DataStatusValue;
  generated_at: string;
}

export interface AnalyticsResponse {
  symbol: string;
  timeframe: string;
  timeframe_label: string;
  source: string | null;
  data_status: DataStatusValue;
  quality: QualityAssessment;
  gaps: GapReport;
  sample_size: number;
  last_close: number | null;
  returns: { last_bar_simple: number | null; over_window: number | null; origin: string };
  indicators: IndicatorsBundle;
  volatility: VolatilitySnapshot;
  trend: MicroTrend;
  value_origins: Record<string, string>;
  note: string;
}

export interface MultiTimeframeRow {
  timeframe: string;
  label: string;
  trend: string;
  trend_strength?: number | null;
  return?: number | null;
  return_over_20?: number | null;
  volatility?: number | null;
  volatility_regime?: string | null;
  atr_percent?: number | null;
  volume_change?: number | null;
  data_status: DataStatusValue;
  quality: QualityValue | string;
  source?: string | null;
  sample_size?: number;
  error?: string;
}

export interface MultiTimeframeResponse {
  symbol: string;
  rows: MultiTimeframeRow[];
  summary: { short_vs_broader?: Record<string, unknown>; [key: string]: unknown };
  note: string;
  origin: string;
}

// ---------------------------------------------------------------------------
// Forecasting
// ---------------------------------------------------------------------------

export interface ForecastMetrics {
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  directional_accuracy: number | null;
  observations: number;
}

export interface ForecastDetail {
  id: string;
  symbol: string;
  timeframe: string;
  horizon: number;
  generated_at: string;
  prediction: number;
  last_close: number;
  lower_bound: number | null;
  upper_bound: number | null;
  model_name: string;
  model_version: string;
  feature_version: string;
  training_window: number;
  training_end_time: string | null;
  metrics: ForecastMetrics;
  baseline_metrics: ForecastMetrics;
  beats_baseline: boolean;
  data_source: string | null;
  data_quality: QualityValue;
  label: string;
  origin: string;
  limitations: string[];
}

export interface ValidationRow {
  model: string;
  kind: string;
  metrics: ForecastMetrics;
  folds: number;
  observations: number;
  feature_importance?: Record<string, number> | null;
}

export interface ForecastResponse {
  symbol: string;
  timeframe: string;
  timeframe_label: string;
  horizon: number;
  horizon_seconds: number | null;
  target_timestamp: string | null;
  status: DataStatusValue;
  quality: QualityValue;
  data_quality_detail: QualityAssessment | null;
  source: string | null;
  candles_used: number;
  forecast: ForecastDetail | null;
  reason: string | null;
  label: string;
  origin: string;
  validation: ValidationRow[];
  baselines: string[];
  anomaly: Record<string, unknown> | null;
  drift: Record<string, unknown> | null;
  limitations: string[];
  diagnostics: Record<string, unknown>;
  residual_std: number | null;
  note: string;
}

export interface ForecastHistoryResponse {
  symbol: string;
  count: number;
  forecasts: Record<string, unknown>[];
  note: string;
  origin: string;
}

export interface FeatureDrift {
  feature: string;
  psi: number | null;
  ks_statistic: number | null;
  ks_pvalue: number | null;
  status: string;
}

export interface DriftResponse {
  symbol: string;
  timeframe: string;
  status: "STABLE" | "WATCH" | "MODEL PERFORMANCE DEGRADED" | "UNKNOWN";
  compared_at?: string;
  reference_size?: number;
  recent_size?: number;
  degraded_share?: number;
  training_age_days?: number | null;
  note?: string;
  features?: FeatureDrift[];
  reason?: string;
  origin?: string;
}

export interface ForecastPerformanceResponse {
  status: "OK" | "UNAVAILABLE";
  evaluations: number;
  mae: number | null;
  directional_accuracy: number | null;
  interval_coverage: number | null;
  latest_evaluated_at: string | null;
  models: string[];
  reason?: string;
  origin: string;
}

// ---------------------------------------------------------------------------
// Targets / thresholds
// ---------------------------------------------------------------------------

export type TargetStatusValue =
  | "ACTIVE"
  | "REACHED"
  | "MISSED"
  | "EXPIRED"
  | "INVALIDATED";

export interface TargetProximity {
  distance: number | null;
  distance_percent: number | null;
  direction_from_price?: "above" | "below" | "at";
  reason?: string;
}

export interface EvaluatedTarget {
  target: {
    id: string;
    symbol: string;
    target_price: number;
    direction: "above" | "below";
    target_date: string | null;
    created_at: string;
    source: string;
    methodology: string;
    status: TargetStatusValue;
    first_reached_at: string | null;
    notes: string | null;
  };
  status: TargetStatusValue;
  touch_count: number | null;
  crossing_count: number | null;
  last_touched_at: string | null;
  proximity: TargetProximity | null;
  current_price: number | null;
  source: string | null;
  data_status: DataStatusValue;
  note: string | null;
}

export interface LadderLevel {
  rank: number;
  target_price: number;
  direction: "above" | "below";
  level_type: "support" | "resistance";
  observed_at: string;
  distance: number;
  distance_percent: number;
  origin: string;
  methodology: string;
}

export interface TargetsResponse {
  symbol: string;
  current_price: number | null;
  source: string | null;
  data_status: DataStatusValue;
  targets: EvaluatedTarget[];
  active_count: number;
  reached_count: number;
  derived_ladder: LadderLevel[];
  lookback_days: number;
  note: string;
  origin: string;
}

export interface TargetHistoryResponse {
  symbol: string;
  target_count: number;
  event_count: number;
  events: Record<string, unknown>[];
  note: string;
}

export interface TargetCreateResult {
  status: "CREATED" | "REJECTED";
  origin?: string;
  target?: EvaluatedTarget["target"];
  target_status?: TargetStatusValue;
  touch_count?: number | null;
  crossing_count?: number | null;
  last_touched_at?: string | null;
  proximity?: number | null;
  current_price?: number | null;
  source?: string | null;
  data_status?: DataStatusValue;
  note?: string | null;
  reason?: string;
}

export interface TargetInvalidateResult {
  status: "INVALIDATED" | "NOT_FOUND";
  target_id: string;
}

export interface ReliabilityBin {
  lower: number | null;
  upper: number | null;
  count: number;
  mean_predicted: number | null;
  observed_frequency: number | null;
}

export interface CalibrationReport {
  status: string;
  samples: number;
  brier_score: number | null;
  base_rate: number | null;
  brier_skill_score: number | null;
  threshold: number | null;
  horizon: number;
  note: string;
  bins: ReliabilityBin[];
}

export interface ThresholdResponse {
  symbol: string;
  timeframe: string;
  threshold: number;
  horizon: number;
  direction: "above" | "below";
  currency: string;
  current_price: number | null;
  distance_percent: number | null;
  probabilities: { empirical: number | null; model_gbm: number | null; samples: number } | null;
  calibration: CalibrationReport | null;
  label: string;
  origin: string;
  status: DataStatusValue;
  reason?: string;
  note?: string;
  source?: string | null;
  candles_used?: number;
}

export interface OnDateResponse {
  symbol: string;
  source: string | null;
  status: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Categories views
// ---------------------------------------------------------------------------

export interface TrendingCoin {
  id: string;
  name: string;
  symbol: string;
  market_cap_rank: number | null;
  thumb: string | null;
  source?: string;
  [key: string]: unknown;
}

export interface PreSessionResponse {
  category: string;
  label: string;
  market_structure: { is_24_7: boolean; statement: string; origin: string };
  session_boundaries: {
    period: string;
    current_period_start: string;
    next_boundary: string;
    seconds_to_boundary: number;
    basis: string;
    origin: string;
  }[];
  market_events: null;
  event_source_note: string;
  trending: TrendingCoin[] | null;
  trending_status: DataStatusValue;
  trending_source: string | null;
  trending_note: string;
}

export interface InstitutionsResponse {
  category: string;
  symbol: string;
  disclosed_holdings: {
    source: string | null;
    asset: string | null;
    total_holdings: number | null;
    total_value_usd: number | null;
    market_cap_dominance_percent: number | null;
    company_count: number | null;
    companies: number | null;
    coverage: string | null;
    limitations: string[] | null;
    origin: string;
  } | null;
  etf_flows: null;
  etf_flows_status: DataStatusValue;
  etf_flows_note: string;
  onchain_holder_data: null;
  onchain_note: string;
  status: DataStatusValue;
  reason?: string;
  note?: string;
}

export interface SourceCategory {
  id: string | null;
  name: string | null;
  market_cap: number | null;
  market_cap_change_24h: number | null;
  source?: string;
  [key: string]: unknown;
}

export interface IndustryResponse {
  category: string;
  taxonomy: {
    type: string;
    basis: string;
    industries: {
      id: string;
      label: string;
      definition: string;
      symbols: string[];
      count: number;
    }[];
    origin: string;
  };
  source_categories: SourceCategory[] | null;
  source_categories_status: DataStatusValue;
  source_categories_note?: string;
}

// ---------------------------------------------------------------------------
// Operations
// ---------------------------------------------------------------------------

export interface CryptoHealthResponse {
  status: string;
  providers: ProviderHealthEntry[];
  count: number;
}

export interface ProbeResponse {
  providers: {
    provider: string;
    available: boolean;
    status: string;
    latency_ms: number | null;
    detail: string | null;
  }[];
  available: number;
  count: number;
}

export interface ObservabilityResponse {
  cache_entries: number;
  providers: Record<string, unknown>;
  health: Record<string, unknown>[];
  timeframes: number;
  assets: number;
  value_origins: Record<string, string>;
}

export interface PersistenceResponse {
  counts: Record<string, number>;
  note: string;
}

export interface RateLimitResponse {
  max_requests: number;
  window_seconds: number;
  tracked_clients: number;
  ws_max_connections: number;
}

// ---------------------------------------------------------------------------
// Service — the only place crypto URLs live
// ---------------------------------------------------------------------------

export const CryptoService = {
  // reference
  getAssets: () => cryptoGet<CryptoAssetsResponse>("/assets"),
  getTimeframes: () => cryptoGet<TimeframesResponse>("/timeframes"),
  getSources: () => cryptoGet<SourcesResponse>("/sources"),
  getCategories: () => cryptoGet<CategoriesResponse>("/categories"),
  getPreSession: () => cryptoGet<PreSessionResponse>("/categories/pre-session"),
  getInstitutions: (symbol: string) =>
    cryptoGet<InstitutionsResponse>(`/categories/institutions/${encodeURIComponent(symbol)}`),
  getIndustry: () => cryptoGet<IndustryResponse>("/categories/industry"),

  // market data
  getQuote: (symbol: string) => cryptoGet<QuotePayload>(`/quote/${encodeURIComponent(symbol)}`),
  getCandles: (
    symbol: string,
    params: { timeframe?: string | null; limit?: number; display_points?: number; raw?: boolean } = {}
  ) =>
    cryptoGet<CandlesResponse>(`/candles/${encodeURIComponent(symbol)}`, {
      timeframe: params.timeframe ?? undefined,
      limit: params.limit,
      display_points: params.display_points,
      raw: params.raw,
    }),
  getAnalytics: (symbol: string, timeframe?: string | null, limit?: number) =>
    cryptoGet<AnalyticsResponse>(`/analytics/${encodeURIComponent(symbol)}`, {
      timeframe: timeframe ?? undefined,
      limit,
    }),
  getMultiTimeframe: (symbol: string) =>
    cryptoGet<MultiTimeframeResponse>(`/multi-timeframe/${encodeURIComponent(symbol)}`),

  // forecasting
  getForecast: (
    symbol: string,
    params: { timeframe?: string | null; horizon?: number; persist?: boolean } = {}
  ) =>
    cryptoGet<ForecastResponse>(`/forecast/${encodeURIComponent(symbol)}`, {
      timeframe: params.timeframe ?? undefined,
      horizon: params.horizon,
      persist: params.persist,
    }),
  getForecastHistory: (symbol: string, timeframe?: string | null, limit = 50) =>
    cryptoGet<ForecastHistoryResponse>(`/forecast/${encodeURIComponent(symbol)}/history`, {
      timeframe: timeframe ?? undefined,
      limit,
    }),
  getForecastDrift: (symbol: string, timeframe?: string | null) =>
    cryptoGet<DriftResponse>(`/forecast/${encodeURIComponent(symbol)}/drift`, {
      timeframe: timeframe ?? undefined,
    }),
  getForecastPerformance: (symbol?: string | null) =>
    cryptoGet<ForecastPerformanceResponse>("/forecast-performance", {
      symbol: symbol ?? undefined,
    }),

  // targets / thresholds
  getTargets: (symbol: string, includeDerived = true) =>
    cryptoGet<TargetsResponse>(`/targets/${encodeURIComponent(symbol)}`, {
      include_derived: includeDerived,
    }),
  getTargetHistory: (symbol: string) =>
    cryptoGet<TargetHistoryResponse>(`/targets/${encodeURIComponent(symbol)}/history`),
  getLadder: (symbol: string, count?: number) =>
    cryptoGet<{ symbol: string; current_price: number | null; source: string | null; levels: LadderLevel[]; count: number; note: string; origin: string }>(
      `/targets/${encodeURIComponent(symbol)}/ladder`,
      { count }
    ),
  createTarget: async (payload: {
    symbol: string;
    target_price: number;
    direction: "above" | "below";
    target_date?: string | null;
    notes?: string | null;
  }): Promise<CryptoEnvelope<TargetCreateResult>> => {
    const res = await apiClient.post<CryptoEnvelope<TargetCreateResult>>(
      "/api/v1/crypto/targets",
      payload
    );
    return res.data;
  },
  invalidateTarget: async (targetId: string): Promise<CryptoEnvelope<TargetInvalidateResult>> => {
    const res = await apiClient.post<CryptoEnvelope<TargetInvalidateResult>>(
      "/api/v1/crypto/targets/invalidate",
      { target_id: targetId }
    );
    return res.data;
  },
  getThreshold: (
    symbol: string,
    params: { threshold: number; timeframe?: string | null; horizon?: number; direction?: "above" | "below" }
  ) =>
    cryptoGet<ThresholdResponse>(`/threshold/${encodeURIComponent(symbol)}`, {
      threshold: params.threshold,
      timeframe: params.timeframe ?? undefined,
      horizon: params.horizon,
      direction: params.direction ?? "above",
    }),
  getOnDate: (
    symbol: string,
    params: { date: string; threshold?: number; direction?: "above" | "below" }
  ) =>
    cryptoGet<OnDateResponse>(`/on-date/${encodeURIComponent(symbol)}`, {
      date: params.date,
      threshold: params.threshold,
      direction: params.direction ?? "above",
    }),

  // operations
  getHealth: () => cryptoGet<CryptoHealthResponse>("/health"),
  probeHealth: () => cryptoGet<ProbeResponse>("/health/probe"),
  getObservability: () => cryptoGet<ObservabilityResponse>("/observability"),
  getPersistence: () => cryptoGet<PersistenceResponse>("/persistence"),
  getRateLimit: () => cryptoGet<RateLimitResponse>("/rate-limit"),
};

// ---------------------------------------------------------------------------
// WebSocket endpoint
// ---------------------------------------------------------------------------

/** Absolute or proxied WebSocket URL for the crypto stream. */
export function cryptoSocketUrl(clientId: string): string {
  const configured = import.meta.env.VITE_WS_URL;
  const base =
    configured ||
    (typeof window !== "undefined"
      ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
      : "ws://127.0.0.1:8000");
  return `${base.replace(/\/+$/, "")}/api/v1/crypto/ws/${encodeURIComponent(clientId)}`;
}

/** A stable per-browser client id for the bounded WS gateway (spec §89). */
export function cryptoClientId(): string {
  try {
    const key = "cryptoWsClientId";
    let id = window.localStorage.getItem(key);
    if (!id) {
      id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `c-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
      window.localStorage.setItem(key, id);
    }
    return id;
  } catch {
    return `c-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  }
}
