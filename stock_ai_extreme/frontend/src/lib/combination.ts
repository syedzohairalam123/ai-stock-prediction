export type CombinationOutcome = "YES" | "NO";

export interface CombinationSelection {
  marketId: string;
  outcome: CombinationOutcome;
  probability: number;
  probabilitySnapshot: number;
  addedAt: string;
}

export interface Combination {
  id: string;
  name: string;
  selections: CombinationSelection[];
  createdAt: string;
  updatedAt: string;
}

export interface CombinationRecord extends Combination {
  probabilitySnapshot: number;
}

export interface CorrelationAssessment {
  status: "INDEPENDENT" | "INDETERMINATE" | "POTENTIAL_CORRELATION";
  message: string;
}

export interface MarketReference {
  id: string;
  title: string;
  category: string;
  status: string;
  updatedAt: string;
  resolution?: string | null;
  yesProbability?: number;
  noProbability?: number;
}

const STORAGE_KEY = "psx-combination-history-v1";

function clampProbability(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > 100) {
    throw new Error("Invalid probability value.");
  }
  return Number(numeric.toFixed(4));
}

export class CombinationCalculator {
  static calculateCombinedProbability(values: Array<number | null | undefined>): number {
    const cleanValues = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    if (cleanValues.length === 0) {
      throw new Error("Add forecast events to begin an analysis.");
    }

    const decimals = cleanValues.map((value) => clampProbability(value) / 100);
    const product = decimals.reduce((accumulator, value) => accumulator * value, 1);
    const result = product * 100;
    if (!Number.isFinite(result) || result < 0 || result > 100) {
      throw new Error("Calculation failure: combined result is invalid.");
    }
    return Number(result.toFixed(1));
  }

  static calculateOutcomeProbability(market: MarketReference | null | undefined, outcome: CombinationOutcome): number | null {
    if (!market || market.status === "RESOLVED") {
      return null;
    }
    if (typeof market.yesProbability !== "number" || typeof market.noProbability !== "number") {
      throw new Error("Missing market probability.");
    }
    const probability = outcome === "YES" ? market.yesProbability : market.noProbability;
    if (!Number.isFinite(probability) || probability < 0 || probability > 100) {
      throw new Error("Invalid probability.");
    }
    return Number(probability.toFixed(2));
  }
}

export class CorrelationService {
  static detectPotentialCorrelation(selections: CombinationSelection[], markets: MarketReference[]): CorrelationAssessment {
    if (selections.length < 2) {
      return {
        status: "INDEPENDENT",
        message: "Independence not verified.",
      };
    }

    const marketMap = new Map(markets.map((market) => [market.id, market]));
    const titles = selections
      .map((selection) => marketMap.get(selection.marketId)?.title ?? "")
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    const categories = new Set(selections.map((selection) => marketMap.get(selection.marketId)?.category).filter(Boolean));
    const duplicateMarketIds = new Set<string>();
    const seen = new Set<string>();
    for (const selection of selections) {
      if (seen.has(selection.marketId)) duplicateMarketIds.add(selection.marketId);
      seen.add(selection.marketId);
    }

    const sharedKeywords = ["final", "match", "team", "company", "index", "inflation", "policy", "election", "series", "product", "release", "politics", "crypto", "economy", "geopolitics"];
    const keywordHits = sharedKeywords.filter((keyword) => titles.includes(keyword));

    if (duplicateMarketIds.size > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION — the same market was selected more than once.",
      };
    }

    if (categories.size === 1 && keywordHits.length > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION — selected events appear to share the same underlying theme or trigger.",
      };
    }

    if (selections.length >= 2 && keywordHits.length > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION — related market language suggests common drivers.",
      };
    }

    return {
      status: "INDETERMINATE",
      message: "Independence not verified.",
    };
  }
}

export class CombinationStorage {
  static load(): CombinationRecord[] {
    if (typeof window === "undefined") {
      return [];
    }

    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) {
        return [];
      }
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
    } catch {
      return [];
    }
  }

  static save(record: CombinationRecord): CombinationRecord {
    const saved = { ...record, updatedAt: new Date().toISOString() };
    const next = [...this.load().filter((existing) => existing.id !== saved.id), saved];
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return saved;
  }

  static saveCombination(record: CombinationRecord): CombinationRecord {
    return this.save(record);
  }

  static loadCombination(id: string): CombinationRecord | null {
    return this.load().find((record) => record.id === id) ?? null;
  }

  static loadCombinations(): CombinationRecord[] {
    return this.load();
  }

  static rename(id: string, name: string): CombinationRecord | null {
    const current = this.load();
    const target = current.find((record) => record.id === id);
    if (!target) {
      return null;
    }
    const renamed = { ...target, name: name.trim() || target.name, updatedAt: new Date().toISOString() };
    const next = current.map((record) => (record.id === id ? renamed : record));
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return renamed;
  }

  static delete(id: string): boolean {
    const current = this.load();
    const next = current.filter((record) => record.id !== id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return current.length !== next.length;
  }
}

export class CombinationService {
  static addSelection(
    selections: CombinationSelection[],
    market: MarketReference | null | undefined,
    outcome: CombinationOutcome,
  ): CombinationSelection[] {
    if (!market || !market.id) {
      throw new Error("Invalid market.");
    }
    if (market.status === "RESOLVED") {
      throw new Error("Resolved market: event is closed and should not be treated as a live estimate.");
    }
    const currentProbability = CombinationCalculator.calculateOutcomeProbability(market, outcome);
    if (currentProbability === null) {
      throw new Error("No valid probability is available for this market.");
    }
    if (selections.some((selection) => selection.marketId === market.id)) {
      throw new Error("Duplicate market: select a different forecast before combining.");
    }

    return [
      ...selections,
      {
        marketId: market.id,
        outcome,
        probability: currentProbability,
        probabilitySnapshot: currentProbability,
        addedAt: new Date().toISOString(),
      },
    ];
  }

  static removeSelection(selections: CombinationSelection[], marketId: string): CombinationSelection[] {
    return selections.filter((selection) => selection.marketId !== marketId);
  }

  static calculateCombinedProbabilityFromSelections(selections: CombinationSelection[]): number {
    return CombinationCalculator.calculateCombinedProbability(
      selections.map((selection) => selection.probability),
    );
  }

  static calculateCombinedProbabilityFromSnapshot(selections: CombinationSelection[]): number {
    return CombinationCalculator.calculateCombinedProbability(
      selections.map((selection) => selection.probabilitySnapshot),
    );
  }

  static getFreshnessStatus(updatedAt: string): "Current" | "Recently Updated" | "Stale" {
    const ageMs = Date.now() - new Date(updatedAt).getTime();
    if (!Number.isFinite(ageMs) || ageMs < 0) {
      return "Stale";
    }
    if (ageMs <= 6 * 60 * 60 * 1000) return "Current";
    if (ageMs <= 7 * 24 * 60 * 60 * 1000) return "Recently Updated";
    return "Stale";
  }
}

export function isMarketFresh(updatedAt: string): boolean {
  return CombinationService.getFreshnessStatus(updatedAt) !== "Stale";
}

export function formatProbability(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return `${value.toFixed(1)}%`;
}
