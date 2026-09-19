/**
 * Phase 11 — unified chart data source (spec §6, §7, §29).
 *
 * One loader feeds every chart panel, whichever kind of entity it plots:
 *
 *   STOCK  -> the existing FastAPI history service (`MarketService.getHistory`)
 *   INDEX  -> the existing deterministic PSX index series (`psxMarket`)
 *
 * Both are pushed through the same OHLCV normalizer, so a chart never has to
 * care where its candles came from. Nothing is fabricated: if a provider has no
 * bars for a window, the panel shows an honest empty state, and if the API falls
 * back to generated data the dataset carries the provider's own status label.
 *
 * This module is a *thin adapter*, not a second data layer: it reuses the
 * Phase-5 services, the Phase-2 index service and the Phase-5 timeframe system.
 */
import { MarketService, type DataStatus } from "../services";
import { INDICES, STOCKS, getHistoryAsync } from "../psxMarket";
import { rangeWindow, type StockRange } from "../timeframes";
import { normalizeOHLCV, historyRowsToRaw, psxPointsToRaw } from "./ohlcv";
import type { Candle, EntityType, NormalizedDataset } from "./types";
import { datasetFitKey } from "./defaults";

export type ChartDataSource = "stock-history" | "psx-index";

export interface ChartDataset {
  symbol: string;
  entityType: EntityType;
  timeframe: StockRange;
  /** True only when the bars really are intraday (drives VWAP availability). */
  intraday: boolean;
  source: ChartDataSource;
  /** Display name of the instrument. */
  name: string;
  /** Provider-reported freshness, when the provider reports anything. */
  status: DataStatus | null;
  providerSource: string | null;
  /** Identity of this exact dataset — gates the persisted viewport. */
  fitKey: string;
  points: Candle[];
  stats: NormalizedDataset["stats"];
}

export type ChartDataErrorCode = "INVALID_SYMBOL" | "NO_DATA" | "FETCH_FAILED";

/** Typed failure so the UI can render a specific, actionable message. */
export class ChartDataError extends Error {
  code: ChartDataErrorCode;
  constructor(code: ChartDataErrorCode, message: string) {
    super(message);
    this.name = "ChartDataError";
    this.code = code;
  }
}

// ---------------------------------------------------------------------------
// Symbol universe (reuses the existing PSX metadata, never duplicates it)
// ---------------------------------------------------------------------------

const INDEX_SET = new Set(INDICES.map((i) => i.symbol));
const STOCK_SET = new Set(STOCKS.map((s) => s.symbol));

/** Tickers the FRONTEND can classify without asking the API. */
export function isKnownIndex(symbol: string): boolean {
  return INDEX_SET.has(symbol.trim().toUpperCase());
}

export function isKnownStock(symbol: string): boolean {
  return STOCK_SET.has(symbol.trim().toUpperCase());
}

/** `ABC`, `AB-1`, `BRK.B` — deliberately permissive; the API is the authority. */
const SYMBOL_RE = /^[A-Z0-9][A-Z0-9._-]{0,11}$/;

export function normalizeSymbol(input: string): string {
  return input.trim().toUpperCase();
}

export function isValidSymbolFormat(symbol: string): boolean {
  return SYMBOL_RE.test(normalizeSymbol(symbol));
}

/**
 * Best guess at what the user typed: an index symbol is plotted as an index
 * (it has its own series), anything else goes through the stock service.
 */
export function inferEntityType(symbol: string): EntityType {
  return isKnownIndex(symbol) ? "INDEX" : "STOCK";
}

export function entityDisplayName(symbol: string, entityType: EntityType): string {
  const s = normalizeSymbol(symbol);
  if (entityType === "INDEX") return INDICES.find((i) => i.symbol === s)?.name ?? s;
  return STOCKS.find((m) => m.symbol === s)?.name ?? s;
}

/**
 * Type-ahead for the chart's symbol box: indices first, then exchange tickers.
 * Matching is prefix-first so typing "H" surfaces HBL before HUBC.
 */
export function symbolSuggestions(query: string, limit = 8): { symbol: string; name: string; entityType: EntityType }[] {
  const q = normalizeSymbol(query);
  if (!q) return [];
  const rank = (symbol: string, name: string) => {
    const upSymbol = symbol.toUpperCase();
    const upName = name.toUpperCase();
    if (upSymbol === q) return 0;
    if (upSymbol.startsWith(q)) return 1;
    if (upName.startsWith(q)) return 2;
    if (upSymbol.includes(q)) return 3;
    if (upName.includes(q)) return 4;
    return -1;
  };
  const rows = [
    ...INDICES.map((i) => ({ symbol: i.symbol, name: i.name, entityType: "INDEX" as EntityType })),
    ...STOCKS.map((s) => ({ symbol: s.symbol, name: s.name, entityType: "STOCK" as EntityType })),
  ]
    .map((row) => ({ row, score: rank(row.symbol, row.name) }))
    .filter((entry) => entry.score >= 0)
    .sort((a, b) => a.score - b.score || a.row.symbol.localeCompare(b.row.symbol))
    .slice(0, limit)
    .map((entry) => entry.row);
  return rows;
}

/**
 * Hand-picked liquid names + the flagship index, used by the empty/error states
 * to offer a working starting point instead of a dead end (spec §29).
 */
