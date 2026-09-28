/**
 * Phase 20 — Quick Order / Paper Trading Ticket: types, service and validation.
 *
 * Follows the project's layering rule exactly:
 *
 *   UI (components) -> hooks (React Query) -> THIS FILE -> lib/axios -> API
 *
 * There is no API-key handling anywhere in this file, no broker/exchange
 * endpoint, and no payment surface — because the backend has none. Every call
 * lands on a simulation route that records a hypothetical scenario.
 */
import apiClient from "./axios";

// ---------------------------------------------------------------------------
// Types (mirroring backend/app/paper/*)
// ---------------------------------------------------------------------------

export type PaperInstrumentKind = "STOCK" | "INDEX" | "CRYPTO" | "COMMODITY" | "FOREX" | "FORECAST";
export type PaperQuoteMode = "PRICE" | "PROBABILITY";
export type PaperSide = "BUY" | "SELL" | "YES" | "NO";
export type PaperOrderType = "MARKET" | "LIMIT";
export type PaperAmountMode = "NOTIONAL" | "QUANTITY";
export type PaperOrderStatus = "DRAFT" | "SIMULATED" | "CANCELLED" | "EXPIRED";
export type PaperDataMode = "LIVE" | "DELAYED" | "STALE" | "SIMULATED" | "UNAVAILABLE";
export type PaperDataStatus = "LIVE" | "RECENT" | "CACHED" | "STALE" | "UNAVAILABLE";

export interface PaperInstrument {
  symbol: string;
  kind: PaperInstrumentKind;
  displayName: string;
  quoteMode: PaperQuoteMode;
  currency: string | null;
  providerSymbol: string;
  pricePrecision: number;
  quantityPrecision: number;
  marketId: string | null;
  closeTime: string | null;
  question: string | null;
  category: string | null;
  sourceUrl: string | null;
  externalSource: boolean;
  sides: PaperSide[];
  orderTypes: PaperOrderType[];
  amountModes: PaperAmountMode[];
  isForecast: boolean;
  notes: string[];
  paper: true;
  simulationOnly: true;
}

export interface PaperQuote {
  symbol: string;
  kind: PaperInstrumentKind;
  quoteMode: PaperQuoteMode;
  price: number | null;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  spread: number | null;
  spreadPercent: number | null;
  change: number | null;
  changePercent: number | null;
  previousClose: number | null;
  currency: string | null;
  timestamp: string | null;
  source: string | null;
  status: PaperDataStatus;
  dataMode: PaperDataMode;
  stale: boolean;
  staleReason: string | null;
  ageSeconds: number | null;
  volatilityPercent: number | null;
  volatilityLookback: number | null;
  probabilityYes: number | null;
  probabilityNo: number | null;
  marketStatus: string | null;
  closeTime: string | null;
  question: string | null;
  notes: string[];
}

export interface PaperConfig {
  staleAfterSeconds: number;
  orderTtlSeconds: number;
  minNotional: number;
  maxNotional: number;
  maxQuantity: number;
  amountPrecision: number;
  quantityPrecision: number;
  pricePrecision: number;
  submitTimeoutSeconds: number;
  volatilityLookbackDays: number;
  statuses: PaperOrderStatus[];
}

export interface PaperQuoteSnapshot {
  capturedAt: string;
  observedPrice: number | null;
  observedTimestamp: string | null;
  source: string | null;
  status: string | null;
  dataMode: string | null;
  stale: boolean;
  probabilityYes: number | null;
  probabilityNo: number | null;
  selectedOutcome?: PaperSide | null;
}

export interface PaperOrderPreview {
  banner: string;
  instrument: string;
  displayName: string;
  instrumentKind: PaperInstrumentKind;
  quoteMode: PaperQuoteMode;
  direction: PaperSide;
  directionLabel: string;
  orderType: PaperOrderType;
  orderTypeExplanation: string;
  referencePrice: number | null;
  referenceLabel: string;
  limitPrice: number | null;
  amountMode: PaperAmountMode;
  amount: number | null;
  quantity: number | null;
  estimatedNotional: number | null;
  currency: string | null;
  timestamp: string;
  quoteTimestamp: string | null;
  dataMode: PaperDataMode;
  dataSource: string | null;
  dataStatus: string | null;
  stale: boolean;
  warnings: string[];
  disclaimer: string;
}

