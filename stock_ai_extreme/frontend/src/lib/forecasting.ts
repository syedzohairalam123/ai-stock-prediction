import apiClient from "./axios";

export const FORECAST_CATEGORIES = ["Politics", "Sports", "Crypto", "Esports", "Finance", "Geopolitics", "Tech", "Culture", "Economy"] as const;
export type ForecastCategory = (typeof FORECAST_CATEGORIES)[number];
export type ForecastStatus = "UPCOMING" | "OPEN" | "CLOSED" | "SUSPENDED" | "RESOLVED";
export type ForecastDataMode = "LIVE" | "DELAYED" | "SIMULATED" | "HISTORICAL" | "UNAVAILABLE";
export type ForecastResolution = "YES" | "NO" | null;
export type ForecastHistoryRange = "1D" | "7D" | "1M" | "FULL";

export interface ProbabilityPoint { timestamp: string; yesProbability: number; noProbability: number; }
export interface ForecastSource { name: string; url: string; publishedAt: string | null; verifiedAt: string | null; }
export interface ForecastMarket {
  id: string; title: string; description: string; category: ForecastCategory; status: ForecastStatus;
  yesProbability: number; noProbability: number; history: ProbabilityPoint[]; closeTime: string;
  resolution: ForecastResolution; sources: ForecastSource[]; createdAt: string; updatedAt: string;
  dataMode: ForecastDataMode; updateCount: number; participantCount: number | null;
  resolutionSource: ForecastSource | null; resolutionDate: string | null;
}

export function normalizeProbabilities(yes: unknown, no?: unknown): { yesProbability: number; noProbability: number } {
  const yesValue = Number(yes);
  const noValue = no === undefined ? 100 - yesValue : Number(no);
  if (!Number.isFinite(yesValue) || !Number.isFinite(noValue)) throw new Error("Probability must be finite.");
  if (yesValue < 0 || yesValue > 100 || noValue < 0 || noValue > 100) throw new Error("Probability must be between 0 and 100.");
  const roundedYes = Math.round(yesValue * 100) / 100;
  const roundedNo = Math.round((100 - roundedYes) * 100) / 100;
  return { yesProbability: roundedYes, noProbability: roundedNo };
}

function normalizePoint(point: Partial<ProbabilityPoint>): ProbabilityPoint {
  const normalized = normalizeProbabilities(point.yesProbability, point.noProbability);
  return { timestamp: typeof point.timestamp === "string" ? point.timestamp : new Date(0).toISOString(), ...normalized };
}

function normalizeMarket(raw: Partial<ForecastMarket>): ForecastMarket {
  const probabilities = normalizeProbabilities(raw.yesProbability, raw.noProbability);
  return {
    id: String(raw.id ?? "unknown-market"), title: String(raw.title ?? "Untitled forecast"),
    description: String(raw.description ?? "No market description supplied."), category: FORECAST_CATEGORIES.includes(raw.category as ForecastCategory) ? raw.category as ForecastCategory : "Finance",
    status: ["UPCOMING", "OPEN", "CLOSED", "SUSPENDED", "RESOLVED"].includes(raw.status as string) ? raw.status as ForecastStatus : "OPEN",
    ...probabilities, history: Array.isArray(raw.history) ? raw.history.map((point) => normalizePoint(point)).sort((a, b) => a.timestamp.localeCompare(b.timestamp)) : [],
    closeTime: String(raw.closeTime ?? new Date().toISOString()), resolution: raw.resolution === "YES" || raw.resolution === "NO" ? raw.resolution : null,
    sources: Array.isArray(raw.sources) ? raw.sources.filter((source) => source && typeof source.url === "string" && source.url.length > 0).map((source) => ({ name: String(source.name ?? "Source"), url: source.url, publishedAt: source.publishedAt ?? null, verifiedAt: source.verifiedAt ?? null })) : [],
    createdAt: String(raw.createdAt ?? new Date().toISOString()), updatedAt: String(raw.updatedAt ?? new Date().toISOString()),
    dataMode: raw.dataMode ?? "UNAVAILABLE", updateCount: Number.isFinite(raw.updateCount) ? Number(raw.updateCount) : 0,
    participantCount: Number.isFinite(raw.participantCount) ? Number(raw.participantCount) : null,
    resolutionSource: raw.resolutionSource && typeof raw.resolutionSource.url === "string" ? raw.resolutionSource as ForecastSource : null,
    resolutionDate: raw.resolutionDate ?? null,
  };
}

