/**
 * Phase 9 — Persistence abstraction (spec E/Q).
 *
 * The UI never touches localStorage or axios directly for watchlist/portfolio
 * data; it talks to a `WatchlistStorage` / `PortfolioStorage` interface.
 *
 * Two implementations ship today:
 *   - BackendStorage   — server DB through the FastAPI API (the default; data
 *                        survives reloads and is what the whole app already uses)
 *   - LocalStorageStore— offline fallback that keeps working when the backend
 *                        is unreachable, so the UI degrades instead of dying.
 *
 * Both satisfy the same contract, so later authenticated server
 * synchronization is an adapter swap, not a UI rewrite. Services
 * (`WatchlistService`, `PortfolioService`, `TransactionService`) pick the
 * adapter and expose the spec-D engine operations: add, remove, exists,
 * list, reorder, search.
 */

import apiClient from "./axios";
import type { Transaction, TransactionInput } from "./finance";

// ---------------------------------------------------------------------------
// Watchlist (spec C/D)
// ---------------------------------------------------------------------------

export interface WatchlistItem {
  id: string | number;
  userId: string | null;
  symbol: string;
  addedAt: string;
  notes: string | null;
  sortOrder: number;
  /** Live quote fields (BackendStorage fills them; local-only store can't). */
  price?: number | null;
  changePercent?: number | null;
  status?: string;
}

export interface WatchlistStorage {
  /** List in display order, priced when the adapter can price. */
  list(): Promise<WatchlistItem[]>;
  exists(symbol: string): Promise<boolean>;
  add(symbol: string, notes?: string): Promise<WatchlistItem>;
  remove(symbol: string): Promise<boolean>;
  setNotes(symbol: string, notes: string | null): Promise<WatchlistItem | null>;
  /** Persist a manual order — the full ordered list of ids. */
  reorder(orderedIds: Array<string | number>): Promise<WatchlistItem[]>;
}

/** Map the backend's snake_case WatchlistItem onto the spec-C camelCase shape. */
function fromBackend(row: {
  id: number;
  ticker: string;
  note: string | null;
  added_at: string;
  sort_order: number;
  price?: number | null;
  change_percent?: number | null;
  status?: string;
}): WatchlistItem {
  return {
    id: row.id,
    userId: null, // auth-ready: the backend is single-tenant until auth lands
    symbol: row.ticker,
    addedAt: row.added_at,
    notes: row.note,
    sortOrder: row.sort_order,
    price: row.price ?? null,
    changePercent: row.change_percent ?? null,
    status: row.status,
  };
}

/** Server persistence through the existing FastAPI API (default adapter). */
export class BackendWatchlistStorage implements WatchlistStorage {
  async list(): Promise<WatchlistItem[]> {
    // /watchlist/quotes prices every saved ticker fresh at read time and
    // resolves PSX symbols server-side — one call for the whole panel.
    const res = await apiClient.get("/api/watchlist/quotes");
    const items = (res.data?.items ?? []) as Array<Record<string, unknown>>;
    return items.map((i) =>
      fromBackend(i as Parameters<typeof fromBackend>[0])
    );
  }

  async exists(symbol: string): Promise<boolean> {
    try {
      const res = await apiClient.get(
        `/api/watchlist/exists/${encodeURIComponent(symbol.toUpperCase())}`
      );
      return Boolean(res.data?.exists);
    } catch {
      // fall back to listing if the exists route is unavailable
      const items = await this.list();
      return items.some((i) => i.symbol === symbol.toUpperCase());
    }
  }

  async add(symbol: string, notes?: string): Promise<WatchlistItem> {
    const res = await apiClient.post("/api/watchlist", {
      ticker: symbol.toUpperCase(),
      note: notes || null,
    });
    return fromBackend(res.data);
  }

  async remove(symbol: string): Promise<boolean> {
    const res = await apiClient.delete(
      `/api/watchlist/${encodeURIComponent(symbol.toUpperCase())}`
    );
    return Boolean(res.data?.removed);
  }

  async setNotes(symbol: string, notes: string | null): Promise<WatchlistItem | null> {
    const res = await apiClient.patch(
      `/api/watchlist/${encodeURIComponent(symbol.toUpperCase())}`,
      { note: notes }
    );
    return fromBackend(res.data);
  }

  async reorder(orderedIds: Array<string | number>): Promise<WatchlistItem[]> {
    const res = await apiClient.post("/api/watchlist/reorder", { ids: orderedIds });
    return ((res.data?.items ?? []) as Array<Record<string, unknown>>).map(
      (i) => fromBackend(i as Parameters<typeof fromBackend>[0])
    );
  }
}

const LS_WATCHLIST_KEY = "neural_market.watchlist.v1";

interface LsWatchRow {
  id: string;
  symbol: string;
  addedAt: string;
  notes: string | null;
  sortOrder: number;
}

