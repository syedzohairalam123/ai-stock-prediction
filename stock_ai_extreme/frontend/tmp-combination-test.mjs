// src/lib/combination.ts
var STORAGE_KEY = "psx-combination-history-v1";
function clampProbability(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > 100) {
    throw new Error("Invalid probability value.");
  }
  return Number(numeric.toFixed(4));
}
var CombinationCalculator = class {
  static calculateCombinedProbability(values) {
    const cleanValues = values.filter((value) => typeof value === "number" && Number.isFinite(value));
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
  static calculateOutcomeProbability(market, outcome) {
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
};
var CorrelationService = class {
  static detectPotentialCorrelation(selections, markets) {
    if (selections.length < 2) {
      return {
        status: "INDEPENDENT",
        message: "Independence not verified."
      };
    }
    const marketMap = new Map(markets.map((market) => [market.id, market]));
    const titles = selections.map((selection) => marketMap.get(selection.marketId)?.title ?? "").filter(Boolean).join(" ").toLowerCase();
    const categories = new Set(selections.map((selection) => marketMap.get(selection.marketId)?.category).filter(Boolean));
    const duplicateMarketIds = /* @__PURE__ */ new Set();
    const seen = /* @__PURE__ */ new Set();
    for (const selection of selections) {
      if (seen.has(selection.marketId)) duplicateMarketIds.add(selection.marketId);
      seen.add(selection.marketId);
    }
    const sharedKeywords = ["final", "match", "team", "company", "index", "inflation", "policy", "election", "series", "product", "release", "politics", "crypto", "economy", "geopolitics"];
    const keywordHits = sharedKeywords.filter((keyword) => titles.includes(keyword));
    if (duplicateMarketIds.size > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION \u2014 the same market was selected more than once."
      };
    }
    if (categories.size === 1 && keywordHits.length > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION \u2014 selected events appear to share the same underlying theme or trigger."
      };
    }
    if (selections.length >= 2 && keywordHits.length > 0) {
      return {
        status: "POTENTIAL_CORRELATION",
        message: "POTENTIAL CORRELATION \u2014 related market language suggests common drivers."
      };
    }
    return {
      status: "INDETERMINATE",
      message: "Independence not verified."
    };
  }
};
var CombinationStorage = class {
  static load() {
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
  static save(record) {
    const saved = { ...record, updatedAt: (/* @__PURE__ */ new Date()).toISOString() };
    const next = [...this.load().filter((existing) => existing.id !== saved.id), saved];
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return saved;
  }
  static saveCombination(record) {
    return this.save(record);
  }
  static loadCombination(id) {
    return this.load().find((record) => record.id === id) ?? null;
  }
  static loadCombinations() {
    return this.load();
  }
  static rename(id, name) {
    const current = this.load();
    const target = current.find((record) => record.id === id);
    if (!target) {
      return null;
    }
    const renamed = { ...target, name: name.trim() || target.name, updatedAt: (/* @__PURE__ */ new Date()).toISOString() };
    const next = current.map((record) => record.id === id ? renamed : record);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return renamed;
  }
  static delete(id) {
    const current = this.load();
    const next = current.filter((record) => record.id !== id);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }
    return current.length !== next.length;
  }
};
var CombinationService = class {
  static addSelection(selections, market, outcome) {
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
        addedAt: (/* @__PURE__ */ new Date()).toISOString()
      }
    ];
  }
  static removeSelection(selections, marketId) {
    return selections.filter((selection) => selection.marketId !== marketId);
  }
  static calculateCombinedProbabilityFromSelections(selections) {
    return CombinationCalculator.calculateCombinedProbability(
      selections.map((selection) => selection.probability)
    );
  }
  static calculateCombinedProbabilityFromSnapshot(selections) {
    return CombinationCalculator.calculateCombinedProbability(
      selections.map((selection) => selection.probabilitySnapshot)
    );
  }
  static getFreshnessStatus(updatedAt) {
    const ageMs = Date.now() - new Date(updatedAt).getTime();
    if (!Number.isFinite(ageMs) || ageMs < 0) {
      return "Stale";
    }
    if (ageMs <= 6 * 60 * 60 * 1e3) return "Current";
    if (ageMs <= 7 * 24 * 60 * 60 * 1e3) return "Recently Updated";
    return "Stale";
  }
};
function isMarketFresh(updatedAt) {
  return CombinationService.getFreshnessStatus(updatedAt) !== "Stale";
}
function formatProbability(value) {
  if (value === null || !Number.isFinite(value)) {
    return "\u2014";
  }
  return `${value.toFixed(1)}%`;
}
export {
  CombinationCalculator,
  CombinationService,
  CombinationStorage,
  CorrelationService,
  formatProbability,
  isMarketFresh
};