export const POPULAR_CHART_SYMBOLS: { symbol: string; entityType: EntityType }[] = [
  { symbol: "KSE100", entityType: "INDEX" },
  { symbol: "OGDC", entityType: "STOCK" },
  { symbol: "LUCK", entityType: "STOCK" },
  { symbol: "HBL", entityType: "STOCK" },
  { symbol: "MEBL", entityType: "STOCK" },
  { symbol: "SYS", entityType: "STOCK" },
  { symbol: "ENGRO", entityType: "STOCK" },
  { symbol: "PSO", entityType: "STOCK" },
];

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

/** Indices only carry intraday bars on the 1D range (Phase-2 behavior). */
export function isIntraday(symbol: string, entityType: EntityType, timeframe: StockRange): boolean {
  if (entityType === "INDEX") return timeframe === "1D";
  return rangeWindow(timeframe).intraday;
}

async function loadStock(symbol: string, timeframe: StockRange): Promise<ChartDataset> {
  const win = rangeWindow(timeframe);
  let response: Awaited<ReturnType<typeof MarketService.getHistory>>;
  try {
    response = await MarketService.getHistory(symbol, win.start, win.end, win.interval);
  } catch (error) {
    throw new ChartDataError(
      "FETCH_FAILED",
      error instanceof Error ? error.message : "The market-data service could not be reached."
    );
  }

  const rows = Array.isArray(response?.rows) ? response.rows : [];
  const normalized = normalizeOHLCV(historyRowsToRaw(rows as unknown as Record<string, unknown>[]));

  return {
    symbol,
    entityType: "STOCK",
    timeframe,
    intraday: win.intraday,
    source: "stock-history",
    name: entityDisplayName(symbol, "STOCK"),
    status: response?.meta?.status ?? null,
    providerSource: response?.meta?.source ?? null,
    fitKey: datasetFitKey(symbol, timeframe, normalized.points),
    points: normalized.points,
    stats: normalized.stats,
  };
}

async function loadIndex(symbol: string, timeframe: StockRange): Promise<ChartDataset> {
  const meta = INDICES.find((i) => i.symbol === symbol);
  if (!meta) {
    throw new ChartDataError(
      "INVALID_SYMBOL",
      `No PSX index named "${symbol}". Try one of: ${INDICES.map((i) => i.symbol).join(", ")}.`
    );
  }

  let points;
  try {
    points = await getHistoryAsync(symbol, timeframe);
  } catch (error) {
    throw new ChartDataError(
      "FETCH_FAILED",
      error instanceof Error ? error.message : "The index series could not be loaded."
    );
  }

  const normalized = normalizeOHLCV(psxPointsToRaw(points ?? []));

  return {
    symbol,
    entityType: "INDEX",
    timeframe,
    intraday: timeframe === "1D",
    source: "psx-index",
    name: meta.name,
    // The Phase-2 index series is deterministic sample data; label it honestly
    // rather than implying a live feed.
    status: "CACHED",
    providerSource: "psx-index-series",
    fitKey: datasetFitKey(symbol, timeframe, normalized.points),
    points: normalized.points,
    stats: normalized.stats,
  };
}

/**
 * Load + normalize one dataset.
 *
 * @throws ChartDataError with a code the UI maps to a specific state.
 */
export async function loadChartDataset(
  rawSymbol: string,
  entityType: EntityType,
  timeframe: StockRange
): Promise<ChartDataset> {
  const symbol = normalizeSymbol(rawSymbol);
  if (!symbol) {
    throw new ChartDataError("INVALID_SYMBOL", "Enter a symbol to plot.");
  }
  if (!isValidSymbolFormat(symbol)) {
    throw new ChartDataError(
      "INVALID_SYMBOL",
      `"${rawSymbol}" is not a valid ticker. Use up to 12 letters, digits, “.” or “-”.`
    );
  }

  const dataset = entityType === "INDEX" ? await loadIndex(symbol, timeframe) : await loadStock(symbol, timeframe);

  if (dataset.points.length === 0) {
    throw new ChartDataError(
      "NO_DATA",
      `No ${timeframe} bars available for ${symbol}. Try another timeframe or symbol.`
    );
  }
  return dataset;
}

/** Human summary of what the normalizer had to do (shown in the data-quality chip). */
export function dataQualitySummary(stats: NormalizedDataset["stats"]): string | null {
  const notes: string[] = [];
  if (stats.rejected > 0) notes.push(`${stats.rejected} malformed bar${stats.rejected === 1 ? "" : "s"} rejected`);
  if (stats.duplicates > 0) notes.push(`${stats.duplicates} duplicate timestamp${stats.duplicates === 1 ? "" : "s"} collapsed`);
  if (stats.outOfOrder > 0) notes.push(`${stats.outOfOrder} out-of-order bar${stats.outOfOrder === 1 ? "" : "s"} re-sorted`);
  if (stats.repaired > 0) notes.push(`${stats.repaired} incoherent OHLC bar${stats.repaired === 1 ? "" : "s"} repaired`);
  if (stats.missingVolume > 0) notes.push(`${stats.missingVolume} bar${stats.missingVolume === 1 ? "" : "s"} without volume`);
  return notes.length ? notes.join(" · ") : null;
}
