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
