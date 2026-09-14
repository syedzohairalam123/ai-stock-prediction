/**
 * PSX Market data service (Phase 2).
 *
 * Deterministic, stable mock data — generated ONCE at module load with a
 * seeded PRNG, so values never change between renders or reloads of the same
 * bundle. The exported API mirrors what a real backend would expose, so this
 * layer can be swapped for live data later without touching the UI:
 *
 *   listIndices()            -> IndexSnapshot[]
 *   getSnapshot(symbol)      -> IndexSnapshot
 *   getHistory(symbol, tf)   -> OHLCVPoint[]
 *   getMarketStatus()        -> MarketStatus (computed from PKT clock)
 */

export type Timeframe = "1D" | "7D" | "1M" | "6M" | "1Y" | "3Y" | "5Y";
export const TIMEFRAMES: Timeframe[] = ["1D", "7D", "1M", "6M", "1Y", "3Y", "5Y"];

export type MarketStatus = "OPEN" | "CLOSED" | "PRE_OPEN" | "POST_MARKET" | "DELAYED_FEED";

export interface IndexMeta {
  symbol: string;
  name: string;
  /** Rough real-world anchor so the mock numbers look plausible per index. */
  baseValue: number;
  /** Typical daily volatility used by the seeded generator. */
  dailyVol: number;
}

export interface IndexSnapshot {
  symbol: string;
  name: string;
  value: number;
  change: number;
  changePct: number;
  open: number;
  prevClose: number;
  dayHigh: number;
  dayLow: number;
  week52High: number;
  week52Low: number;
  totalVolume: number;
  tradedValue: number;
  status: MarketStatus;
  lastUpdated: string;
  sparkline: number[];
}

export interface OHLCVPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ---------------------------------------------------------------------------
// Index universe
// ---------------------------------------------------------------------------

export const INDICES: IndexMeta[] = [
  { symbol: "KSE100", name: "KSE-100 Index", baseValue: 84_500, dailyVol: 0.008 },
  { symbol: "KSEALL", name: "KSE All Share", baseValue: 58_200, dailyVol: 0.009 },
  { symbol: "KSE30", name: "KSE-30 Index", baseValue: 39_400, dailyVol: 0.01 },
  { symbol: "KMI30", name: "KMI-30 Index", baseValue: 120_100, dailyVol: 0.009 },
  { symbol: "KMIALL", name: "KMI All Share", baseValue: 67_800, dailyVol: 0.011 },
  { symbol: "PSXDIV20", name: "PSX Dividend 20", baseValue: 42_900, dailyVol: 0.007 },
];