export interface PaperOrder {
  id: string;
  userId: string | null;
  clientRequestId: string | null;
  symbol: string;
  instrumentKind: PaperInstrumentKind;
  displayName: string;
  quoteMode: PaperQuoteMode;
  side: PaperSide;
  orderType: PaperOrderType;
  amountMode: PaperAmountMode;
  amount: number;
  quantity: number;
  limitPrice: number | null;
  referencePrice: number | null;
  currency: string | null;
  notional: number | null;
  status: PaperOrderStatus;
  dataMode: PaperDataMode;
  dataSource: string | null;
  openedSnapshot: Partial<PaperQuoteSnapshot>;
  submitSnapshot: Partial<PaperQuoteSnapshot>;
  forecastMarketId: string | null;
  probabilityAtOpen: number | null;
  probabilityCurrent: number | null;
  conditionMet: boolean | null;
  conditionCheckedAt: string | null;
  conditionDetail: Record<string, unknown>;
  exitReference: number | null;
  exitAt: string | null;
  pnl: number | null;
  pnlPercent: number | null;
  notes: string | null;
  openedAt: string | null;
  submittedAt: string | null;
  expiresAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
  paper: true;
  simulationOnly: true;
  statusLabel: string;
}

export interface PaperPnl {
  side: PaperSide;
  entryReference: number;
  exitReference: number;
  priceDifference: number;
  quantity: number;
  hypotheticalPnl: number;
  hypotheticalPnlPercent: number | null;
  unit: "PRICE" | "PERCENTAGE_POINTS";
  paper: true;
  disclaimer: string;
}

export interface PaperSimulationResult {
  orderId: string;
  status: PaperOrderStatus;
  observationsChecked: number;
  evaluatedAt: string;
  conditionMet?: boolean | null;
  fill?: Record<string, unknown>;
  message?: string;
  pnl?: PaperPnl;
  outcome?: string;
  paper: true;
}

export interface PaperHistorySummary {
  total: number;
  draft: number;
  simulated: number;
  cancelled: number;
  expired: number;
  resolved: number;
  wins: number;
  losses: number;
  winRate: number | null;
  hypotheticalTotalPnl: number;
  hypotheticalBestPnl: number | null;
  hypotheticalWorstPnl: number | null;
  paper: true;
  disclaimer: string;
}

export interface PaperHistoryResponse {
  orders: PaperOrder[];
  count: number;
  /** Effective page size the server used. */
  limit?: number;
  /** §53 cursor: createdAt of the last row — pass back as `before` for the next page. Null = no more pages. */
  nextBefore?: string | null;
  hasMore?: boolean;
  summary: PaperHistorySummary;
  paper: true;
  separateFromPortfolio: true;
  disclaimer: string;
  userId?: string;
}

/** §54: a lightweight lifecycle event pushed by the backend (SSE / recent list). */
export interface PaperEvent {
  seq: number;
  at: number;
  type: string;
  orderId?: string;
  userId?: string;
  symbol?: string;
  side?: string;
  status?: string;
  referencePrice?: number | null;
}

export interface PaperAuditEntry {
  id: number;
  requestId: string;
  orderId: string | null;
  userId: string | null;
  event: string;
  instrument: string | null;
  reference: Record<string, unknown>;
  result: Record<string, unknown>;
  at: string | null;
}

export interface ValidationIssue {
  field: string;
  code: string;
  message: string;
}

export interface PreviewResponse {
  ok: boolean;
  preview?: PaperOrderPreview;
  instrument: PaperInstrument | null;
  quote: PaperQuote | null;
  issues: ValidationIssue[];
  banner: string;
  paper: true;
}

export interface InstrumentResponse {
  instrument: PaperInstrument;
  quote: PaperQuote;
  config: PaperConfig;
  paper: true;
}

export interface SubmitResponse {
  order: PaperOrder;
  duplicate: boolean;
  requestId: string;
  message?: string;
  paper: true;
}

