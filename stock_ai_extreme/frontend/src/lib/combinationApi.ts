/**
 * Phase 15.1/15.2 — transport layer for the correlation-adjusted combination
 * engine and server-persisted combinations.
 *
 * Kept separate from `combination.ts` on purpose: that module is the *pure*
 * model (types + the independence calculator) and is bundled standalone by
 * `scripts/combination-analysis-test.mjs`, so it must not pull in an HTTP
 * client. Everything that talks to the backend lives here.
 *
 * Every method degrades to `null`/`false`/an `error` string rather than
 * throwing, so the UI keeps showing the independence estimate when the backend
 * is unreachable.
 */
import apiClient from "./axios";
import type {
  CombinationAnalysis,
  CombinationEventInput,
  CombinationRecord,
  CombinationSelection,
  CombineOptions,
  CorrelationAnalysisResult,
  CorrelationMatrixReport,
  CorrelationOnlyResult,
} from "./combination";

function toEventPayload(events: CombinationEventInput[]): Array<Record<string, unknown>> {
  return events.map((event) => ({
    marketId: event.marketId,
    outcome: event.outcome,
    probability: event.probability,
    ...(event.label ? { label: event.label } : {}),
  }));
}

/**
 * Correlation-adjusted combination via the backend engine.
 *
 * Always returns a result object: the panel keeps the independence estimate on
 * screen and shows `error` when the engine cannot run (offline, or too little
 * history), instead of breaking the analysis.
 */
export class CorrelationAdjustedCalculator {
  static async combine(events: CombinationEventInput[], options: CombineOptions = {}): Promise<CorrelationAnalysisResult> {
    if (events.length < 2) {
      return { analysis: null, error: "Select at least two events to run a correlation-adjusted analysis." };
    }
    try {
      const { data } = await apiClient.post<CombinationAnalysis>("/forecast/combine", {
        events: toEventPayload(events),
        ...(options.draws ? { draws: options.draws } : {}),
        ...(options.deltaPp !== undefined ? { deltaPp: options.deltaPp } : {}),
        ...(options.seed !== undefined ? { seed: options.seed } : {}),
        includeSensitivity: options.includeSensitivity ?? true,
      });
      return { analysis: data, error: null };
    } catch (error) {
      return { analysis: null, error: error instanceof Error ? error.message : "Correlation analysis is temporarily unavailable." };
    }
  }

  static async correlate(events: CombinationEventInput[]): Promise<CorrelationOnlyResult> {
    if (events.length < 2) {
      return { report: null, error: "Select at least two events." };
    }
    try {
      const { data } = await apiClient.post<CorrelationMatrixReport>("/forecast/correlate", { events: toEventPayload(events) });
      return { report: data, error: null };
    } catch (error) {
      return { report: null, error: error instanceof Error ? error.message : "Correlation matrix is temporarily unavailable." };
    }
  }
}

/**
 * Server-persisted combinations + append-only snapshots.
 *
 * Mirrors the Phase 12 workspace pattern: the localStorage store stays the
 * offline fallback, and this adapter is used when the backend is reachable.
 */
export class CombinationBackendStorage {
  static async load(): Promise<CombinationRecord[] | null> {
    try {
      const { data } = await apiClient.get<{ combinations: Array<Record<string, unknown>> }>("/forecast/combinations");
      if (!Array.isArray(data?.combinations)) return null;
      return data.combinations.map((row) => ({
        id: String(row.id),
        name: String(row.name ?? "Untitled combination"),
        selections: (row.selections as CombinationSelection[]) ?? [],
        probabilitySnapshot: Number(row.combined_probability ?? 0),
        createdAt: String(row.created_at ?? new Date().toISOString()),
        updatedAt: String(row.updated_at ?? new Date().toISOString()),
      }));
    } catch {
      return null;
    }
  }

  static async save(record: CombinationRecord): Promise<CombinationRecord | null> {
    try {
      const { data } = await apiClient.post<Record<string, unknown>>("/forecast/combinations", {
        id: record.id,
        name: record.name,
        selections: record.selections,
        combinedProbability: record.probabilitySnapshot,
      });
      return { ...record, id: String(data.id ?? record.id) };
    } catch {
      return null;
    }
  }

  static async remove(id: string): Promise<boolean> {
    try {
      await apiClient.delete(`/forecast/combinations/${encodeURIComponent(id)}`);
      return true;
    } catch {
      return false;
    }
  }

  static async snapshot(id: string, combinedProbability: number, correlationAdjusted?: number): Promise<boolean> {
    try {
      await apiClient.post(`/forecast/combinations/${encodeURIComponent(id)}/snapshot`, {
        combinedProbability,
        ...(correlationAdjusted !== undefined ? { correlationAdjustedProbability: correlationAdjusted } : {}),
      });
      return true;
    } catch {
      return false;
    }
  }
}
