import apiClient from "./axios";
import { distanceBudget, fuzzyRank } from "./fuzzy";
import { INDICES, STOCKS } from "./psxMarket";

export type SearchEntityType = "stock" | "index" | "sector";

export interface SearchResult {
  id: string;
  type: SearchEntityType;
  symbol: string;
  name: string;
  sector?: string;
  description?: string;
}

const STOCK_RESULTS: SearchResult[] = STOCKS.map((stock) => ({
  id: `stock-${stock.symbol}`,
  type: "stock",
  symbol: stock.symbol,
  name: stock.name,
  sector: stock.sector,
  description: `${stock.name} · ${stock.sector}`,
}));

const INDEX_RESULTS: SearchResult[] = INDICES.map((index) => ({
  id: `index-${index.symbol}`,
  type: "index",
  symbol: index.symbol,
  name: index.name,
  description: "PSX market index",
}));

const SECTOR_RESULTS: SearchResult[] = [...new Set(STOCKS.map((stock) => stock.sector))].map((sector) => ({
  id: `sector-${sector}`,
  type: "sector",
  symbol: sector,
  name: `${sector} sector`,
  description: "PSX sector universe",
}));

/** The single searchable universe shared by the header and workspace sidebar. */
export const SEARCH_UNIVERSE: readonly SearchResult[] = [
  ...STOCK_RESULTS,
  ...INDEX_RESULTS,
  ...SECTOR_RESULTS,
];

export const POPULAR_SEARCHES = ["OGDC", "LUCK", "HBL", "MEBL", "SYS", "PSO"]
  .map((symbol) => SEARCH_UNIVERSE.find((result) => result.type === "stock" && result.symbol === symbol))
  .filter((result): result is SearchResult => Boolean(result));

function score(result: SearchResult, needle: string): number {
  const symbol = result.symbol.toLowerCase();
  const name = result.name.toLowerCase();
  const sector = result.sector?.toLowerCase() ?? "";
  if (symbol === needle) return 0;
  if (symbol.startsWith(needle)) return 1;
  if (name.startsWith(needle)) return 2;
  if (sector.startsWith(needle)) return 3;
  if (symbol.includes(needle)) return 4;
  if (name.includes(needle)) return 5;
  return 6;
}

/** Fast local autocomplete over the canonical PSX metadata, with stable ranking. */
export function searchGlobal(query: string, limit = 40): SearchResult[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  return SEARCH_UNIVERSE
    .filter((result) => {
      const haystack = `${result.symbol} ${result.name} ${result.sector ?? ""}`.toLowerCase();
      return haystack.includes(needle);
    })
    .sort((a, b) => score(a, needle) - score(b, needle) || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export function normalizeSearchSymbol(symbol: string): string {
  return symbol.trim().toUpperCase();
}

// ---------------------------------------------------------------------------
// Phase 13 — fuzzy + server-ranked search layered on top of the exact path
// ---------------------------------------------------------------------------

function tokensFor(result: SearchResult): string[] {
  return [result.symbol, result.name, result.sector ?? ""].filter((token) => token.length > 0);
}

/**
 * Typo-tolerant local search over the same universe.
 *
 * `searchGlobal` remains the exact/substring path; this is only consulted when
 * it finds nothing, so a query like "OGDC" or "oil" never pays the fuzzy cost.
 */
export function searchGlobalFuzzy(query: string, limit = 20): SearchResult[] {
  const needle = query.trim();
  if (!needle) return [];
  return fuzzyRank(SEARCH_UNIVERSE, tokensFor, needle, { limit, maxDistance: distanceBudget(needle.toLowerCase()) }).map((match) => match.item);
}

export type SearchSource = "LOCAL_EXACT" | "SERVER_BM25" | "LOCAL_FUZZY";

export interface SmartSearchResult {
  results: SearchResult[];
  source: SearchSource;
  error?: string;
}

interface ServerSearchRow {
  id: string;
  type: string;
  symbol: string;
  name: string;
  score: number;
  source?: string;
}

/**
 * Ranked search that degrades honestly, in this order:
 *
 *   1. the local exact matcher (instant, no network);
 *   2. the server's BM25 index (company-alias aware, typo-tolerant);
 *   3. the local fuzzy matcher (BK-tree) when the server is unreachable.
 *
 * `source` tells the caller which one answered, so the UI can label it.
 */
export async function searchGlobalSmart(query: string, limit = 20): Promise<SmartSearchResult> {
  const exact = searchGlobal(query, limit);
  if (exact.length > 0) return { results: exact, source: "LOCAL_EXACT" };

  try {
    const { data } = await apiClient.post<{ results: ServerSearchRow[] }>("/search", { query, limit });
    if (Array.isArray(data?.results) && data.results.length > 0) {
      const results = data.results.map<SearchResult>((row) => ({
        id: row.id,
        type: (["stock", "index", "sector"] as const).includes(row.type as SearchEntityType) ? (row.type as SearchEntityType) : "stock",
        symbol: row.symbol,
        name: row.name,
        description: `Ranked match · score ${Number(row.score ?? 0).toFixed(2)}`,
      }));
      return { results, source: "SERVER_BM25" };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Server search unavailable.";
    return { results: searchGlobalFuzzy(query, limit), source: "LOCAL_FUZZY", error: message };
  }

  return { results: searchGlobalFuzzy(query, limit), source: "LOCAL_FUZZY" };
}