export interface EvaluateResponse {
  order: PaperOrder;
  result: PaperSimulationResult;
  paper: true;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const PAPER_BANNER = "PAPER SIMULATION — NOT A REAL ORDER";

export const PAPER_DISCLAIMER =
  "Non-monetary simulation. No order is placed, no broker or exchange is contacted, " +
  "and no funds are involved. Historical results do not guarantee future results.";

/** Quick simulated amount presets (spec §6). Notional values, not payments. */
export const QUICK_AMOUNTS = [1, 5, 10, 100] as const;

export const DEFAULT_PAPER_CONFIG: PaperConfig = {
  staleAfterSeconds: 900,
  orderTtlSeconds: 604800,
  minNotional: 0.01,
  maxNotional: 1_000_000,
  maxQuantity: 1_000_000,
  amountPrecision: 2,
  quantityPrecision: 8,
  pricePrecision: 8,
  submitTimeoutSeconds: 20,
  volatilityLookbackDays: 60,
  statuses: ["DRAFT", "SIMULATED", "CANCELLED", "EXPIRED"],
};

const USER_KEY = "neural-market-paper-user-id";

/**
 * A stable, browser-local simulation owner id.
 *
 * This app has no authentication (documented in the backend), so paper history
 * is scoped to an id kept in this browser rather than to an account. It is not
 * a security boundary — it just keeps one browser's simulations separate from
 * another's. Nothing sensitive is stored.
 */
export function getPaperUserId(): string {
  if (typeof window === "undefined") return "anonymous";
  try {
    const existing = window.localStorage.getItem(USER_KEY);
    if (existing) return existing;
    const generated = `paper-${newRequestId().slice(0, 12)}`;
    window.localStorage.setItem(USER_KEY, generated);
    return generated;
  } catch {
    return "anonymous";
  }
}

/** Unique id for one submission attempt (used for server-side idempotency). */
export function newRequestId(): string {
  const cryptoObj = typeof globalThis !== "undefined" ? (globalThis.crypto as Crypto | undefined) : undefined;
  if (cryptoObj?.randomUUID) return cryptoObj.randomUUID().replace(/-/g, "");
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

function enc(value: string): string {
  return encodeURIComponent(value);
}

export const PaperTradingService = {
  /** Resolve an instrument and read its live quote for the ticket header. */
  async getInstrument(
    symbol: string,
    opts: { kind?: PaperInstrumentKind; currency?: string; displayName?: string } = {},
  ): Promise<InstrumentResponse> {
    const params = new URLSearchParams();
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.currency) params.set("currency", opts.currency);
    if (opts.displayName) params.set("displayName", opts.displayName);
    const qs = params.toString();
    return apiClient
      .get<InstrumentResponse>(`/api/market/instrument/${enc(symbol)}${qs ? `?${qs}` : ""}`)
      .then((r) => r.data);
  },

  /** Live quote only (used for the fast refresh loop while the panel is open). */
  async getQuote(
    symbol: string,
    opts: { kind?: PaperInstrumentKind; withBidAsk?: boolean } = {},
  ): Promise<{ instrument: PaperInstrument; quote: PaperQuote }> {
    const params = new URLSearchParams();
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.withBidAsk === false) params.set("withBidAsk", "false");
    const qs = params.toString();
    return apiClient
      .get(`/api/market/quote/${enc(symbol)}${qs ? `?${qs}` : ""}`)
      .then((r) => r.data);
  },

  async getConfig(): Promise<PaperConfig> {
    return apiClient.get<PaperConfig>("/api/market/config").then((r) => r.data);
  },

  /** Validate + preview. Writes nothing anywhere. */
  async preview(body: Record<string, unknown>): Promise<PreviewResponse> {
    return apiClient.post<PreviewResponse>("/api/paper/preview", body).then((r) => r.data);
  },

  /** Record a simulation. Idempotent on `clientRequestId`. */
  async submit(body: Record<string, unknown>): Promise<SubmitResponse> {
    return apiClient.post<SubmitResponse>("/api/paper/orders", body).then((r) => r.data);
  },

  async listOrders(
    opts: {
      userId?: string;
      symbol?: string;
      status?: PaperOrderStatus;
      side?: string;
      mode?: string;
      dateFrom?: string;
      dateTo?: string;
      /** §53 cursor — the `nextBefore` value from the previous page. */
      before?: string;
      limit?: number;
    } = {},
  ): Promise<PaperHistoryResponse> {
    const params = new URLSearchParams();
    params.set("userId", opts.userId || getPaperUserId());
    if (opts.symbol) params.set("symbol", opts.symbol);
    if (opts.status) params.set("status", opts.status);
    if (opts.side) params.set("side", opts.side);
    if (opts.mode) params.set("mode", opts.mode);
    if (opts.dateFrom) params.set("dateFrom", opts.dateFrom);
    if (opts.dateTo) params.set("dateTo", opts.dateTo);
    if (opts.before) params.set("before", opts.before);
    if (opts.limit) params.set("limit", String(opts.limit));
    return apiClient.get<PaperHistoryResponse>(`/api/paper/orders?${params.toString()}`).then((r) => r.data);
  },

