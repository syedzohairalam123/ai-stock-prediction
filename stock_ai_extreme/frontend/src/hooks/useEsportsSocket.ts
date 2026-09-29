/**
 * Phase 21B — esports WebSocket hook.
 *
 * One hook call per page owns the single socket for that page. It:
 *  - subscribes to the match channel, a game channel, or the cross-game
 *    firehose that feeds the activity ticker;
 *  - reconnects with capped exponential backoff (§16);
 *  - on every (re)connect requests a fresh snapshot and REPLACES local state
 *    instead of replaying missed events onto a stale client (§17);
 *  - dispatches each frame into the store where a memoized slice keeps the
 *    re-render scoped to the ticker / scoreboard (§10).
 */
import { useEffect } from "react";

import { esportsClientId, esportsSocketUrl } from "../lib/esports";
import type { EsportsEvent, EsportsSnapshot } from "../lib/esports";
import { useEsportsStore } from "../store/useEsportsStore";

export interface EsportsSocketOptions {
  /** Subscribe to a single match's channel. */
  matchId?: string | null;
  /** Subscribe to one game's channel. */
  gameId?: string | null;
  /** Subscribe to every event (hub ticker). Ignored when matchId/gameId is set. */
  all?: boolean;
  /** Set false to hold the connection closed. */
  enabled?: boolean;
}

const MAX_BACKOFF_MS = 15_000;

export function useEsportsSocket(options: EsportsSocketOptions = {}) {
  const { matchId = null, gameId = null, all = false, enabled = true } = options;
  const setConnection = useEsportsStore((s) => s.setConnection);
  const applySnapshot = useEsportsStore((s) => s.applySnapshot);
  const applyEvent = useEsportsStore((s) => s.applyEvent);
  const noteMessage = useEsportsStore((s) => s.noteMessage);

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let socket: WebSocket | undefined;
    let attempt = 0;
    let retryTimer: number | undefined;
    let connectTimer: number | undefined;
    const clientId = esportsClientId();

    const send = (payload: Record<string, unknown>) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
      }
    };

    const subscribe = () => {
      if (matchId) send({ type: "subscribe", match_id: matchId });
      else if (gameId) send({ type: "subscribe", game_id: gameId });
      else if (all) send({ type: "subscribe", channel: "all" });
    };

    /** §17: replace stale local state with an authoritative snapshot. */
    const requestSnapshot = () => {
      if (matchId) send({ type: "snapshot", match_id: matchId });
      send({ type: "ping" });
    };

    const connect = () => {
      if (stopped) return;
      setConnection(attempt === 0 ? "connecting" : "reconnecting");
      let ws: WebSocket;
      try {
        ws = new WebSocket(esportsSocketUrl(clientId));
      } catch {
        scheduleRetry();
        return;
      }
      socket = ws;

      ws.onopen = () => {
        if (stopped) {
          ws.close();
          return;
        }
        attempt = 0;
        setConnection("connected");
        subscribe();
        requestSnapshot();
      };

      ws.onmessage = (message) => {
        noteMessage();
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(message.data as string);
        } catch {
          return;
        }
        const type = payload.type as string | undefined;
        if (type === "snapshot") {
          const snap = payload.data as EsportsSnapshot | null;
          if (snap && typeof snap === "object" && "match_id" in snap) {
            applySnapshot(snap);
          }
        } else if (type === "event") {
          const event = payload.data as EsportsEvent | undefined;
          if (event && typeof event === "object" && "id" in event) {
            applyEvent(event);
          }
        }
      };

      ws.onerror = () => {
        /* onclose follows and handles the retry */
      };

      ws.onclose = () => {
        if (!stopped) scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      attempt += 1;
      setConnection("reconnecting");
      const delay = Math.min(1000 * 2 ** Math.min(attempt, 4), MAX_BACKOFF_MS);
      retryTimer = window.setTimeout(connect, delay);
    };

    // Defer one tick: React StrictMode double-mounts effects in dev, and the
    // first mount's cleanup would otherwise close a socket still CONNECTING.
    connectTimer = window.setTimeout(connect, 0);

    return () => {
      stopped = true;
      window.clearTimeout(connectTimer);
      window.clearTimeout(retryTimer);
      socket?.close();
      setConnection("disconnected");
    };
  }, [matchId, gameId, all, enabled, setConnection, applySnapshot, applyEvent, noteMessage]);
}
