/**
 * Phase 20 — `usePaperOrderStore`.
 *
 * UI state only. Per the project's architecture rule, no server/API code lives
 * in a Zustand store: the panel calls the React Query hooks in
 * `hooks/usePaperTrading.ts`, and this store just remembers what the user was
 * looking at, what they typed, and what the last attempt did.
 *
 * The store is intentionally page-agnostic: any page can publish its context
 * (`setContext`) and the ticket reflects it, which is what makes the ticket
 * context-aware without every page owning its own copy.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  type PaperAmountMode,
  type PaperInstrumentKind,
  type PaperOrder,
  type PaperOrderPreview,
  type PaperOrderType,
  type PaperQuote,
  type PaperQuoteMode,
  type PaperQuoteSnapshot,
  type PaperSide,
  type PaperSimulationResult,
  type ValidationIssue,
  newRequestId,
} from "../lib/paperTrading";

export interface PaperContext {
  /** Provider-facing symbol, e.g. `OGDC`, `BTC-USD`, `EURUSD=X`, `FORECAST:abc`. */
  symbol: string;
  kind: PaperInstrumentKind;
  displayName?: string;
  currency?: string | null;
  quoteMode?: PaperQuoteMode;
  /** Route the ticket was opened from — recorded for the audit context. */
  page: string;
  /** Phase 14 linkage. */
  marketId?: string | null;
  question?: string | null;
  closeTime?: string | null;
  category?: string | null;
  /** Snapshot values the page already had, used before the first fresh quote. */
  observedPrice?: number | null;
  observedTimestamp?: string | null;
  source?: string | null;
  dataMode?: string | null;
  status?: string | null;
  probabilityYes?: number | null;
  probabilityNo?: number | null;
}

export type PaperSubmitState = "IDLE" | "SUBMITTING" | "DONE" | "ERROR";

interface PaperOrderState {
  // --- panel ---------------------------------------------------------------
  isOpen: boolean;
  /** True while the user collapsed the ticket on tablet-sized layouts. */
  isCollapsed: boolean;
  context: PaperContext | null;
  openPanel: (context?: Partial<PaperContext>) => void;
  closePanel: () => void;
  togglePanel: () => void;
  setCollapsed: (collapsed: boolean) => void;
  setContext: (context: PaperContext) => void;
  patchContext: (context: Partial<PaperContext>) => void;
  clearContext: () => void;

  // --- form ----------------------------------------------------------------
  side: PaperSide;
  orderType: PaperOrderType;
  amountMode: PaperAmountMode;
  amount: string;
  limitPrice: string;
  acknowledgeStale: boolean;
  setSide: (side: PaperSide) => void;
  setOrderType: (orderType: PaperOrderType) => void;
  setAmountMode: (mode: PaperAmountMode) => void;
  setAmount: (amount: string) => void;
  addToAmount: (delta: number) => void;
  setLimitPrice: (price: string) => void;
  useQuoteAsLimit: () => void;
  setAcknowledgeStale: (value: boolean) => void;
  resetForm: () => void;

  // --- snapshots (spec §9/§15) ---------------------------------------------
  quoteSnapshot: PaperQuoteSnapshot | null;
  captureSnapshot: (quote: PaperQuote, side?: PaperSide) => void;
  clearSnapshot: () => void;

  /**
   * A live reading pushed in by a page that ALREADY owns a market-data
   * connection (e.g. the stock page's WebSocket). The ticket prefers this over
   * its own polled value so it never opens a second socket (spec §16).
   */
  liveQuote: { symbol: string; price: number | null; source?: string | null; status?: string | null; timestamp?: string | null } | null;
  setLiveQuote: (
    live: { symbol: string; price: number | null; source?: string | null; status?: string | null; timestamp?: string | null } | null,
  ) => void;

