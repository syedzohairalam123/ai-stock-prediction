/**
 * Phase 20 — React Query hooks for the Quick Order / Paper Trading ticket.
 *
 * The only place the ticket talks to the API. Components never call `fetch`.
 *
 * Live-data note (spec §16): the ticket does **not** open its own WebSocket. It
 * polls the same `MarketDataManager` every other page reads (one shared server
 * cache, one fallback chain), and it also accepts a live reading pushed in by a
 * page that already holds an open market-data connection — see
 * `usePaperLiveQuotePublisher`.
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  PaperTradingService,
  getPaperUserId,
  type PaperInstrumentKind,
  type PaperOrder,
  type PaperOrderStatus,
  type PaperQuote,
} from "../lib/paperTrading";
import { usePaperOrderStore } from "../store/usePaperOrderStore";

export const paperKeys = {
  config: ["paper", "config"] as const,
  instrument: (symbol: string, kind?: string) => ["paper", "instrument", symbol, kind ?? ""] as const,
  orders: (userId: string, symbol?: string, status?: string) =>
    ["paper", "orders", userId, symbol ?? "", status ?? ""] as const,
  order: (orderId: string) => ["paper", "order", orderId] as const,
};

/** Published simulation limits (so the UI and the server never disagree). */
export function usePaperConfig() {
  return useQuery({
    queryKey: paperKeys.config,
    queryFn: () => PaperTradingService.getConfig(),
    staleTime: 30 * 60 * 1000,
    retry: 1,
  });
}

/** How often to re-read a quote, based on how fresh the last one actually was. */
function quoteIntervalMs(quote: PaperQuote | undefined): number {
  if (!quote) return 15_000;
  if (quote.dataMode === "LIVE") return 15_000;
  if (quote.dataMode === "UNAVAILABLE") return 60_000;
  return 45_000;
}

/**
 * Instrument metadata + live quote for the ticket.
 *
 * Only runs while the panel is open for a symbol, so a closed ticket costs
 * nothing and never polls a provider.
 */
export function usePaperInstrument(
  symbol: string | null | undefined,
  kind?: PaperInstrumentKind,
  enabled = true,
) {
  return useQuery({
    queryKey: paperKeys.instrument(symbol ?? "", kind),
    queryFn: () => PaperTradingService.getInstrument(symbol as string, { kind }),
    enabled: Boolean(symbol) && enabled,
    refetchInterval: (query) => quoteIntervalMs(query.state.data?.quote as PaperQuote | undefined),
    retry: 1,
    staleTime: 5_000,
  });
}

/**
 * Publish an already-open live quote into the ticket's store.
 *
 * Pages that own a market-data connection (the stock dashboard's WebSocket) call
 * this so the ticket shows the same live reading without opening a second
 * connection of its own.
 */
export function usePaperLiveQuotePublisher(
  symbol: string | null | undefined,
  live: { price?: number | null; source?: string | null; status?: string | null; timestamp?: string | null } | null,
) {
  const isOpen = usePaperOrderStore((s) => s.isOpen);
  const contextSymbol = usePaperOrderStore((s) => s.context?.symbol);
  const setLiveQuote = usePaperOrderStore((s) => s.setLiveQuote);

  const price = live?.price ?? null;
  const source = live?.source ?? null;
  const status = live?.status ?? null;
  const timestamp = live?.timestamp ?? null;

  useEffect(() => {
    if (!isOpen || !symbol || contextSymbol !== symbol) return;
    if (price === null || !Number.isFinite(price)) return;
    setLiveQuote({ symbol, price, source, status, timestamp });
  }, [isOpen, symbol, contextSymbol, price, source, status, timestamp, setLiveQuote]);
}

/** Recent simulations for this browser's user id (spec §18). */
export function usePaperOrders(
  opts: { symbol?: string; status?: PaperOrderStatus; limit?: number; enabled?: boolean } = {},
) {
  const userId = getPaperUserId();
  return useQuery({
    queryKey: paperKeys.orders(userId, opts.symbol, opts.status),
    queryFn: () => PaperTradingService.listOrders({ userId, symbol: opts.symbol, status: opts.status, limit: opts.limit }),
    enabled: opts.enabled ?? true,
    refetchInterval: 30_000,
    retry: 1,
    staleTime: 10_000,
  });
}

/** Validate + preview without writing anything. */
export function usePaperPreview() {
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => PaperTradingService.preview(body),
  });
}

/**
 * Record a simulation.
 *
 * `clientRequestId` is generated once per attempt by the store and reused when
 * the user retries the same request, so a double-click or a network retry
 * cannot create two rows (spec §25).
 */
export function useSubmitPaperOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => PaperTradingService.submit(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["paper", "orders"] });
      queryClient.invalidateQueries({ queryKey: ["paper", "summary"] });
    },
  });
}

/** Re-check a simulation against real subsequent observations (spec §12/§13). */
export function useEvaluatePaperOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => PaperTradingService.evaluate(orderId),
    onSuccess: (data) => {
      queryClient.setQueryData(paperKeys.order(data.order.id), { order: data.order });
      queryClient.invalidateQueries({ queryKey: ["paper", "orders"] });
    },
  });
}

export function useCancelPaperOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, reason }: { orderId: string; reason?: string }) =>
      PaperTradingService.cancel(orderId, reason),
    onSuccess: (data) => {
      queryClient.setQueryData(paperKeys.order(data.order.id), { order: data.order });
      queryClient.invalidateQueries({ queryKey: ["paper", "orders"] });
    },
  });
}

/**
 * Map a React Query / axios error into a message plus structured issues.
 * The panel always resolves its SUBMITTING state from this — it can never be
 * left spinning (spec §27).
 */
export function interpretPaperError(error: unknown): { message: string; issues: { field: string; code: string; message: string }[] } {
  const fallback = "The simulation could not be submitted. Nothing was sent anywhere.";
  if (!error) return { message: fallback, issues: [] };
  const anyError = error as { message?: string; issues?: unknown };
  const message = typeof anyError.message === "string" && anyError.message ? anyError.message : fallback;
  const issues = Array.isArray(anyError.issues) ? (anyError.issues as { field: string; code: string; message: string }[]) : [];
  return { message, issues };
}

/** Convenience: the order currently selected in the history panel. */
export function useSelectedPaperOrder(order: PaperOrder | null) {
  return usePaperOrderStore((s) => s.lastOrder ?? order);
}