  /** §54: last N lifecycle events for this user (the polling fallback for SSE). */
  async recentEvents(limit = 20): Promise<{ events: PaperEvent[]; count: number }> {
    return apiClient
      .get(`/api/paper/events/recent?limit=${encodeURIComponent(String(limit))}`)
      .then((r) => r.data);
  },

  /** §37: paper-subsystem health (providers, event bus, statuses). */
  async health(): Promise<{
    status: string;
    providers: { name: string; configured: boolean }[];
    eventBus: Record<string, number>;
  }> {
    return apiClient.get("/api/paper/health").then((r) => r.data);
  },

  async getOrder(orderId: string): Promise<{ order: PaperOrder }> {
    return apiClient.get(`/api/paper/orders/${enc(orderId)}`).then((r) => r.data);
  },

  async getAudit(orderId: string): Promise<{ entries: PaperAuditEntry[]; count: number }> {
    return apiClient.get(`/api/paper/orders/${enc(orderId)}/audit`).then((r) => r.data);
  },

  /** Compare a simulation with real subsequent observations. */
  async evaluate(orderId: string): Promise<EvaluateResponse> {
    return apiClient.post<EvaluateResponse>(`/api/paper/orders/${enc(orderId)}/evaluate`, {}).then((r) => r.data);
  },

  async cancel(orderId: string, reason?: string): Promise<{ order: PaperOrder }> {
    return apiClient
      .post(`/api/paper/orders/${enc(orderId)}/cancel`, { reason })
      .then((r) => r.data);
  },

  async getSummary(userId?: string): Promise<{ summary: PaperHistorySummary; byStatus: Record<string, number> }> {
    const params = new URLSearchParams({ userId: userId || getPaperUserId() });
    return apiClient.get(`/api/paper/summary?${params.toString()}`).then((r) => r.data);
  },
};

// ---------------------------------------------------------------------------
// Client-side validation (instant feedback — the server always re-validates)
// ---------------------------------------------------------------------------

export interface PaperInputDraft {
  amount: string;
  amountMode: PaperAmountMode;
  orderType: PaperOrderType;
  limitPrice: string;
}

function decimalPlaces(raw: string): number {
  const trimmed = raw.trim();
  if (!trimmed) return 0;
  const dot = trimmed.indexOf(".");
  return dot === -1 ? 0 : trimmed.length - dot - 1;
}

