/**
 * Phase 21B — esports real-time store.
 *
 * Holds only the fast-changing real-time state: the WebSocket connection
 * state, the latest per-match snapshots, and a bounded activity buffer for the
 * ticker. Server data (match lists, details, tournaments) lives in React
 * Query, not here.
 *
 * Two properties matter for §10/§26 performance:
 *  - updates are immutable and slice-scoped, so a component that selects only
 *    `events` never re-renders when a snapshot changes, and vice-versa;
 *  - every buffer is capped, so a long-lived live match cannot grow memory or
 *    mount thousands of timeline rows (§27).
 */
import { create } from "zustand";

import type { EsportsEvent, EsportsSnapshot } from "../lib/esports";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected";

/** Most recent events kept for the ticker / timeline (mobile-safe bound). */
export const MAX_TICKER_EVENTS = 120;
const MAX_MATCH_EVENTS = 240;

interface EsportsState {
  connection: ConnectionState;
  connectedAt: string | null;
  lastMessageAt: string | null;
  /** Cross-game activity feed, newest first. */
  events: EsportsEvent[];
  /** Events keyed by match id, newest first (bounded per match). */
  matchEvents: Record<string, EsportsEvent[]>;
  /** Latest snapshot keyed by match id. */
  snapshots: Record<string, EsportsSnapshot>;

  setConnection: (state: ConnectionState) => void;
  noteMessage: () => void;
  applySnapshot: (snapshot: EsportsSnapshot) => void;
  applyEvent: (event: EsportsEvent) => void;
  seedMatchEvents: (matchId: string, events: EsportsEvent[]) => void;
  clearMatchEvents: (matchId: string) => void;
  reset: () => void;
}

function dedupePrepend(list: EsportsEvent[], event: EsportsEvent, cap: number): EsportsEvent[] {
  // Events have stable ids; ignore a replay and keep the buffer bounded.
  const without = list.some((existing) => existing.id === event.id)
    ? list.filter((existing) => existing.id !== event.id)
    : list;
  return [event, ...without].slice(0, cap);
}

/**
 * Fold an event into a snapshot so the scoreboard reflects live score changes
 * without waiting for the next full snapshot frame.
 */
function foldEventIntoSnapshot(
  snapshot: EsportsSnapshot | undefined,
  event: EsportsEvent
): EsportsSnapshot | undefined {
  if (!snapshot || snapshot.match_id !== event.match_id) return snapshot;
  const payload = event.payload || {};
  const num = (value: unknown, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback;

  switch (event.type) {
    case "SCORE_CHANGED":
      return {
        ...snapshot,
        score_a: num(payload.team_a_score, snapshot.score_a),
        score_b: num(payload.team_b_score, snapshot.score_b),
        timestamp: event.timestamp,
      };
    case "MAP_STARTED":
      return {
        ...snapshot,
        status: "LIVE",
        map_number: num(payload.map_number, snapshot.map_number),
        current_map:
          typeof payload.map_name === "string" ? payload.map_name : snapshot.current_map,
        timestamp: event.timestamp,
      };
    case "MAP_ENDED":
      return { ...snapshot, status: "MAP_BREAK", timestamp: event.timestamp };
    case "MATCH_PAUSED":
      return { ...snapshot, status: "PAUSED", timestamp: event.timestamp };
    case "MATCH_RESUMED":
      return { ...snapshot, status: "LIVE", timestamp: event.timestamp };
    case "MATCH_STARTED":
      return { ...snapshot, status: "LIVE", timestamp: event.timestamp };
    case "MATCH_ENDED":
      return { ...snapshot, status: "COMPLETED", timestamp: event.timestamp };
    default:
      return snapshot;
  }
}

export const useEsportsStore = create<EsportsState>()((set) => ({
  connection: "disconnected",
  connectedAt: null,
  lastMessageAt: null,
  events: [],
  matchEvents: {},
  snapshots: {},

  setConnection: (connection) =>
    set((state) => ({
      connection,
      connectedAt: connection === "connected" ? new Date().toISOString() : state.connectedAt,
    })),

  noteMessage: () => set({ lastMessageAt: new Date().toISOString() }),

  applySnapshot: (snapshot) =>
    set((state) => ({
      snapshots: { ...state.snapshots, [snapshot.match_id]: snapshot },
    })),

  applyEvent: (event) =>
    set((state) => {
      const existingMatchEvents = state.matchEvents[event.match_id] ?? [];
      const folded = foldEventIntoSnapshot(state.snapshots[event.match_id], event);
      return {
        events: dedupePrepend(state.events, event, MAX_TICKER_EVENTS),
        matchEvents: {
          ...state.matchEvents,
          [event.match_id]: dedupePrepend(existingMatchEvents, event, MAX_MATCH_EVENTS),
        },
        snapshots: folded
          ? { ...state.snapshots, [event.match_id]: folded }
          : state.snapshots,
        lastMessageAt: new Date().toISOString(),
      };
    }),

  seedMatchEvents: (matchId, events) =>
    set((state) => {
      const sorted = [...events]
        .sort((a, b) => b.sequence - a.sequence || (b.timestamp > a.timestamp ? 1 : -1))
        .slice(0, MAX_MATCH_EVENTS);
      return { matchEvents: { ...state.matchEvents, [matchId]: sorted } };
    }),

  clearMatchEvents: (matchId) =>
    set((state) => {
      if (!(matchId in state.matchEvents)) return state;
      const next = { ...state.matchEvents };
      delete next[matchId];
      return { matchEvents: next };
    }),

  reset: () =>
    set({ connection: "disconnected", connectedAt: null, lastMessageAt: null, events: [], matchEvents: {}, snapshots: {} }),
}));

/** Convenience selector: newest snapshot for one match (undefined until seen). */
export function selectSnapshot(matchId: string | undefined) {
  return (state: EsportsState) => (matchId ? state.snapshots[matchId] : undefined);
}

/** Convenience selector: the cross-game ticker feed. */
export function selectTickerEvents(state: EsportsState) {
  return state.events;
}

/** Convenience selector: events for one match. */
export function selectMatchEvents(matchId: string | undefined) {
  return (state: EsportsState) => (matchId ? state.matchEvents[matchId] ?? [] : []);
}