  // --- submission lifecycle ------------------------------------------------
  clientRequestId: string;
  submitState: PaperSubmitState;
  submitError: string | null;
  issues: ValidationIssue[];
  preview: PaperOrderPreview | null;
  lastOrder: PaperOrder | null;
  lastResult: PaperSimulationResult | null;
  beginSubmit: () => string;
  setPreview: (preview: PaperOrderPreview | null) => void;
  setIssues: (issues: ValidationIssue[]) => void;
  finishSubmit: (order: PaperOrder, duplicate: boolean) => void;
  failSubmit: (message: string, issues?: ValidationIssue[]) => void;
  setLastResult: (order: PaperOrder, result: PaperSimulationResult) => void;
  startNewRequest: () => void;
}

const DEFAULT_CONTEXT: PaperContext = {
  symbol: "",
  kind: "STOCK",
  page: "/",
};

export const usePaperOrderStore = create<PaperOrderState>()(
  persist(
    (set, get) => ({
      // --- panel -----------------------------------------------------------
      isOpen: false,
      isCollapsed: false,
      context: null,
      openPanel: (context) =>
        set((state) => {
          const nextContext = context
            ? { ...DEFAULT_CONTEXT, ...(state.context ?? {}), ...context }
            : state.context;
          const symbolChanged = nextContext?.symbol !== state.context?.symbol;
          return {
            isOpen: true,
            context: nextContext,
            submitState: state.submitState === "ERROR" ? "IDLE" : state.submitState,
            submitError: state.submitState === "ERROR" ? null : state.submitError,
            // Opening for a *different* instrument must not carry the previous
            // instrument's snapshot/result over — that would compare two
            // unrelated things.
            quoteSnapshot: symbolChanged ? null : state.quoteSnapshot,
            preview: symbolChanged ? null : state.preview,
            issues: symbolChanged ? [] : state.issues,
            lastResult: symbolChanged ? null : state.lastResult,
            clientRequestId: symbolChanged ? newRequestId() : state.clientRequestId,
            // The side vocabulary depends on the instrument: a forecast event
            // takes YES/NO, everything else BUY/SELL. Switching instruments
            // must never leave an invalid side selected.
            side: context?.quoteMode || symbolChanged ? normaliseSide(state.side, context?.quoteMode) : state.side,
          };
        }),
      closePanel: () => set({ isOpen: false, isCollapsed: false }),
      togglePanel: () => set((state) => ({ isOpen: !state.isOpen, isCollapsed: false })),
      setCollapsed: (isCollapsed) => set({ isCollapsed }),
      setContext: (context) =>
        set((state) => {
          const changedSymbol = state.context?.symbol !== context.symbol;
          return {
            context,
            // A different instrument means the old snapshot/form no longer
            // describes what is on screen.
            quoteSnapshot: changedSymbol ? null : state.quoteSnapshot,
            preview: changedSymbol ? null : state.preview,
            lastResult: changedSymbol ? null : state.lastResult,
            issues: changedSymbol ? [] : state.issues,
            submitError: changedSymbol ? null : state.submitError,
            submitState: changedSymbol ? "IDLE" : state.submitState,
            clientRequestId: changedSymbol ? newRequestId() : state.clientRequestId,
            side: normaliseSide(state.side, context.quoteMode),
            limitPrice: changedSymbol ? "" : state.limitPrice,
          };
        }),
      patchContext: (context) =>
        set((state) => (state.context ? { context: { ...state.context, ...context } } : {})),
      clearContext: () => set({ context: null }),

      // --- form ------------------------------------------------------------
      side: "BUY",
      orderType: "MARKET",
      amountMode: "NOTIONAL",
      amount: "10",
      limitPrice: "",
      acknowledgeStale: false,
      setSide: (side) => set({ side }),
      setOrderType: (orderType) => set({ orderType }),
      setAmountMode: (amountMode) => set({ amountMode }),
      setAmount: (amount) => set({ amount }),
      addToAmount: (delta) => {
        const current = Number.parseFloat(get().amount);
        const base = Number.isFinite(current) ? current : 0;
        const next = Math.max(0, Math.round((base + delta) * 100) / 100);
        set({ amount: String(next) });
      },
      setLimitPrice: (limitPrice) => set({ limitPrice }),
      useQuoteAsLimit: () => {
        const reference = get().quoteSnapshot?.observedPrice;
        if (reference !== null && reference !== undefined && Number.isFinite(reference)) {
          set({ limitPrice: String(reference) });
        }
      },
      setAcknowledgeStale: (acknowledgeStale) => set({ acknowledgeStale }),
      resetForm: () =>
        set({
          side: "BUY",
          orderType: "MARKET",
          amountMode: "NOTIONAL",
          amount: "10",
          limitPrice: "",
          acknowledgeStale: false,
          issues: [],
          preview: null,
          submitError: null,
          submitState: "IDLE",
          clientRequestId: newRequestId(),
        }),

      // --- snapshots --------------------------------------------------------
      quoteSnapshot: null,
      captureSnapshot: (quote, side) => {
        const snapshot: PaperQuoteSnapshot = {
          capturedAt: new Date().toISOString(),
          observedPrice:
            quote.quoteMode === "PROBABILITY"
              ? side === "NO"
                ? quote.probabilityNo
                : quote.probabilityYes
              : quote.price,
          observedTimestamp: quote.timestamp,
          source: quote.source,
          status: quote.status,
          dataMode: quote.dataMode,
          stale: quote.stale,
          probabilityYes: quote.probabilityYes,
          probabilityNo: quote.probabilityNo,
          selectedOutcome: quote.quoteMode === "PROBABILITY" ? (side ?? null) : null,
        };
        set({ quoteSnapshot: snapshot });
      },
      clearSnapshot: () => set({ quoteSnapshot: null }),
      liveQuote: null,
      setLiveQuote: (live) => {
        const current = get().liveQuote;
        // Only write when something actually changed — this is fed by a
        // streaming source, so an unconditional set would re-render constantly.
        if (
          current?.symbol === live?.symbol &&
          current?.price === live?.price &&
          current?.status === live?.status &&
          current?.timestamp === live?.timestamp
        ) {
          return;
        }
        set({ liveQuote: live });
      },

      // --- submission -------------------------------------------------------
      clientRequestId: newRequestId(),
      submitState: "IDLE",
      submitError: null,
      issues: [],
      preview: null,
      lastOrder: null,
      lastResult: null,
      beginSubmit: () => {
        const id = get().clientRequestId || newRequestId();
        set({ submitState: "SUBMITTING", submitError: null, clientRequestId: id });
        return id;
      },
      setPreview: (preview) => set({ preview }),
      setIssues: (issues) => set({ issues }),
      finishSubmit: (order, duplicate) =>
        set({
          submitState: "DONE",
          submitError: duplicate
            ? "This request was already recorded — showing the existing simulation instead of creating a duplicate."
            : null,
          lastOrder: order,
          issues: [],
        }),
      failSubmit: (message, issues = []) =>
        set({ submitState: "ERROR", submitError: message, issues }),
      setLastResult: (lastOrder, lastResult) => set({ lastOrder, lastResult }),
      startNewRequest: () => set({ clientRequestId: newRequestId(), submitState: "IDLE", submitError: null }),
    }),
    {
      name: "neural-market-paper-ticket",
      // Only the user's *preferences* survive a reload. The context, open state,
      // snapshot and results are page-driven and are deliberately not persisted
      // — a stale snapshot restored from storage would be exactly the kind of
      // dishonesty this phase forbids.
      partialize: (state) => ({
        side: state.side,
        orderType: state.orderType,
        amountMode: state.amountMode,
        amount: state.amount,
      }),
    },
  ),
);

/** Keep the side valid when the ticket switches between price and event modes. */
function normaliseSide(side: PaperSide, quoteMode?: PaperQuoteMode): PaperSide {
  const isForecast = quoteMode === "PROBABILITY";
  if (isForecast) return side === "NO" ? "NO" : "YES";
  return side === "SELL" ? "SELL" : "BUY";
}