function parseNumeric(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  // Reject anything JavaScript would silently accept as a prefix ("10abc").
  if (!/^-?\d*(\.\d*)?$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/**
 * Mirror of the server-side rules, for immediate feedback only.
 *
 * The backend re-runs every one of these checks; this exists so the user is
 * told before a round trip, never so the server can trust the client.
 */
export function validatePaperDraft(
  draft: PaperInputDraft,
  opts: {
    config: PaperConfig;
    quantityPrecision: number;
    quoteMode: PaperQuoteMode;
    referencePrice: number | null;
    stale: boolean;
    acknowledgeStale: boolean;
    hasSymbol: boolean;
  },
): ValidationIssue[] {
  const issues: ValidationIssue[] = [];

  if (!opts.hasSymbol) {
    issues.push({ field: "symbol", code: "missing_symbol", message: "No instrument is selected." });
  }

  const raw = draft.amount.trim();
  if (!raw) {
    issues.push({ field: "amount", code: "missing_amount", message: "Enter a simulated amount or quantity." });
  } else {
    const value = parseNumeric(raw);
    if (value === null) {
      issues.push({ field: "amount", code: "invalid_number", message: "Amount must be a number." });
    } else if (value < 0) {
      issues.push({ field: "amount", code: "negative_amount", message: "Amount cannot be negative." });
    } else if (value === 0) {
      issues.push({ field: "amount", code: "zero_amount", message: "Amount must be greater than zero." });
    } else if (draft.amountMode === "NOTIONAL") {
      if (value < opts.config.minNotional) {
        issues.push({ field: "amount", code: "below_minimum", message: `Minimum is ${opts.config.minNotional}.` });
      }
      if (value > opts.config.maxNotional) {
        issues.push({ field: "amount", code: "above_maximum", message: `Maximum is ${opts.config.maxNotional.toLocaleString()}.` });
      }
      if (decimalPlaces(raw) > opts.config.amountPrecision) {
        issues.push({
          field: "amount",
          code: "excessive_precision",
          message: `At most ${opts.config.amountPrecision} decimal places.`,
        });
      }
    } else {
      if (value > opts.config.maxQuantity) {
        issues.push({ field: "amount", code: "above_maximum", message: `Maximum quantity is ${opts.config.maxQuantity.toLocaleString()}.` });
      }
      const allowed = Math.min(opts.config.quantityPrecision, opts.quantityPrecision);
      if (decimalPlaces(raw) > allowed) {
        issues.push({ field: "amount", code: "excessive_precision", message: `At most ${allowed} decimal places.` });
      }
    }
  }

  if (draft.orderType === "LIMIT") {
    const limitRaw = draft.limitPrice.trim();
    if (!limitRaw) {
      issues.push({ field: "limitPrice", code: "missing_price", message: "A LIMIT simulation needs a limit price." });
    } else {
      const limit = parseNumeric(limitRaw);
      if (limit === null) {
        issues.push({ field: "limitPrice", code: "invalid_price", message: "Limit price must be a number." });
      } else if (limit <= 0) {
        issues.push({ field: "limitPrice", code: "invalid_price", message: "Limit price must be greater than zero." });
      } else if (decimalPlaces(limitRaw) > opts.config.pricePrecision) {
        issues.push({
          field: "limitPrice",
          code: "excessive_precision",
          message: `At most ${opts.config.pricePrecision} decimal places.`,
        });
      }
    }
  }

  if (opts.quoteMode === "PRICE" && (opts.referencePrice === null || !Number.isFinite(opts.referencePrice))) {
    issues.push({
      field: "referencePrice",
      code: "missing_reference_price",
      message: "No usable reference price is available, so this cannot be simulated.",
    });
  }

  if (opts.stale && !opts.acknowledgeStale) {
    issues.push({
      field: "quote",
      code: "stale_quote",
      message: "Quote data is stale. Acknowledge the stale reading to continue.",
    });
  }

  return issues;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function isQuoteStale(quote: PaperQuote | null | undefined, config?: PaperConfig): boolean {
  if (!quote) return true;
  if (quote.stale) return true;
  if (quote.dataMode === "UNAVAILABLE" || quote.dataMode === "STALE") return true;
  if (quote.ageSeconds !== null && config && quote.ageSeconds > config.staleAfterSeconds) return true;
  return false;
}

export function formatPaperNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

export function formatPaperPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatPaperTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Relative age label used by the freshness readout. */
export function formatPaperAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export const PAPER_DATA_MODE_LABEL: Record<PaperDataMode, string> = {
  LIVE: "LIVE",
  DELAYED: "DELAYED",
  STALE: "STALE DATA",
  SIMULATED: "SIMULATED",
  UNAVAILABLE: "UNAVAILABLE",
};

export const PAPER_STATUS_LABEL: Record<PaperOrderStatus, string> = {
  DRAFT: "DRAFT",
  SIMULATED: "SIMULATED",
  CANCELLED: "CANCELLED",
  EXPIRED: "EXPIRED",
};

export const PAPER_STATUS_DESCRIPTION: Record<PaperOrderStatus, string> = {
  DRAFT: "Prepared but not simulated yet.",
  SIMULATED: "Recorded as a paper scenario — no order was placed.",
  CANCELLED: "You stopped this simulation.",
  EXPIRED: "The simulation reached its time limit without its condition being met.",
};

export function directionLabel(side: PaperSide, quoteMode: PaperQuoteMode): string {
  return quoteMode === "PROBABILITY" ? `PAPER ${side} · informational` : `PAPER ${side}`;
}

/** Human label for the "reference value" column, which differs per instrument. */
export function referenceColumnLabel(quoteMode: PaperQuoteMode): string {
  return quoteMode === "PROBABILITY" ? "Probability (%)" : "Reference price";
}

/** Event outcomes are never described with buy/sell vocabulary. */
export function sideOptionsFor(quoteMode: PaperQuoteMode): { value: PaperSide; label: string; hint: string }[] {
  if (quoteMode === "PROBABILITY") {
    return [
      { value: "YES", label: "YES", hint: "Selecting YES is an informational forecast choice, not a wager." },
      { value: "NO", label: "NO", hint: "Selecting NO is an informational forecast choice, not a wager." },
    ];
  }
  return [
    { value: "BUY", label: "BUY", hint: "Paper long: the simulation profits if the reference rises." },
    { value: "SELL", label: "SELL", hint: "Paper short: the simulation profits if the reference falls." },
  ];
}