const now = Date.now();
function simulatedMarket(id: string, title: string, category: ForecastCategory, yes: number, days: number): ForecastMarket {
  const history: ProbabilityPoint[] = Array.from({ length: 25 }, (_, index) => {
    const progress = index / 24;
    const value = yes - Math.sin(index * 1.7) * 2.4 - (1 - progress) * 4;
    return normalizePoint({ timestamp: new Date(now - (24 - index) * 86_400_000).toISOString(), yesProbability: value });
  });
  return normalizeMarket({ id, title, description: "Educational probability visualization. This fallback is explicitly simulated and is not a financial or wagering product.", category, status: "OPEN", yesProbability: yes, history, closeTime: new Date(now + days * 86_400_000).toISOString(), resolution: null, sources: [], createdAt: new Date(now - 14 * 86_400_000).toISOString(), updatedAt: new Date(now - 3 * 60_000).toISOString(), dataMode: "SIMULATED", updateCount: history.length, participantCount: null, resolutionSource: null, resolutionDate: null });
}

const FALLBACK_MARKETS = [
  simulatedMarket("tech-product-cycle", "Will a major technology product launch occur this quarter?", "Tech", 64, 18),
  simulatedMarket("economy-inflation-path", "Will the next reported inflation reading decline month over month?", "Economy", 57, 24),
  simulatedMarket("finance-index-threshold", "Will the tracked finance index finish above its current reference level?", "Finance", 48, 11),
  simulatedMarket("crypto-volatility-window", "Will crypto market volatility remain elevated over the next seven days?", "Crypto", 61, 7),
  simulatedMarket("sports-finalist", "Will the listed team reach the next tournament final?", "Sports", 43, 30),
  simulatedMarket("geopolitics-briefing", "Will the monitored diplomatic process produce a formal update this month?", "Geopolitics", 35, 21),
  simulatedMarket("culture-release", "Will the announced cultural release arrive before the stated date?", "Culture", 72, 9),
  simulatedMarket("esports-series", "Will the series reach its scheduled deciding match?", "Esports", 54, 5),
  simulatedMarket("politics-information", "Will the scheduled public policy process publish an official update by its deadline?", "Politics", 50, 20),
];

async function request<T>(path: string): Promise<T> { return (await apiClient.get<T>(path)).data; }

export const ForecastService = {
  async getForecastMarkets(): Promise<ForecastMarket[]> { try { const data = await request<ForecastMarket[]>("/forecast/markets"); return data.map(normalizeMarket); } catch { return FALLBACK_MARKETS.map(normalizeMarket); } },
  async getForecastById(id: string): Promise<ForecastMarket> { try { return normalizeMarket(await request<ForecastMarket>(`/forecast/markets/${encodeURIComponent(id)}`)); } catch { const market = FALLBACK_MARKETS.find((item) => item.id === id); if (!market) throw new Error("Forecast market not found."); return normalizeMarket(market); } },
  async getForecastHistory(id: string, range: ForecastHistoryRange = "FULL"): Promise<ProbabilityPoint[]> { const market = await this.getForecastById(id); const cutoff = range === "1D" ? 86_400_000 : range === "7D" ? 7 * 86_400_000 : range === "1M" ? 30 * 86_400_000 : Number.POSITIVE_INFINITY; return market.history.filter((point) => Date.now() - new Date(point.timestamp).getTime() <= cutoff); },
  async getForecastCategories(): Promise<ForecastCategory[]> { try { return await request<ForecastCategory[]>("/forecast/categories"); } catch { return [...FORECAST_CATEGORIES]; } },
  async getResolution(id: string): Promise<{ resolution: ForecastResolution; source: ForecastSource | null; date: string | null }> { const market = await this.getForecastById(id); return { resolution: market.resolution, source: market.resolutionSource, date: market.resolutionDate }; },
};

export function probabilityDelta(history: ProbabilityPoint[], current: number): number | null {
  if (history.length < 2) return null;
  return Math.round((current - history[history.length - 2].yesProbability) * 100) / 100;
}