function lsRead(): LsWatchRow[] {
  try {
    const raw = localStorage.getItem(LS_WATCHLIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as LsWatchRow[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function lsWrite(rows: LsWatchRow[]): void {
  localStorage.setItem(LS_WATCHLIST_KEY, JSON.stringify(rows));
}

/** Offline fallback — same contract, browser persistence, no pricing. */
export class LocalWatchlistStorage implements WatchlistStorage {
  async list(): Promise<WatchlistItem[]> {
    return lsRead()
      .sort((a, b) => a.sortOrder - b.sortOrder || a.addedAt.localeCompare(b.addedAt))
      .map((r) => ({
        id: r.id,
        userId: null,
        symbol: r.symbol,
        addedAt: r.addedAt,
        notes: r.notes,
        sortOrder: r.sortOrder,
        price: null,
        changePercent: null,
        status: "UNAVAILABLE" as const,
      }));
  }

  async exists(symbol: string): Promise<boolean> {
    return lsRead().some((r) => r.symbol === symbol.toUpperCase());
  }

  async add(symbol: string, notes?: string): Promise<WatchlistItem> {
    const sym = symbol.toUpperCase();
    const rows = lsRead();
    if (rows.some((r) => r.symbol === sym)) {
      throw new Error(`${sym} is already on the watchlist.`);
    }
    const row: LsWatchRow = {
      id: `w_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      symbol: sym,
      addedAt: new Date().toISOString(),
      notes: notes || null,
      sortOrder: 0,
    };
    lsWrite([...rows, row]);
    return { ...row, userId: null, price: null, changePercent: null, status: "UNAVAILABLE" };
  }

  async remove(symbol: string): Promise<boolean> {
    const sym = symbol.toUpperCase();
    const rows = lsRead();
    const next = rows.filter((r) => r.symbol !== sym);
    lsWrite(next);
    return next.length !== rows.length;
  }

  async setNotes(symbol: string, notes: string | null): Promise<WatchlistItem | null> {
    const sym = symbol.toUpperCase();
    const rows = lsRead();
    const row = rows.find((r) => r.symbol === sym);
    if (!row) return null;
    row.notes = notes;
    lsWrite(rows);
    return { ...row, userId: null, price: null, changePercent: null, status: "UNAVAILABLE" };
  }

  async reorder(orderedIds: Array<string | number>): Promise<WatchlistItem[]> {
    const rows = lsRead();
    const pos = new Map(orderedIds.map((id, i) => [String(id), i + 1]));
    for (const r of rows) {
      const p = pos.get(String(r.id));
      if (p !== undefined) r.sortOrder = p;
    }
    lsWrite(rows);
    return this.list();
  }
}

// ---------------------------------------------------------------------------
// Transactions (spec F) + Portfolio storage (spec Q)
// ---------------------------------------------------------------------------

export interface StoredTransaction extends Transaction {}

export interface TransactionStorage {
  list(filter?: TransactionFilter): Promise<StoredTransaction[]>;
  create(input: TransactionInput & { symbol: string; side: "BUY" | "SELL" }): Promise<StoredTransaction>;
  remove(id: string): Promise<boolean>;
}

export interface TransactionFilter {
  symbol?: string;
  side?: "BUY" | "SELL";
  dateFrom?: string; // ISO date (YYYY-MM-DD)
  dateTo?: string;
}

/** Maps the backend Transaction row onto the spec-F camelCase shape. */
function txFromBackend(row: {
  id: number;
  user_id: string | null;
  symbol: string;
  transaction_type: "BUY" | "SELL";
  quantity: number;
  price: number;
  fees: number;
  transaction_date: string;
  notes: string | null;
  broker: string | null;
}): StoredTransaction {
  return {
    id: String(row.id),
    userId: row.user_id,
    symbol: row.symbol,
    side: row.transaction_type,
    quantity: row.quantity,
    price: row.price,
    date: row.transaction_date,
    fees: row.fees,
    notes: row.notes ?? undefined,
    broker: row.broker ?? undefined,
  };
}

export class BackendTransactionStorage implements TransactionStorage {
  async list(filter?: TransactionFilter): Promise<StoredTransaction[]> {
    const params = new URLSearchParams();
    if (filter?.symbol) params.set("symbol", filter.symbol.toUpperCase());
    if (filter?.side) params.set("transaction_type", filter.side);
    if (filter?.dateFrom) params.set("date_from", filter.dateFrom);
    if (filter?.dateTo) params.set("date_to", filter.dateTo);
    params.set("limit", "2000");
    const res = await apiClient.get(`/api/portfolio/transactions?${params.toString()}`);
    return ((res.data?.transactions ?? []) as Array<Record<string, unknown>>).map(
      (t) => txFromBackend(t as Parameters<typeof txFromBackend>[0])
    );
  }

  async create(input: TransactionInput & { symbol: string; side: "BUY" | "SELL" }): Promise<StoredTransaction> {
    const res = await apiClient.post("/api/portfolio/transactions", {
      symbol: input.symbol.toUpperCase(),
      transaction_type: input.side,
      quantity: Number(input.quantity),
      price: Number(input.price),
      fees: input.fees.trim() === "" ? 0 : Number(input.fees),
      transaction_date: input.date.length === 10 ? `${input.date}T00:00:00` : input.date,
      notes: undefined,
    });
    return txFromBackend(res.data);
  }

  async remove(id: string): Promise<boolean> {
    const res = await apiClient.delete(`/api/portfolio/transactions/${encodeURIComponent(id)}`);
    return Boolean(res.data?.deleted);
  }
}

const LS_TX_KEY = "neural_market.transactions.v1";

function lsTxRead(): StoredTransaction[] {
  try {
    const raw = localStorage.getItem(LS_TX_KEY);
    const parsed = raw ? (JSON.parse(raw) as StoredTransaction[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function lsTxWrite(rows: StoredTransaction[]): void {
  localStorage.setItem(LS_TX_KEY, JSON.stringify(rows));
}

export class LocalTransactionStorage implements TransactionStorage {
  async list(filter?: TransactionFilter): Promise<StoredTransaction[]> {
    let rows = lsTxRead();
    if (filter?.symbol) rows = rows.filter((r) => r.symbol === filter.symbol!.toUpperCase());
    if (filter?.side) rows = rows.filter((r) => r.side === filter.side);
    if (filter?.dateFrom) rows = rows.filter((r) => r.date >= filter.dateFrom!);
    if (filter?.dateTo) rows = rows.filter((r) => r.date <= `${filter.dateTo!}T23:59:59`);
    return rows.sort((a, b) => b.date.localeCompare(a.date));
  }

  async create(input: TransactionInput & { symbol: string; side: "BUY" | "SELL" }): Promise<StoredTransaction> {
    const rows = lsTxRead();
    const tx: StoredTransaction = {
      id: `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      userId: null,
      symbol: input.symbol.toUpperCase(),
      side: input.side,
      quantity: Number(input.quantity),
      price: Number(input.price),
      date: input.date.length === 10 ? `${input.date}T00:00:00` : input.date,
      fees: input.fees.trim() === "" ? 0 : Number(input.fees),
    };
    lsTxWrite([...rows, tx]);
    return tx;
  }

  async remove(id: string): Promise<boolean> {
    const rows = lsTxRead();
    const next = rows.filter((r) => r.id !== id);
    lsTxWrite(next);
    return next.length !== rows.length;
  }
}

// ---------------------------------------------------------------------------
// Services (spec Q) — the seam the UI talks to
// ---------------------------------------------------------------------------

export class WatchlistService {
  constructor(private storage: WatchlistStorage) {}

  list() {
    return this.storage.list();
  }
  exists(symbol: string) {
    return this.storage.exists(symbol);
  }
  add(symbol: string, notes?: string) {
    return this.storage.add(symbol, notes);
  }
  remove(symbol: string) {
    return this.storage.remove(symbol);
  }
  setNotes(symbol: string, notes: string | null) {
    return this.storage.setNotes(symbol, notes);
  }
  reorder(orderedIds: Array<string | number>) {
    return this.storage.reorder(orderedIds);
  }
  /** Spec D: client-side search over the listed items. */
  static search(items: WatchlistItem[], query: string): WatchlistItem[] {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) => i.symbol.toLowerCase().includes(q) || (i.notes ?? "").toLowerCase().includes(q)
    );
  }
}

export class TransactionService {
  constructor(private storage: TransactionStorage) {}

  list(filter?: TransactionFilter) {
    return this.storage.list(filter);
  }
  create(input: TransactionInput & { symbol: string; side: "BUY" | "SELL" }) {
    return this.storage.create(input);
  }
  remove(id: string) {
    return this.storage.remove(id);
  }
}

/**
 * Chooses adapters: backend when reachable, local fallback otherwise, with a
 * health flag the UI can show honestly ("offline — saved in this browser").
 */
export class PortfolioService {
  watchlist: WatchlistService;
  transactions: TransactionService;
  private backendWatchlist = new BackendWatchlistStorage();
  private localWatchlist = new LocalWatchlistStorage();
  private backendTx = new BackendTransactionStorage();
  private localTx = new LocalTransactionStorage();
  private _usingLocal = false;

  constructor() {
    this.watchlist = new WatchlistService(this.backendWatchlist);
    this.transactions = new TransactionService(this.backendTx);
  }

  get usingLocalFallback(): boolean {
    return this._usingLocal;
  }

  /** Switch to the offline adapters after a backend failure. */
  useLocalFallback(): void {
    if (!this._usingLocal) {
      this._usingLocal = true;
      this.watchlist = new WatchlistService(this.localWatchlist);
      this.transactions = new TransactionService(this.localTx);
    }
  }
}

/** App-wide singletons (one instance → one fallback state). */
export const portfolioService = new PortfolioService();
export const watchlistService = portfolioService.watchlist;
export const transactionService = portfolioService.transactions;
