/**
 * Phase 21B — Esports Hub data layer.
 *
 * One typed client for every `/api/esports*` endpoint. The honesty contract
 * mirrored from the backend:
 *
 *  - `null`/`undefined` means the source did not publish the field; it renders
 *    as the labelled `NA` fallback, never a fabricated 0 or placeholder;
 *  - `data_mode` / `data_quality` are the source's own freshness labels;
 *  - no team, player, score or timestamp is invented client-side.
 *
 * Pure display helpers live in `./esportsFormat` (dependency-free, unit-tested
 * by `npm run test:esports`) and are re-exported here for ergonomic imports.
 */
import apiClient from "./axios";
import type { DataMode, MatchStatusValue } from "./esportsFormat";

export {
  STATUS_META,
  GAME_LABELS,
  GAME_SHORT,
  HUB_GAMES,
  NA,
  statusMeta,
  gameLabel,
  gameShort,
  relTime,
  formatDateTime,
  formatDay,
  formatClock,
  dataModeTone,
  describeMatch,
  esportsClientId,
} from "./esportsFormat";
export type { MatchStatusValue, DataMode, StatusTone, StatusMeta, DescribableMatch } from "./esportsFormat";

// ---------------------------------------------------------------------------
// Types (mirror the backend contract field for field)
// ---------------------------------------------------------------------------

