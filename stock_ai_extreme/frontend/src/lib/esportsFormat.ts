/**
 * Phase 21B — pure esports display helpers.
 *
 * Deliberately dependency-free (no axios, no React, no import.meta) so it can
 * be bundled and unit-tested in isolation by `npm run test:esports`, exactly
 * like the other `*Format`-style helpers in this codebase. Nothing here fetches
 * or invents a value; it only labels and formats what the backend supplied.
 */

export type MatchStatusValue =
  | "SCHEDULED"
  | "UPCOMING"
  | "LIVE"
  | "PAUSED"
  | "MAP_BREAK"
  | "COMPLETED"
  | "CANCELLED"
  | "POSTPONED"
  | "UNKNOWN";

export type DataMode = "LIVE" | "DELAYED" | "STALE" | "UNAVAILABLE";

export type StatusTone = "live" | "upcoming" | "paused" | "completed" | "neutral";

export interface StatusMeta {
  label: string;
  tone: StatusTone;
}

export const STATUS_META: Record<MatchStatusValue, StatusMeta> = {
  LIVE: { label: "Live", tone: "live" },
  PAUSED: { label: "Paused", tone: "paused" },
  MAP_BREAK: { label: "Map break", tone: "paused" },
  UPCOMING: { label: "Upcoming", tone: "upcoming" },
  SCHEDULED: { label: "Scheduled", tone: "upcoming" },
  COMPLETED: { label: "Completed", tone: "completed" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
  POSTPONED: { label: "Postponed", tone: "neutral" },
  UNKNOWN: { label: "Unknown", tone: "neutral" },
};

export function statusMeta(status: string | null | undefined): StatusMeta {
  const key = (status || "UNKNOWN").toUpperCase() as MatchStatusValue;
  return STATUS_META[key] ?? STATUS_META.UNKNOWN;
}

export const GAME_LABELS: Record<string, string> = {
  cs2: "Counter-Strike 2",
  lol: "League of Legends",
  dota2: "Dota 2",
};

export const GAME_SHORT: Record<string, string> = {
  cs2: "CS2",
  lol: "LoL",
  dota2: "Dota 2",
};

/** Games the hub is built around, in display order. */
export const HUB_GAMES = ["cs2", "lol", "dota2"] as const;

export function gameLabel(gameId: string): string {
  return GAME_LABELS[gameId] ?? gameId.toUpperCase();
}

export function gameShort(gameId: string): string {
  return GAME_SHORT[gameId] ?? gameId.toUpperCase();
}

/** "N/A" for every missing metric — the honest rendering of null. */
export const NA = "N/A";

export function relTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return NA;
  const diff = Date.now() - then;
  const sign = diff < 0 ? -1 : 1;
  const abs = Math.abs(diff);
  const minutes = Math.floor(abs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return sign < 0 ? `in ${minutes}m` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return sign < 0 ? `in ${hours}h` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return sign < 0 ? `in ${days}d` : `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDay(iso: string | null | undefined): string {
  if (!iso) return NA;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "MM:SS" from a seconds count; null/negative → "N/A". */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) return NA;
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

export function dataModeTone(mode: string | null | undefined): StatusTone {
  switch ((mode || "").toUpperCase()) {
    case "LIVE":
      return "live";
    case "DELAYED":
      return "upcoming";
    case "STALE":
      return "paused";
    default:
      return "neutral";
  }
}

/** The minimal shape `describeMatch` needs — kept structural for easy testing. */
export interface DescribableMatch {
  game_id: string;
  status: string;
  score_a: number;
  score_b: number;
  tournament_name?: string | null;
  team_a: { id: string; name: string | null };
  team_b: { id: string; name: string | null };
  winner_id?: string | null;
}

/**
 * A screen-reader description of a match's live state (§20).
 * Example: "Live Counter-Strike 2 match. Spirit leads Falcons two maps to zero."
 */
export function describeMatch(match: DescribableMatch): string {
  const game = gameLabel(match.game_id);
  const a = match.team_a.name || "Team A";
  const b = match.team_b.name || "Team B";
  const meta = statusMeta(match.status);
  const score = `${match.score_a} to ${match.score_b}`;
  if (match.status === "COMPLETED" && match.winner_id) {
    const winner =
      match.winner_id === match.team_a.id ? a : match.winner_id === match.team_b.id ? b : null;
    return `${meta.label} ${game} match. ${winner ? `${winner} won` : "Final score"} ${score}.`;
  }
  if (match.status === "LIVE" || match.status === "PAUSED" || match.status === "MAP_BREAK") {
    if (match.score_a === match.score_b) {
      return `${meta.label} ${game} match. ${a} and ${b} are tied ${score}.`;
    }
    const leader = match.score_a > match.score_b ? a : b;
    const trailer = match.score_a > match.score_b ? b : a;
    return `${meta.label} ${game} match. ${leader} leads ${trailer} ${score}.`;
  }
  return `${meta.label} ${game} match. ${a} versus ${b}.`;
}

/** Deterministic, url-safe client id for the WebSocket connection. */
export function esportsClientId(): string {
  return `hub-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}
