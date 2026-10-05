/**
 * Phase 22D — Forecast history + realised performance (spec §9, §20, §30, §31).
 *
 * Two backend-only surfaces that Phase 22C computed and stored but never showed:
 *   • REALISED PERFORMANCE — MAE / directional accuracy / interval coverage of
 *     forecasts that were actually scored against the outcome that happened.
 *     A metric with too few evaluations is reported as such, never averaged in.
 *   • STORED HISTORY — the append-only record of every forecast the engine
 *     produced, each with its model/feature version, training window and
 *     whether it has since been evaluated.
 *
 * Nothing here is a promise: it is a retrospective of what the engine actually
 * said versus what actually happened.
 */
import type {
  ForecastHistoryResponse,
  ForecastPerformanceResponse,
} from "../../lib/crypto";
import {
  useCryptoForecastHistory,
  useCryptoForecastPerformance,
} from "../../hooks/useCryptoQueries";
import { formatDateTime, formatPercent, formatPrice, NA } from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoStat, CryptoWidgetError } from "./CryptoStates";

/** The documented stored-forecast row (mirrors the backend persistence shape). */
interface StoredForecast {
  id: string;
  timeframe: string;
  horizon: number;
  generated_at: string;
  target_timestamp: string | null;
  last_close: number | null;
  prediction: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  model_name: string;
  model_version: string;
  beats_baseline: boolean | null;
  data_source: string | null;
  evaluated: boolean;
}

function asStoredForecast(row: Record<string, unknown>): StoredForecast {
  const num = (value: unknown): number | null =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  return {
    id: String(row.id ?? ""),
    timeframe: String(row.timeframe ?? ""),
    horizon: Number(row.horizon ?? 0),
    generated_at: String(row.generated_at ?? ""),
    target_timestamp: (row.target_timestamp as string | null) ?? null,
    last_close: num(row.last_close),
    prediction: num(row.prediction),
    lower_bound: num(row.lower_bound),
    upper_bound: num(row.upper_bound),
    model_name: String(row.model_name ?? NA),
    model_version: String(row.model_version ?? ""),
    beats_baseline: typeof row.beats_baseline === "boolean" ? row.beats_baseline : null,
    data_source: (row.data_source as string | null) ?? null,
    evaluated: Boolean(row.evaluated),
  };
}

export interface CryptoForecastHistoryPanelProps {
  symbol: string;
  timeframe: string;
  enabled?: boolean;
}

