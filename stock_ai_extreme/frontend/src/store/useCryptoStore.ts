/**
 * Phase 22 — crypto real-time store.
 *
 * Holds only the fast-changing live state fed by the WebSocket gateway:
 * the connection state, the latest quote per symbol, live candle tails per
 * (symbol, timeframe) channel, and snapshot metadata. Server data (assets,
 * analytics, forecasts, targets) lives in React Query, not here.
 *
 * Two properties mirror the esports store (§10/§26 performance):
 *  - updates are immutable and slice-scoped, so a component selecting only
 *    `ticks` never re-renders when candles change, and vice-versa;
 *  - every buffer is capped, so a long-lived stream cannot grow memory (§27).
 */
import { create } from "zustand";

import type { CryptoCandle, QuotePayload } from "../lib/crypto";

export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

/** Rolling price history kept per symbol for the live monitor. */
const MAX_PRICE_HISTORY = 400;

export interface LiveTick {
  symbol: string;
  price: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  source: string | null;
  sourceTimestamp: string | null;
  receivedAt: string | null;
  dataStatus: string;
  origin: string;
}

export interface LiveCandle {
  timestamp: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  isFinal: boolean;
  source: string | null;
}

export interface SnapshotMeta {
  symbol: string;
  timeframe: string | null;
  dataStatus: string | null;
  source: string | null;
  candleCount: number;
  receivedAt: string;
}

interface CryptoState {
  connection: ConnectionState;
  connectedAt: string | null;
  lastMessageAt: string | null;
  /** Latest tick per internal symbol (the `crypto:SYMBOL` channel). */
  ticks: Record<string, LiveTick>;
  /** Rolling price history per symbol for the live monitor (oldest first). */
  tickPrices: Record<string, number[]>;
  /** Bounded live candle tail per channel key `SYMBOL:TIMEFRAME` (oldest first). */
  candleTails: Record<string, LiveCandle[]>;
  /** Last authoritative snapshot metadata per symbol. */
  snapshots: Record<string, SnapshotMeta>;

  setConnection: (state: ConnectionState) => void;
  noteMessage: () => void;
  applyTick: (tick: LiveTick) => void;
  applyCandle: (symbol: string, timeframe: string, candle: LiveCandle) => void;
  applySnapshot: (
    snapshot: SnapshotMeta,
    quote: QuotePayload | null,
    candles: CryptoCandle[]
  ) => void;
  reset: () => void;
}

/** Channel key for a (symbol, timeframe) pair. */
export function cryptoChannelKey(symbol: string, timeframe: string | null): string {
  return `${symbol.toUpperCase()}:${timeframe ?? "default"}`;
}

/**
 * Fold a live candle into a bounded ascending-by-time tail: an existing bar
 * with the same timestamp is updated in place (the provider re-publishes the
 * current bar as it forms), otherwise the bar is appended and the tail trimmed.
 */
function upsertCandleTail(
  existing: LiveCandle[] | undefined,
  incoming: LiveCandle,
  cap: number
): LiveCandle[] {
  const list = existing ? [...existing] : [];
  const index = list.findIndex((c) => c.timestamp === incoming.timestamp);
  if (index >= 0) list[index] = incoming;
  else list.push(incoming);
  list.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  return list.slice(-cap);
}

export const useCryptoStore = create<CryptoState>()((set) => ({
  connection: "disconnected",
  connectedAt: null,
  lastMessageAt: null,
  ticks: {},
  tickPrices: {},
  candleTails: {},
  snapshots: {},

  setConnection: (connection) =>
    set((state) => ({
      connection,
      connectedAt: connection === "connected" ? new Date().toISOString() : state.connectedAt,
    })),

  noteMessage: () => set({ lastMessageAt: new Date().toISOString() }),

  applyTick: (tick) =>
    set((state) => {
      const previous = state.tickPrices[tick.symbol] ?? [];
      const prices =
        typeof tick.price === "number" && Number.isFinite(tick.price)
          ? [...previous, tick.price].slice(-MAX_PRICE_HISTORY)
          : previous;
      return {
        ticks: { ...state.ticks, [tick.symbol]: tick },
        tickPrices: { ...state.tickPrices, [tick.symbol]: prices },
        lastMessageAt: new Date().toISOString(),
      };
    }),

  applyCandle: (symbol, timeframe, candle) =>
    set((state) => {
      const key = cryptoChannelKey(symbol, timeframe);
      return {
        candleTails: {
          ...state.candleTails,
          [key]: upsertCandleTail(state.candleTails[key], candle, MAX_PRICE_HISTORY),
        },
        lastMessageAt: new Date().toISOString(),
      };
    }),

  applySnapshot: (snapshot, quote, candles) =>
    set((state) => {
      const key = cryptoChannelKey(snapshot.symbol, snapshot.timeframe);
      const tail: LiveCandle[] = candles
        .slice(-MAX_PRICE_HISTORY)
        .map((c) => ({
          timestamp: c.timestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
          volume: c.volume,
          isFinal: true,
          source: snapshot.source,
        }))
        .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
      const candleTails = { ...state.candleTails };
      if (snapshot.timeframe) candleTails[key] = tail;
      return {
        snapshots: { ...state.snapshots, [snapshot.symbol]: snapshot },
        candleTails,
        ticks: quote
          ? {
              ...state.ticks,
              [snapshot.symbol]: {
                symbol: snapshot.symbol,
                price: quote.price,
                high: null,
                low: null,
                volume: quote.volume_24h,
                source: quote.source,
                sourceTimestamp: quote.timestamp,
                receivedAt: new Date().toISOString(),
                dataStatus: quote.status,
                origin: quote.origin,
              },
            }
          : state.ticks,
        lastMessageAt: new Date().toISOString(),
      };
    }),

  reset: () =>
    set({
      connection: "disconnected",
      connectedAt: null,
      lastMessageAt: null,
      ticks: {},
      tickPrices: {},
      candleTails: {},
      snapshots: {},
    }),
}));

/** Convenience selector: the latest tick for one symbol. */
export function selectTick(symbol: string | undefined) {
  return (state: CryptoState) => (symbol ? state.ticks[symbol.toUpperCase()] : undefined);
}

/** Convenience selector: the live candle tail for one channel. */
export function selectCandleTail(symbol: string, timeframe: string) {
  return (state: CryptoState) =>
    state.candleTails[`${symbol.toUpperCase()}:${timeframe}`] ?? [];
}
