/**
 * Phase 22C — MODELLED FORECAST card + model provenance (spec §8/§9/§35).
 *
 * The card never uses "guaranteed"/"certain"/"will". It states the horizon, the
 * empirical prediction range, the model + version, when it was generated, the
 * data source and the quality. The expandable section exposes the validation
 * evidence (walk-forward MAE/RMSE/directional accuracy) and the baseline
 * comparison — including when the baseline *wins*, which is reported, not hidden.
 */
import { useState } from "react";

import type { ForecastResponse } from "../../lib/crypto";
import {
  formatDateTime,
  formatPercent,
  formatPrice,
  NA,
  originLabel,
} from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoSkeleton, CryptoStat, CryptoWidgetError } from "./CryptoStates";

export interface CryptoForecastPanelProps {
  symbol: string;
  data: ForecastResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  horizon: number;
  onHorizonChange: (next: number) => void;
}

const HORIZONS = [1, 3, 5, 10, 20];

export function CryptoForecastPanel({
  symbol,
  data,
  loading,
  error,
  onRetry,
  horizon,
  onHorizonChange,
}: CryptoForecastPanelProps) {
  const [showInfo, setShowInfo] = useState(false);
  const forecast = data?.forecast ?? null;

  return (
    <CryptoPanel
      title={
        <span>
          <span className="crypto-model-chip">MODELLED FORECAST</span> {symbol}
        </span>
      }
      badge={
        <div className="crypto-horizon-control" role="group" aria-label="Forecast horizon">
          {HORIZONS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={value === horizon}
              className={value === horizon ? "active" : undefined}
              onClick={() => onHorizonChange(value)}
              title={`Forecast ${value} bar${value > 1 ? "s" : ""} ahead`}
            >
              {value}
            </button>
          ))}
        </div>
      }
      className="crypto-forecast-panel"
    >
      {loading && !data && <CryptoSkeleton height={180} label="Generating modelled forecast" />}
      {error && <CryptoWidgetError title="FORECAST UNAVAILABLE" message={error} onRetry={onRetry} />}

      {!loading && !error && data && !data.forecast && (
        <CryptoEmpty
          title="FORECAST UNAVAILABLE"
          reason={data.reason ?? "The engine declined to produce a forecast for this configuration."}
          hint="A forecast is withheld when there is not enough real history, or when a model cannot be validated."
        />
      )}

      {data && forecast && (
        <>
          <div className="crypto-forecast-grid">
            <CryptoStat
              label="Prediction"
              value={formatPrice(forecast.prediction)}
              sub={`${horizon}-bar horizon`}
            />
            <CryptoStat
              label="Prediction range"
              value={
                forecast.lower_bound != null && forecast.upper_bound != null
                  ? `${formatPrice(forecast.lower_bound)} – ${formatPrice(forecast.upper_bound)}`
                  : NA
              }
              sub="80% empirical residual band"
            />
            <CryptoStat
              label="Last close"
              value={formatPrice(forecast.last_close)}
              sub={data.timeframe_label}
            />
            <CryptoStat label="Model" value={forecast.model_name} sub={forecast.model_version} />
            <CryptoStat
              label="Vs baseline"
              value={
                forecast.beats_baseline ? (
                  <span className="pos">beats baseline</span>
                ) : (
                  <span className="mut">baseline preferred</span>
                )
              }
              tone={forecast.beats_baseline ? undefined : "mut"}
              title="A baseline is kept when no ML model genuinely beats it on held-out data"
            />
            <CryptoStat
              label="Generated"
              value={formatDateTime(forecast.generated_at)}
              sub={`${originLabel(forecast.origin)} · quality ${data.quality}`}
            />
            <CryptoStat
              label="Source"
              value={data.source ?? NA}
              sub={`${data.candles_used} candles`}
            />
            <CryptoStat
              label="Target time"
              value={data.target_timestamp ? formatDateTime(data.target_timestamp) : NA}
              sub="UTC stored · local shown"
            />
          </div>

          <div className="crypto-forecast-chips">
            {data.anomaly && (
              <span
                className={`crypto-chip ${String(data.anomaly.status) === "DATA ANOMALY" ? "warn" : "native"}`}
              >
                {String(data.anomaly.status)}
              </span>
            )}
            {data.drift && (
              <span
                className={`crypto-chip ${
                  String(data.drift.status) === "MODEL PERFORMANCE DEGRADED"
                    ? "danger"
                    : String(data.drift.status) === "WATCH"
                      ? "warn"
                      : "native"
                }`}
              >
                drift {String(data.drift.status)}
              </span>
            )}
            <span className="crypto-chip">{data.validation.length} models validated</span>
          </div>

          <button
            type="button"
            className="crypto-disclosure"
            aria-expanded={showInfo}
            onClick={() => setShowInfo((value) => !value)}
          >
            {showInfo ? "▾" : "▸"} Model information
          </button>

          {showInfo && (
            <div className="crypto-model-info" id="crypto-model-info">
              <div className="crypto-stat-grid compact">
                <CryptoStat label="Model" value={forecast.model_name} />
                <CryptoStat label="Version" value={forecast.model_version} />
                <CryptoStat label="Feature version" value={forecast.feature_version} />
                <CryptoStat label="Training window" value={String(forecast.training_window)} />
                <CryptoStat
                  label="Training end"
                  value={forecast.training_end_time ? formatDateTime(forecast.training_end_time) : NA}
                />
                <CryptoStat label="MAE" value={fmt(forecast.metrics.mae)} />
                <CryptoStat label="RMSE" value={fmt(forecast.metrics.rmse)} />
                <CryptoStat
                  label="Directional accuracy"
                  value={
                    forecast.metrics.directional_accuracy != null
                      ? `${(forecast.metrics.directional_accuracy * 100).toFixed(1)}%`
                      : NA
                  }
                />
                <CryptoStat label="Sample size" value={String(forecast.metrics.observations)} />
                <CryptoStat label="Baseline RMSE" value={fmt(forecast.baseline_metrics.rmse)} />
              </div>

              {data.validation.length > 0 && (
                <div className="crypto-table-wrap">
                  <table className="crypto-table">
                    <caption className="sr-only">Walk-forward validation results per model</caption>
                    <thead>
                      <tr>
                        <th scope="col">Model</th>
                        <th scope="col">Kind</th>
                        <th scope="col">RMSE</th>
                        <th scope="col">MAE</th>
                        <th scope="col">Dir. acc</th>
                        <th scope="col">Folds</th>
                        <th scope="col">Obs.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.validation.map((row) => (
                        <tr key={row.model}>
                          <td>{row.model}</td>
                          <td>{row.kind}</td>
                          <td>{fmt(row.metrics.rmse)}</td>
                          <td>{fmt(row.metrics.mae)}</td>
                          <td>{formatPercent((row.metrics.directional_accuracy ?? 0) * 100)}</td>
                          <td>{row.folds}</td>
                          <td>{row.observations}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {forecast.limitations.length > 0 && (
                <ul className="crypto-limitations">
                  {forecast.limitations.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {data.note && <p className="crypto-note">{data.note}</p>}
        </>
      )}
    </CryptoPanel>
  );
}

function fmt(value: number | null | undefined): string {
  return value == null ? NA : value.toFixed(4);
}

export default CryptoForecastPanel;
