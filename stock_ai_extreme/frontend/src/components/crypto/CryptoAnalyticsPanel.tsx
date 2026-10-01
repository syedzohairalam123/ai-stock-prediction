/**
 * Phase 22A — per-timeframe analytics: indicators, volatility regime and the
 * micro-trend read (spec §11/§12/§13).
 *
 * Every figure is real computation on real candles; a value the window cannot
 * support renders `N/A`. Trend direction is shown with an arrow + word + tone,
 * never colour alone (accessibility).
 */
import type { AnalyticsResponse } from "../../lib/crypto";
import {
  formatPercent,
  formatPercentPlain,
  formatPrice,
  NA,
  originLabel,
  statusTone,
} from "../../lib/cryptoFormat";

export interface CryptoAnalyticsPanelProps {
  analytics: AnalyticsResponse | undefined;
  loading: boolean;
  error: string | null;
}

const REGIME_TONE: Record<string, string> = {
  LOW: "native",
  NORMAL: "",
  HIGH: "warn",
  EXTREME: "danger",
  INSUFFICIENT_DATA: "",
};

const TREND_ARROW: Record<string, string> = {
  UP: "▲",
  DOWN: "▼",
  SIDEWAYS: "▬",
  INSUFFICIENT_DATA: "—",
};

export function CryptoAnalyticsPanel({ analytics, loading, error }: CryptoAnalyticsPanelProps) {
  const trend = analytics?.trend;
  const vol = analytics?.volatility;
  const ind = analytics?.indicators;

  return (
    <section className="panel crypto-analytics-panel">
      <div className="crypto-panel-head">
        <h2>Analytics{analytics ? ` · ${analytics.timeframe_label}` : ""}</h2>
        {analytics && (
          <span className={`freshness ${statusTone(analytics.data_status)}`}>{analytics.data_status}</span>
        )}
      </div>

      {loading && !analytics && <p className="empty">Computing analytics…</p>}
      {error && <div className="warn-banner" role="alert">{error}</div>}

      {analytics && (
        <>
          <div className="crypto-trend-card">
            <div className={`crypto-trend-dir ${trendClass(trend?.direction)}`} role="status">
              <span aria-hidden>{TREND_ARROW[trend?.direction ?? "INSUFFICIENT_DATA"]}</span>
              {trend?.direction ?? "INSUFFICIENT_DATA"}
            </div>
            <div className="crypto-trend-facts">
              <Fact label="Strength" value={trend ? `${(trend.strength * 100).toFixed(0)}%` : NA} />
              <Fact label="Confidence" value={trend ? `${(trend.confidence * 100).toFixed(0)}%` : NA} />
              <Fact label="Recent return" value={formatPercent(trend?.recent_return ?? null)} />
              <Fact label="Sample size" value={analytics.sample_size ? String(analytics.sample_size) : NA} />
            </div>
          </div>

          {trend?.factors && Object.keys(trend.factors).length > 0 && (
            <details className="crypto-details">
              <summary>Trend factors</summary>
              <div className="crypto-kv">
                {Object.entries(trend.factors).map(([key, value]) => (
                  <div key={key}>
                    <span>{key.replace(/_/g, " ")}</span>
                    <b>{typeof value === "number" ? value.toFixed(4) : String(value)}</b>
                  </div>
                ))}
              </div>
            </details>
          )}

          <div className="crypto-stat-grid compact">
            <Metric label="Last close" value={formatPrice(analytics.last_close)} origin={analytics.returns?.origin} />
            <Metric label="EMA fast" value={formatPrice(ind?.ema_fast ?? null)} />
            <Metric label="EMA slow" value={formatPrice(ind?.ema_slow ?? null)} />
            <Metric label="RSI (14)" value={ind?.rsi != null ? ind.rsi.toFixed(2) : NA} />
            <Metric label="ATR" value={formatPrice(ind?.atr ?? null)} />
            <Metric label="ATR %" value={formatPercentPlain(ind?.atr_percent ?? null)} />
            <Metric label="Momentum" value={formatPercent(ind?.momentum ?? null)} />
            <Metric label="Range position" value={ind?.range_position != null ? `${(ind.range_position * 100).toFixed(1)}%` : NA} />
            <Metric label="Volume change" value={formatPercent(ind?.volume_change ?? null)} />
          </div>

          <div className="crypto-vol-card">
            <div className="crypto-vol-head">
              <span>Volatility</span>
              {vol && (
                <span className={`crypto-chip ${REGIME_TONE[vol.regime] ?? ""}`}>{vol.regime}</span>
              )}
            </div>
            <div className="crypto-stat-grid compact">
              <Metric
                label="Realized (annualised)"
                value={vol?.realized_volatility != null ? `${(vol.realized_volatility * 100).toFixed(2)}%` : NA}
              />
              <Metric label="Rolling std" value={vol?.rolling_std != null ? vol.rolling_std.toFixed(4) : NA} />
              <Metric label="ATR %" value={formatPercentPlain(vol?.atr_percent ?? null)} />
              <Metric
                label="Percentile"
                value={vol?.volatility_percentile != null ? `${vol.volatility_percentile.toFixed(1)}` : NA}
              />
              <Metric label="Window" value={vol?.window ? String(vol.window) : NA} />
              <Metric label="Samples" value={vol?.sample_size ? String(vol.sample_size) : NA} />
            </div>
          </div>

          {analytics.note && <p className="crypto-note">{analytics.note}</p>}
        </>
      )}
    </section>
  );
}

function trendClass(direction: string | null | undefined): string {
  if (direction === "UP") return "pos";
  if (direction === "DOWN") return "neg";
  return "mut";
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="crypto-fact">
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Metric({
  label,
  value,
  origin,
}: {
  label: string;
  value: string;
  origin?: string;
}) {
  return (
    <div className="crypto-stat">
      <span className="crypto-stat-k">{label}</span>
      <span className="crypto-stat-v">{value}</span>
      {origin && <span className="crypto-stat-s">{originLabel(origin)}</span>}
    </div>
  );
}

export default CryptoAnalyticsPanel;