export function CryptoForecastHistoryPanel({
  symbol,
  timeframe,
  enabled = true,
}: CryptoForecastHistoryPanelProps) {
  // History is an explicit drill-down: fetched only once the panel is enabled.
  const history = useCryptoForecastHistory(symbol, timeframe, enabled);
  const performance = useCryptoForecastPerformance(symbol);

  const rows = (history.data?.forecasts ?? []).map(asStoredForecast);

  return (
    <>
      <CryptoPanel
        title={
          <span>
            <span className="crypto-model-chip">REALISED</span> Forecast performance
          </span>
        }
        badge={
          performance.data ? (
            <span className="crypto-chip">{performance.data.evaluations} scored forecasts</span>
          ) : undefined
        }
        className="crypto-forecast-perf-panel"
      >
        {performance.isLoading && !performance.data && (
          <CryptoEmpty reason="Reading stored forecast evaluations…" />
        )}
        {performance.isError && (
          <CryptoWidgetError
            title="PERFORMANCE UNAVAILABLE"
            message={(performance.error as Error).message}
            onRetry={() => performance.refetch()}
          />
        )}
        {!performance.isLoading && performance.data && performance.data.status === "UNAVAILABLE" && (
          <CryptoEmpty
            title="NO REALISED FORECASTS YET"
            reason={
              performance.data.reason ??
              "No stored forecast has reached its target time yet, so there is nothing to score."
            }
            hint="Performance is only ever computed from forecasts whose horizon has actually elapsed."
          />
        )}
        {performance.data && performance.data.status === "OK" && (
          <>
            <div className="crypto-stat-grid compact">
              <CryptoStat
                label="Mean absolute error"
                value={fmtMetric(performance.data.mae)}
                sub={`${performance.data.evaluations} evaluations`}
              />
              <CryptoStat
                label="Directional accuracy"
                value={
                  performance.data.directional_accuracy != null
                    ? formatPercent(performance.data.directional_accuracy * 100)
                    : NA
                }
                sub="correct up/down calls"
              />
              <CryptoStat
                label="Interval coverage"
                value={
                  performance.data.interval_coverage != null
                    ? formatPercent(performance.data.interval_coverage * 100)
                    : NA
                }
                sub="actual inside 80% band"
              />
              <CryptoStat
                label="Latest evaluated"
                value={
                  performance.data.latest_evaluated_at
                    ? formatDateTime(performance.data.latest_evaluated_at)
                    : NA
                }
              />
              <CryptoStat
                label="Models scored"
                value={String(performance.data.models.length)}
                sub={performance.data.models.join(", ") || NA}
              />
            </div>
            <p className="crypto-note">
              {performance.data.origin === "MODELLED"
                ? "Retrospective accuracy of forecasts the engine actually published; not a forward guarantee."
                : "Retrospective accuracy from stored evaluations."}
            </p>
          </>
        )}
      </CryptoPanel>

      <CryptoPanel
        title={
          <span>
            <span className="crypto-model-chip">STORED</span> Forecast history · {timeframe}
          </span>
        }
        badge={history.data ? <span className="crypto-chip">{history.data.count} stored</span> : undefined}
        className="crypto-forecast-history-panel"
      >
        {history.isLoading && !history.data && <CryptoEmpty reason="Reading stored forecast history…" />}
        {history.isError && (
          <CryptoWidgetError
            title="HISTORY UNAVAILABLE"
            message={(history.error as Error).message}
            onRetry={() => history.refetch()}
          />
        )}
        {!history.isLoading && !history.isError && rows.length === 0 && (
          <CryptoEmpty
            reason="No forecast for this asset/timeframe has been stored yet."
            hint="Forecasts are persisted (append-only) whenever the engine produces one."
          />
        )}
        {rows.length > 0 && (
          <div className="crypto-table-wrap">
            <table className="crypto-table">
              <caption className="sr-only">
                Append-only stored forecasts with model provenance and evaluation state
              </caption>
              <thead>
                <tr>
                  <th scope="col">Generated</th>
                  <th scope="col">Target time</th>
                  <th scope="col">Prediction</th>
                  <th scope="col">Range</th>
                  <th scope="col">Model</th>
                  <th scope="col">Vs baseline</th>
                  <th scope="col">Evaluated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDateTime(row.generated_at)}</td>
                    <td>{row.target_timestamp ? formatDateTime(row.target_timestamp) : NA}</td>
                    <td><b>{formatPrice(row.prediction)}</b></td>
                    <td className="dim">
                      {row.lower_bound != null && row.upper_bound != null
                        ? `${formatPrice(row.lower_bound)} – ${formatPrice(row.upper_bound)}`
                        : NA}
                    </td>
                    <td>
                      {row.model_name}
                      <span className="dim"> · {row.model_version || NA}</span>
                    </td>
                    <td>
                      {row.beats_baseline == null ? (
                        NA
                      ) : row.beats_baseline ? (
                        <span className="pos">beats</span>
                      ) : (
                        <span className="mut">baseline preferred</span>
                      )}
                    </td>
                    <td>{row.evaluated ? "yes" : "pending"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {history.data?.note && <p className="crypto-note">{history.data.note}</p>}
      </CryptoPanel>
    </>
  );
}

function fmtMetric(value: number | null | undefined): string {
  return value == null ? NA : value.toFixed(4);
}

export default CryptoForecastHistoryPanel;