// ---------------------------------------------------------------------------
// Seeded PRNG (mulberry32) — stable across renders & reloads
// ---------------------------------------------------------------------------

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function gaussian(rand: () => number): number {
  // Box–Muller pair (uses two draws per call)
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// ---------------------------------------------------------------------------
// Stable generation of daily closes per index (520 trading days ≈ 2 years)
// ---------------------------------------------------------------------------

interface Series {
  dates: Date[];
  closes: number[];
  volumes: number[];
}

const seriesCache = new Map<string, Series>();

function getSeries(meta: IndexMeta): Series {
  const cached = seriesCache.get(meta.symbol);
  if (cached) return cached;

  const rand = mulberry32(hashStr(meta.symbol + ":series"));
  const dates: Date[] = [];
  const closes: number[] = [];
  const volumes: number[] = [];

  // 520 trading days, skipping weekends (no holiday calendar in mock land).
  let price = meta.baseValue * (1 + (rand() - 0.5) * 0.12);
  const day = new Date();
  day.setHours(15, 30, 0, 0);
  day.setDate(day.getDate() - 1);
  while (dates.length < 520) {
    day.setDate(day.getDate() - 1);
    if (day.getDay() === 0 || day.getDay() === 6) continue;
    const drift = (rand() - 0.485) * meta.dailyVol;
    const shock = gaussian(rand) * meta.dailyVol * 0.55;
    price = Math.max(price * (1 + drift + shock), meta.baseValue * 0.45);
    const vol = Math.round((0.8 + rand() * 2.2) * meta.baseValue * 60);
    dates.push(new Date(day));
    closes.push(price);
    volumes.push(vol);
  }

  const series = { dates, closes, volumes };
  seriesCache.set(meta.symbol, series);
  return series;
}

// ---------------------------------------------------------------------------
// Snapshot (last trading day values + 52-week range + sparkline)
// ---------------------------------------------------------------------------

const snapshotCache = new Map<string, IndexSnapshot>();

function buildSnapshot(meta: IndexMeta): IndexSnapshot {
  const cached = snapshotCache.get(meta.symbol);
  if (cached) return cached;

  const { dates, closes, volumes } = getSeries(meta);
  const rand = mulberry32(hashStr(meta.symbol + ":snap"));
  const last = closes[closes.length - 1];
  const prev = closes[closes.length - 2];
  const change = last - prev;
  const changePct = (change / prev) * 100;

  const last52 = closes.slice(-252);
  const week52Low = Math.min(...last52);
  const week52High = Math.max(...last52);

  const open = prev * (1 + (rand() - 0.5) * meta.dailyVol * 0.9);
  const dayHigh = Math.max(open, last) * (1 + rand() * meta.dailyVol * 0.5);
  const dayLow = Math.min(open, last) * (1 - rand() * meta.dailyVol * 0.5);
  const totalVolume = volumes.slice(-1)[0] * (1.6 + rand());
  const tradedValue = totalVolume * last;

  const sparkline = closes.slice(-40);

  const snapshot: IndexSnapshot = {
    symbol: meta.symbol,
    name: meta.name,
    value: last,
    change,
    changePct,
    open,
    prevClose: prev,
    dayHigh,
    dayLow,
    week52High,
    week52Low,
    totalVolume,
    tradedValue,
    status: getMarketStatus(),
    lastUpdated: formatPKT(dates[dates.length - 1]),
    sparkline,
  };
  snapshotCache.set(meta.symbol, snapshot);
  return snapshot;
}

// ---------------------------------------------------------------------------
// Market status — computed from the Pakistan (UTC+5) clock, honestly labeled
// ---------------------------------------------------------------------------

export function getMarketStatus(now: Date = new Date()): MarketStatus {
  const pkt = new Date(now.getTime() + 5 * 3600_000);
  const day = pkt.getUTCDay();
  const minutes = pkt.getUTCHours() * 60 + pkt.getUTCMinutes();
  if (day === 0 || day === 6) return "CLOSED";
  if (minutes >= 9 * 60 + 30 && minutes <= 15 * 60 + 30) return "OPEN";
  if (minutes < 9 * 60 + 30) return "PRE_OPEN";
  return "POST_MARKET";
}

export const MARKET_STATUS_LABEL: Record<MarketStatus, string> = {
  OPEN: "MARKET OPEN",
  CLOSED: "MARKET CLOSED",
  PRE_OPEN: "PRE-OPEN",
  POST_MARKET: "POST-MARKET",
  DELAYED_FEED: "DELAYED FEED",
};

function formatPKT(d: Date): string {
  const pkt = new Date(d.getTime() + 5 * 3600_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pkt.getUTCFullYear()}-${pad(pkt.getUTCMonth() + 1)}-${pad(pkt.getUTCDate())} ${pad(pkt.getUTCHours())}:${pad(pkt.getUTCMinutes())} PKT`;
}

// ---------------------------------------------------------------------------
// History per timeframe (deterministic per symbol + timeframe)
// ---------------------------------------------------------------------------

const historyCache = new Map<string, OHLCVPoint[]>();

function buildIntraday(meta: IndexMeta, pointCount: number): OHLCVPoint[] {
  const rand = mulberry32(hashStr(meta.symbol + ":1D"));
  const { dates, closes } = getSeries(meta);
  const base = closes[closes.length - 1];
  const prev = closes[closes.length - 2];
  const dayDate = new Date(dates[dates.length - 1]);
  const points: OHLCVPoint[] = [];

  let lastClose = prev;
  for (let i = 0; i < pointCount; i++) {
    const minute = 9 * 60 + 30 + Math.round((i / pointCount) * (6 * 60)); // 9:30 → 15:30
    const t = new Date(dayDate);
    t.setHours(0, minute, 0, 0);
    const time = formatPKT(t).replace("PKT", "").trim();

    const shock = gaussian(rand) * meta.dailyVol * 0.4;
    let close = lastClose * (1 + shock * 0.35);
    if (i === pointCount - 1) close = base; // end exactly at today's close
    const open = i === 0 ? prev : lastClose;
    const high = Math.max(open, close) * (1 + Math.abs(gaussian(rand)) * meta.dailyVol * 0.3);
    const low = Math.min(open, close) * (1 - Math.abs(gaussian(rand)) * meta.dailyVol * 0.3);
    const volume = Math.round((0.5 + rand()) * meta.baseValue * 40);

    points.push({ time, open, high, low, close, volume });
    lastClose = close;
  }
  return points;
}

function buildDaily(meta: IndexMeta, days: number): OHLCVPoint[] {
  const rand = mulberry32(hashStr(meta.symbol + `:${days}`));
  const { dates, closes, volumes } = getSeries(meta);
  const n = Math.min(days, closes.length);
  const out: OHLCVPoint[] = [];
  for (let i = closes.length - n; i < closes.length; i++) {
    const close = closes[i];
    const open = i > 0 ? closes[i - 1] : close;
    const high = Math.max(open, close) * (1 + Math.abs(gaussian(rand)) * meta.dailyVol * 0.45);
    const low = Math.min(open, close) * (1 - Math.abs(gaussian(rand)) * meta.dailyVol * 0.45);
    out.push({
      time: formatPKT(dates[i]).replace("PKT", "").trim(),
      open,
      high,
      low,
      close,
      volume: volumes[i],
    });
  }
  return out;
}

const TF_DAYS: Record<Exclude<Timeframe, "1D">, number> = {
  "7D": 7,
  "1M": 22,
  "6M": 128,
  "1Y": 252,
  "3Y": 520,
  "5Y": 520,
};

export function getHistory(metaOrSymbol: IndexMeta | string, tf: Timeframe): OHLCVPoint[] {
  const meta =
    typeof metaOrSymbol === "string"
      ? INDICES.find((i) => i.symbol === metaOrSymbol) ?? INDICES[0]
      : metaOrSymbol;
  const key = `${meta.symbol}:${tf}`;
  const cached = historyCache.get(key);
  if (cached) return cached;

  const points =
    tf === "1D"
      ? buildIntraday(meta, 72)
      : buildDaily(meta, TF_DAYS[tf]);

  historyCache.set(key, points);
  return points;
}

// ---------------------------------------------------------------------------
// PHASE 3 — Stock universe (real PSX tickers, deterministic mock quotes)
// ---------------------------------------------------------------------------

export interface StockMeta {
  symbol: string;
  name: string;
  sector: string;
  /** Realistic PKR anchor price. */
  basePrice: number;
  /** Scales generated volume so blue chips dominate the active list. */
  liquidity: number;
  /** Shariah-compliant (KMI30/KMIALL style screening) — powers the Islamic filter. */
  isIslamic: boolean;
  /** Index memberships, e.g. ["KSE100","KSE30"]. */
  indices: string[];
}

export interface StockQuote {
  symbol: string;
  name: string;
  sector: string;
  isIslamic: boolean;
  indices: string[];
  price: number;
  change: number;
  changePct: number;
  open: number;
  prevClose: number;
  dayHigh: number;
  dayLow: number;
  volume: number;
  tradedValue: number;
  lastUpdated: string;
}

export const STOCKS: StockMeta[] = [
  // Exploration & Production
  { symbol: "OGDC", name: "Oil & Gas Dev Co", sector: "E&P", basePrice: 212, liquidity: 3, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "PPL", name: "Pakistan Petroleum", sector: "E&P", basePrice: 176, liquidity: 2.4, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "POL", name: "Pakistan Oilfields", sector: "E&P", basePrice: 612, liquidity: 1.2, isIslamic: true, indices: ["KSE100"] },
  { symbol: "MARI", name: "Mari Petroleum", sector: "E&P", basePrice: 2440, liquidity: 1.1, isIslamic: true, indices: ["KSE100", "KSE30"] },
  // Oil & Gas Marketing / Refinery
  { symbol: "PSO", name: "Pakistan State Oil", sector: "OGM", basePrice: 386, liquidity: 2, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "APL", name: "Attock Petroleum", sector: "OGM", basePrice: 688, liquidity: 0.8, isIslamic: true, indices: ["KSE100"] },
  { symbol: "SNGP", name: "Sui Northern Gas", sector: "OGM", basePrice: 96, liquidity: 1.4, isIslamic: false, indices: ["KSE100"] },
  { symbol: "SSGC", name: "Sui Southern Gas", sector: "OGM", basePrice: 21.5, liquidity: 1.2, isIslamic: false, indices: [] },
  { symbol: "ATRL", name: "Attock Refinery", sector: "Refinery", basePrice: 418, liquidity: 1, isIslamic: true, indices: ["KSE100"] },
  { symbol: "NRL", name: "National Refinery", sector: "Refinery", basePrice: 386, liquidity: 0.7, isIslamic: false, indices: ["KSE100"] },
  { symbol: "PRL", name: "Pakistan Refinery", sector: "Refinery", basePrice: 24, liquidity: 1.3, isIslamic: false, indices: [] },
  // Banks
  { symbol: "HBL", name: "Habib Bank", sector: "Bank", basePrice: 159, liquidity: 2.8, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "UBL", name: "United Bank Ltd", sector: "Bank", basePrice: 322, liquidity: 2.6, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "MCB", name: "MCB Bank", sector: "Bank", basePrice: 264, liquidity: 2.2, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "ABL", name: "Allied Bank", sector: "Bank", basePrice: 118, liquidity: 2.1, isIslamic: false, indices: ["KSE100"] },
  { symbol: "BAFL", name: "Bank Alfalah", sector: "Bank", basePrice: 69, liquidity: 1.8, isIslamic: false, indices: ["KSE100"] },
  { symbol: "BAHL", name: "Bank AL Habib", sector: "Bank", basePrice: 62, liquidity: 1.6, isIslamic: false, indices: ["KSE100"] },
  { symbol: "MEBL", name: "Meezan Bank", sector: "Bank", basePrice: 2350, liquidity: 1.2, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "FABL", name: "Faysal Bank", sector: "Bank", basePrice: 109, liquidity: 1.1, isIslamic: true, indices: ["KSE100"] },
  { symbol: "NBP", name: "National Bank", sector: "Bank", basePrice: 58, liquidity: 1.5, isIslamic: false, indices: ["KSE100"] },
  { symbol: "BOP", name: "Bank of Punjab", sector: "Bank", basePrice: 10.4, liquidity: 2.2, isIslamic: false, indices: [] },
  // Fertilizer
  { symbol: "FFC", name: "Fauji Fertilizer", sector: "Fertilizer", basePrice: 146, liquidity: 2, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "ENGRO", name: "Engro Corporation", sector: "Fertilizer", basePrice: 289, liquidity: 1.9, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "EFERT", name: "Engro Fertilizers", sector: "Fertilizer", basePrice: 106, liquidity: 1.4, isIslamic: true, indices: ["KSE100"] },
  { symbol: "FATIMA", name: "Fatima Fertilizer", sector: "Fertilizer", basePrice: 42, liquidity: 1.7, isIslamic: false, indices: ["KSE100"] },
  // Cement
  { symbol: "LUCK", name: "Lucky Cement", sector: "Cement", basePrice: 642, liquidity: 1.5, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "DGKC", name: "DG Khan Cement", sector: "Cement", basePrice: 109, liquidity: 1.6, isIslamic: true, indices: ["KSE100"] },
  { symbol: "MLCF", name: "Maple Leaf Cement", sector: "Cement", basePrice: 43, liquidity: 1.8, isIslamic: true, indices: ["KSE100"] },
  { symbol: "FCCL", name: "Fauji Cement", sector: "Cement", basePrice: 25, liquidity: 1.9, isIslamic: false, indices: ["KSE100"] },
  { symbol: "CHCC", name: "Cherat Cement", sector: "Cement", basePrice: 184, liquidity: 0.9, isIslamic: true, indices: ["KSE100"] },
  { symbol: "PIOC", name: "Pioneer Cement", sector: "Cement", basePrice: 119, liquidity: 0.8, isIslamic: false, indices: [] },
  // Chemicals
  { symbol: "ICI", name: "ICI Pakistan", sector: "Chemical", basePrice: 1185, liquidity: 0.7, isIslamic: true, indices: ["KSE100"] },
  { symbol: "EPCL", name: "Engro Polymer", sector: "Chemical", basePrice: 43.5, liquidity: 1.6, isIslamic: true, indices: ["KSE100"] },
  { symbol: "LOTCHEM", name: "Lotte Chemical", sector: "Chemical", basePrice: 26, liquidity: 1.5, isIslamic: false, indices: [] },
  { symbol: "NICL", name: "Nishat Chunian Ltd", sector: "Chemical", basePrice: 68, liquidity: 0.6, isIslamic: false, indices: [] },
  // Technology
  { symbol: "SYS", name: "Systems Ltd", sector: "Technology", basePrice: 482, liquidity: 2.1, isIslamic: true, indices: ["KSE100", "KSE30"] },
  { symbol: "NETSOL", name: "NetSol Technologies", sector: "Technology", basePrice: 109, liquidity: 1.4, isIslamic: true, indices: ["KSE100"] },
  { symbol: "TRG", name: "TRG Pakistan", sector: "Technology", basePrice: 48, liquidity: 1.6, isIslamic: false, indices: ["KSE100"] },
  { symbol: "TPL", name: "TPL Insurance", sector: "Technology", basePrice: 12.2, liquidity: 0.9, isIslamic: false, indices: [] },
  { symbol: "AVN", name: "Avanceon Ltd", sector: "Technology", basePrice: 68, liquidity: 0.8, isIslamic: false, indices: [] },
  // Power
  { symbol: "HUBC", name: "Hub Power Co", sector: "Power", basePrice: 129, liquidity: 2.3, isIslamic: false, indices: ["KSE100", "KSE30"] },
  { symbol: "KAPCO", name: "Kot Addu Power", sector: "Power", basePrice: 33.5, liquidity: 1.3, isIslamic: false, indices: ["KSE100"] },
  { symbol: "NCPL", name: "Nishat Chunian Power", sector: "Power", basePrice: 22.5, liquidity: 0.7, isIslamic: false, indices: [] },
  // Textile
  { symbol: "NML", name: "Nishat Mills", sector: "Textile", basePrice: 74, liquidity: 1.2, isIslamic: true, indices: ["KSE100"] },
  { symbol: "ILP", name: "Interloop Ltd", sector: "Textile", basePrice: 391, liquidity: 1.1, isIslamic: true, indices: ["KSE100"] },
  { symbol: "NCL", name: "Nishat (Chunian)", sector: "Textile", basePrice: 42, liquidity: 0.6, isIslamic: false, indices: [] },
];

/** Look up the static PSX metadata (sector, Shariah flag, index membership)
 * for a symbol. Returns undefined for symbols outside the known PSX universe
 * (e.g. US tickers) — callers must treat that as "not applicable", never
 * guess a Shariah status. */
export function getStockMeta(symbol: string): StockMeta | undefined {
  const s = symbol.trim().toUpperCase();
  return STOCKS.find((m) => m.symbol === s);
}

/** Human label for a symbol's sector, falling back to the static PSX universe. */
export function sectorLabel(symbol: string, fallback?: string | null): string | null {
  if (fallback && fallback.trim()) return fallback;
  return getStockMeta(symbol)?.sector ?? null;
}

const stockQuoteCache = new Map<string, StockQuote>();

function buildStockQuote(meta: StockMeta): StockQuote {
  const cached = stockQuoteCache.get(meta.symbol);
  if (cached) return cached;

  const rand = mulberry32(hashStr(meta.symbol + ":quote"));
  const volFactor = 0.014 + meta.liquidity * 0.006; // liquid names swing a bit more
  const changePct = gaussian(rand) * volFactor;
  const prevClose = meta.basePrice * (1 + (rand() - 0.5) * 0.01);
  const price = Math.max(prevClose * (1 + changePct), 0.5);
  const change = price - prevClose;
  const open = prevClose * (1 + (rand() - 0.5) * volFactor * 0.6);
  const dayHigh = Math.max(open, price) * (1 + Math.abs(gaussian(rand)) * volFactor * 0.35);
  const dayLow = Math.min(open, price) * (1 - Math.abs(gaussian(rand)) * volFactor * 0.35);
  const volume = Math.round((0.15 + rand() * 1.35) * meta.liquidity * 2_400_000);
  const tradedValue = volume * price * (1 + (rand() - 0.5) * 0.004);

  const quote: StockQuote = {
    symbol: meta.symbol,
    name: meta.name,
    sector: meta.sector,
    isIslamic: meta.isIslamic,
    indices: meta.indices,
    price,
    change,
    changePct: (change / prevClose) * 100,
    open,
    prevClose,
    dayHigh,
    dayLow,
    volume,
    tradedValue,
    lastUpdated: formatPKT(new Date()),
  };
  stockQuoteCache.set(meta.symbol, quote);
  return quote;
}

export type MoversUniverse = "KSE100" | "ALL" | "ISLAMIC";

export const MOVERS_UNIVERSES: { id: MoversUniverse; label: string }[] = [
  { id: "KSE100", label: "KSE 100" },
  { id: "ALL", label: "All Stocks" },
  { id: "ISLAMIC", label: "All Islamic" },
];

export function isMoversUniverse(v: unknown): v is MoversUniverse {
  return v === "KSE100" || v === "ALL" || v === "ISLAMIC";
}

function filterStocks(u: MoversUniverse): StockMeta[] {
  if (u === "ALL") return STOCKS;
  if (u === "ISLAMIC") return STOCKS.filter((s) => s.isIslamic);
  return STOCKS.filter((s) => s.indices.includes("KSE100"));
}

export interface MoversData {
  universe: MoversUniverse;
  /** Stocks considered for this universe — powers the "N stocks" UI hint. */
  universeSize: number;
  mostActive: StockQuote[];
  gainers: StockQuote[];
  losers: StockQuote[];
}

export async function getMovers(u: MoversUniverse, limit = 8): Promise<MoversData> {
  await apiDelay();
  const quotes = filterStocks(u).map(buildStockQuote);
  const byVol = [...quotes].sort((a, b) => b.volume - a.volume);
  const byGain = [...quotes].sort((a, b) => b.changePct - a.changePct);
  return {
    universe: u,
    universeSize: quotes.length,
    mostActive: byVol.slice(0, limit),
    gainers: byGain.slice(0, limit),
    losers: byGain.slice(-limit).reverse(),
  };
}

// ---------------------------------------------------------------------------
// PHASE 3 — Shariah index flags + index performance table service
// ---------------------------------------------------------------------------

export const SHARIAH_INDICES: ReadonlySet<string> = new Set(["KMI30", "KMIALL"]);

export function isShariahIndex(symbol: string): boolean {
  return SHARIAH_INDICES.has(symbol);
}

/** Single source of truth for the performance table — reuses index snapshots. */
export async function getIndexPerformance(): Promise<IndexSnapshot[]> {
  return listIndices();
}

export type PerfSortKey =
  | "name"
  | "value"
  | "change"
  | "changePct"
  | "totalVolume"
  | "tradedValue"
  | "open"
  | "dayHigh"
  | "dayLow";

export function sortIndexRows(
  rows: IndexSnapshot[],
  key: PerfSortKey,
  dir: "asc" | "desc"
): IndexSnapshot[] {
  const mul = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "name") return a.name.localeCompare(b.name) * mul;
    return ((a[key] as number) - (b[key] as number)) * mul;
  });
}

// ---------------------------------------------------------------------------
// Public API (async so loading states are real; resolves fast with mock data)
// ---------------------------------------------------------------------------

const apiDelay = () => new Promise<void>((r) => setTimeout(r, 260 + Math.random() * 320));

export async function listIndices(): Promise<IndexSnapshot[]> {
  await apiDelay();
  return INDICES.map((m) => buildSnapshot(m));
}

export async function getSnapshot(symbol: string): Promise<IndexSnapshot> {
  await apiDelay();
  const meta = INDICES.find((i) => i.symbol === symbol);
  if (!meta) throw new Error(`Unknown index: ${symbol}`);
  return buildSnapshot(meta);
}

export async function getHistoryAsync(
  symbol: string,
  tf: Timeframe
): Promise<OHLCVPoint[]> {
  await apiDelay();
  return getHistory(symbol, tf);
}

/** Runtime guard for timeframe values (e.g. URL/search-param input). */
export function isTimeframe(v: unknown): v is Timeframe {
  return typeof v === "string" && (TIMEFRAMES as string[]).includes(v);
}

/** Human-friendly formatting helpers shared by the market UI. */
export function fmtNum(v: number, digits = 2): string {
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtCompact(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

/** Signed integer-ish values: +1,250 / -380 */
export function fmtSigned(v: number, digits = 2): string {
  return `${v >= 0 ? "+" : ""}${fmtNum(v, digits)}`;
}

/** Percent with explicit sign: +1.42% / -0.85% */
export function fmtPct(v: number, digits = 2): string {
  return `${fmtSigned(v, digits)}%`;
}

/** Consistently formatted PKR amount: ₨ 1,250.00 */
export function fmtPkr(v: number, digits = 2): string {
  return `₨ ${fmtNum(v, digits)}`;
}

/** Human-readable local timestamp from a mock point's `time` string. */
export function fmtPointTime(time: string, intraday: boolean): string {
  const d = new Date(intraday ? time.replace(" ", "T") : time);
  if (isNaN(d.getTime())) return time;
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(intraday ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

/** Aggregated stats over one historical dataset — powers the chart stat chips. */
export interface PeriodStats {
  open: number;
  high: number;
  low: number;
  close: number;
  change: number;
  changePct: number;
  volume: number;
  points: number;
  prevClose: number;
}

export function getPeriodStats(points: OHLCVPoint[]): PeriodStats | null {
  if (!points.length) return null;
  const first = points[0];
  const last = points[points.length - 1];
  const high = Math.max(...points.map((p) => p.high));
  const low = Math.min(...points.map((p) => p.low));
  const volume = points.reduce((s, p) => s + p.volume, 0);
  // Reference for period change: the close *before* this window opened.
  const ref = first.open;
  const change = last.close - ref;
  return {
    open: first.open,
    high,
    low,
    close: last.close,
    change,
    changePct: (change / ref) * 100,
    volume,
    points: points.length,
    prevClose: ref,
  };
}