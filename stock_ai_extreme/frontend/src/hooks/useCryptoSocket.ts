/**
 * Phase 22 — crypto WebSocket hook.
 *
 * One hook call per page owns the single socket for that page. It:
 *  - subscribes to the symbol's tick channel and its timeframe channel
 *    (`crypto:BTC`, `crypto:BTC:5m` — spec §89);
 *  - reconnects with capped exponential backoff;
 *  - on every (re)connect requests an authoritative snapshot and REPLACES the
 *    local view instead of replaying missed events onto stale state (§110);
 *  - handles the gateway's `batch` coalescing frame (spec §90) by dispatching
 *    each inner frame individually;
 *  - dispatches frames into the store where slice-scoped updates keep
 *    re-renders scoped to the affected channel.
 */
import { useEffect } from "react";

import { cryptoClientId, cryptoSocketUrl, type DataStatusValue } from "../lib/crypto";
import { useCryptoStore } from "../store/useCryptoStore";

export interface CryptoSocketOptions {
  /** Internal symbol to stream (e.g. "BTC"). */
  symbol?: string | null;
  /** Timeframe for the candle channel (defaults to "5m" server-side). */
  timeframe?: string | null;
  /** Set false to hold the connection closed. */
  enabled?: boolean;
}

const MAX_BACKOFF_MS = 15_000;

export function useCryptoSocket(options: CryptoSocketOptions = {}) {
  const { symbol = null, timeframe = null, enabled = true } = options;
  const setConnection = useCryptoStore((s) => s.setConnection);
  const noteMessage = useCryptoStore((s) => s.noteMessage);
  const applyTick = useCryptoStore((s) => s.applyTick);
  const applyCandle = useCryptoStore((s) => s.applyCandle);
  const applySnapshot = useCryptoStore((s) => s.applySnapshot);

  useEffect(() => {
    if (!enabled || !symbol) return;

    let stopped = false;
    let socket: WebSocket | undefined;
    let attempt = 0;
    let retryTimer: number | undefined;
    let connectTimer: number | undefined;
    const clientId = cryptoClientId();

    const send = (payload: Record<string, unknown>) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
      }
    };

    const subscribe = () => {
      send({
        type: "subscribe",
        symbol,
        timeframe: timeframe || undefined,
      });
    };

    /** §110: replace stale local state with an authoritative snapshot. */
    const requestSnapshot = () => {
      send({ type: "snapshot", symbol, timeframe: timeframe || undefined });
      send({ type: "ping" });
    };

    /** Dispatch one gateway frame; `batch` frames fan out to this. */
    const handleFrame = (payload: Record<string, unknown>) => {
      const type = payload.type as string | undefined;
      if (type === "tick") {
        applyTick({
          symbol: String(payload.symbol ?? symbol),
          price: typeof payload.price === "number" ? payload.price : null,
          high: typeof payload.high === "number" ? payload.high : null,
          low: typeof payload.low === "number" ? payload.low : null,
          volume: typeof payload.volume === "number" ? payload.volume : null,
          source: (payload.source as string) ?? null,
          sourceTimestamp: (payload.sourceTimestamp as string) ?? null,
          receivedAt: (payload.receivedAt as string) ?? null,
          dataStatus: (payload.dataStatus as string) ?? "LIVE",
          origin: (payload.origin as string) ?? "SOURCE",
        });
      } else if (type === "candle") {
        applyCandle(
          String(payload.symbol ?? symbol),
          String(payload.timeframe ?? timeframe ?? "5m"),
          {
            timestamp: (payload.timestamp as string) ?? "",
            open: typeof payload.open === "number" ? payload.open : null,
            high: typeof payload.high === "number" ? payload.high : null,
            low: typeof payload.low === "number" ? payload.low : null,
            close: typeof payload.close === "number" ? payload.close : null,
            volume: typeof payload.volume === "number" ? payload.volume : null,
            isFinal: Boolean(payload.isFinal),
            source: (payload.source as string) ?? null,
          }
        );
      } else if (type === "snapshot") {
        const quote = (payload.quote ?? null) as Record<string, unknown> | null;
        const candles = Array.isArray(payload.candles) ? payload.candles : [];
        applySnapshot(
          {
            symbol: String(payload.symbol ?? symbol),
            timeframe: (payload.timeframe as string) ?? null,
            dataStatus: (payload.dataStatus as string) ?? null,
            source: (payload.source as string) ?? null,
            candleCount: candles.length,
            receivedAt: (payload.timestamp as string) ?? new Date().toISOString(),
          },
          quote
            ? {
                symbol: String(quote.symbol ?? symbol),
                price: typeof quote.price === "number" ? quote.price : null,
                bid: typeof quote.bid === "number" ? quote.bid : null,
                ask: typeof quote.ask === "number" ? quote.ask : null,
                volume_24h:
                  typeof quote.volume_24h === "number"
                    ? quote.volume_24h
                    : typeof quote.volume === "number"
                      ? quote.volume
                      : null,
                change_percent_24h:
                  typeof quote.change_percent_24h === "number" ? quote.change_percent_24h : null,
                timestamp: (quote.timestamp as string) ?? null,
                source: (quote.source as string) ?? null,
                status: ((quote.status as string) ?? "LIVE") as DataStatusValue,
                age_ms: typeof quote.age_ms === "number" ? quote.age_ms : null,
                currency: (quote.currency as string) ?? "USD",
                origin: (quote.origin as string) ?? "SOURCE",
              }
            : null,
          candles.map((raw) => {
            const c = raw as Record<string, unknown>;
            return {
              timestamp: String(c.timestamp ?? ""),
              epoch_ms: typeof c.epoch_ms === "number" ? c.epoch_ms : 0,
              open: Number(c.open ?? 0),
              high: Number(c.high ?? 0),
              low: Number(c.low ?? 0),
              close: Number(c.close ?? 0),
              volume: Number(c.volume ?? 0),
            };
          })
        );
      }
    };

    const connect = () => {
      if (stopped) return;
      setConnection(attempt === 0 ? "connecting" : "reconnecting");
      let ws: WebSocket;
      try {
        ws = new WebSocket(cryptoSocketUrl(clientId));
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
        if (payload.type === "batch" && Array.isArray(payload.frames)) {
          for (const frame of payload.frames) {
            if (frame && typeof frame === "object") handleFrame(frame as Record<string, unknown>);
          }
          return;
        }
        handleFrame(payload);
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
  }, [symbol, timeframe, enabled, setConnection, noteMessage, applyTick, applyCandle, applySnapshot]);
}