export interface TeamRef {
  id: string;
  name: string | null;
  logo_url: string | null;
  short_name?: string | null;
  region?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MatchGame {
  match_id?: number | string;
  duration?: number;
  radiant_score?: number;
  dire_score?: number;
  radiant_win?: boolean;
  start_time?: number;
  map_number?: number;
  name?: string;
  team_a_score?: number;
  team_b_score?: number;
  number?: number;
  state?: string;
}

export interface EsportsMatch {
  id: string;
  external_id: string;
  game_id: string;
  tournament_id: string;
  tournament_name: string | null;
  series_id: string;
  status: MatchStatusValue;
  scheduled_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  best_of: number;
  current_map: string | null;
  map_number: number;
  score_a: number;
  score_b: number;
  winner_id: string | null;
  team_a: TeamRef;
  team_b: TeamRef;
  source: string;
  last_updated: string | null;
  data_mode: DataMode | string;
  data_quality: DataMode | string;
  game_state: Record<string, unknown>;
  games: MatchGame[];
  /** Elapsed game seconds when the source publishes it; null otherwise. */
  game_time_seconds: number | null;
  region: string | null;
}

export interface EsportsPlayer {
  id: string;
  external_id: string;
  name: string;
  handle: string;
  team_id: string;
  game_id: string;
  role: string | null;
  country: string | null;
  meta_data: Record<string, unknown>;
}

export interface EsportsEvent {
  id: string;
  match_id: string;
  game_id: string;
  type: string;
  timestamp: string;
  sequence: number;
  team_id: string | null;
  player_id: string | null;
  payload: Record<string, unknown>;
  source: string;
  source_timestamp: string | null;
  received_at: string;
}

export interface EsportsSnapshot {
  match_id: string;
  game_id: string;
  status: MatchStatusValue;
  current_map: string | null;
  map_number: number;
  score_a: number;
  score_b: number;
  team_a_id: string;
  team_b_id: string;
  current_map_scores: Record<string, Record<string, number>>;
  game_state: Record<string, unknown>;
  timestamp: string;
  data_age_seconds: number | null;
  data_status: DataMode | string;
}

export interface SourceStatus {
  name: string;
  status: string;
  last_success?: string | null;
  request_count?: number;
  error_count?: number;
  avg_latency_ms?: number;
  data_mode?: string | null;
  refresh?: string | null;
  error?: string;
}

export interface MatchDetail extends EsportsMatch {
  players: { team_a: EsportsPlayer[]; team_b: EsportsPlayer[] };
  snapshot: EsportsSnapshot | null;
  events: EsportsEvent[];
  event_count: number;
  data_sources: SourceStatus[];
}

export interface GameCounts {
  live: number;
  upcoming: number;
  recent: number;
  total: number;
  tournaments: number;
}

export interface GameSummary {
  game_id: string;
  name: string;
  short_name: string;
  source: string;
  counts: GameCounts;
  activity: { label: string; value: number };
  last_updated: string | null;
  data_mode: DataMode | string;
  tournament_count_window_days?: number;
}

export interface GamesSummaryResponse {
  games: GameSummary[];
  generated_at: string;
  window?: { recent_days: number; note: string };
}

export interface MatchFeedResponse {
  matches: EsportsMatch[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  generated_at: string;
  filters: Record<string, unknown>;
}

export interface FeaturedResponse {
  featured: EsportsMatch | null;
  generated_at: string;
}

export interface EsportsTournament {
  id: string;
  external_id: string;
  name: string;
  game_id: string;
  start_date: string | null;
  end_date: string | null;
  prize_pool: number | null;
  region: string | null;
  status: string;
  metadata: Record<string, unknown>;
}

export interface TournamentDetail extends EsportsTournament {
  matches: EsportsMatch[];
  match_count: number;
  generated_at: string;
}

export interface EsportsGame {
  id: string;
  external_id: string;
  name: string;
  short_name: string;
  source: string;
  meta_data: Record<string, unknown>;
}

export interface MatchFeedParams {
  game_id?: string | null;
  statuses?: MatchStatusValue[] | null;
  live?: boolean;
  upcoming?: boolean;
  tournament_id?: string | null;
  region?: string | null;
  q?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  limit?: number;
  offset?: number;
}

function buildFeedQuery(params: MatchFeedParams): Record<string, string | number | boolean> {
  const query: Record<string, string | number | boolean> = {};
  if (params.game_id) query.game_id = params.game_id;
  if (params.statuses?.length) query.status = params.statuses.join(",");
  if (params.live) query.live = true;
  if (params.upcoming) query.upcoming = true;
  if (params.tournament_id) query.tournament_id = params.tournament_id;
  if (params.region) query.region = params.region;
  if (params.q) query.q = params.q;
  if (params.date_from) query.date_from = params.date_from;
  if (params.date_to) query.date_to = params.date_to;
  if (params.limit) query.limit = params.limit;
  if (params.offset) query.offset = params.offset;
  return query;
}

// ---------------------------------------------------------------------------
// Service — the only place esports URLs live
// ---------------------------------------------------------------------------

export const EsportsService = {
  async getGames(): Promise<{ games: EsportsGame[]; count: number }> {
    const res = await apiClient.get("/api/esports/games");
    return res.data;
  },

  async getGamesSummary(): Promise<GamesSummaryResponse> {
    const res = await apiClient.get<GamesSummaryResponse>("/api/esports/games/summary");
    return res.data;
  },

  async getGameSummary(gameId: string): Promise<GamesSummaryResponse> {
    const res = await apiClient.get<GamesSummaryResponse>(`/api/esports/games/${gameId}/summary`);
    return res.data;
  },

  async getFeatured(gameId?: string | null): Promise<FeaturedResponse> {
    const res = await apiClient.get<FeaturedResponse>("/api/esports/featured", {
      params: gameId ? { game_id: gameId } : undefined,
    });
    return res.data;
  },

  async getMatches(params: MatchFeedParams): Promise<MatchFeedResponse> {
    const res = await apiClient.get<MatchFeedResponse>("/api/esports/matches", {
      params: buildFeedQuery(params),
    });
    return res.data;
  },

  async getMatch(matchId: string): Promise<EsportsMatch> {
    const res = await apiClient.get<EsportsMatch>(`/api/esports/matches/${encodeURIComponent(matchId)}`);
    return res.data;
  },

  async getMatchDetail(matchId: string): Promise<MatchDetail> {
    const res = await apiClient.get<MatchDetail>(
      `/api/esports/matches/${encodeURIComponent(matchId)}/detail`
    );
    return res.data;
  },

  async getMatchEvents(matchId: string): Promise<{ events: EsportsEvent[]; count: number }> {
    const res = await apiClient.get(`/api/esports/matches/${encodeURIComponent(matchId)}/events`);
    return res.data;
  },

  async getMatchLive(matchId: string): Promise<EsportsSnapshot> {
    const res = await apiClient.get<EsportsSnapshot>(
      `/api/esports/matches/${encodeURIComponent(matchId)}/live`
    );
    return res.data;
  },

  async getTournament(tournamentId: string): Promise<TournamentDetail> {
    const res = await apiClient.get<TournamentDetail>(
      `/api/esports/tournaments/${encodeURIComponent(tournamentId)}`
    );
    return res.data;
  },

  async getGameTournaments(gameId: string): Promise<{ tournaments: EsportsTournament[]; count: number }> {
    const res = await apiClient.get(`/api/esports/games/${gameId}/tournaments`);
    return res.data;
  },

  async getSources(): Promise<{ providers: SourceStatus[]; count: number }> {
    const res = await apiClient.get("/api/esports/sources");
    return res.data;
  },
};

// ---------------------------------------------------------------------------
// WebSocket endpoint
// ---------------------------------------------------------------------------

/** Absolute or proxied WebSocket URL for the esports stream. */
export function esportsSocketUrl(clientId: string): string {
  const configured = import.meta.env.VITE_WS_URL;
  const base =
    configured ||
    (typeof window !== "undefined"
      ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
      : "ws://127.0.0.1:8000");
  return `${base.replace(/\/+$/, "")}/api/esports/ws/${encodeURIComponent(clientId)}`;
}
