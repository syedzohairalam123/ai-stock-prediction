/**
 * Phase 22A — multi-timeframe comparison (spec §9).
 *
 * One row per configured timeframe (5m → 1Y), each filled from the same real
 * OHLCV engine. Rows the provider cannot support are marked, not hidden, and a
 * row with an error reports that error instead of a blank.
 */
import type { MultiTimeframeResponse } from "../../lib/crypto";
import { formatPercent, formatPercentPlain, NA, statusTone } from "../../lib/cryptoFormat";

export interface CryptoMultiTimeframePanelProps {
  data: MultiTimeframeResponse | undefined;
  loading: boolean;
  error: string | null;
  selectedTimeframe: string;
  onSelect: (timeframe: string) => void;
}

const TREND_ARROW: Record<string, string> = {
  UP: "▲",
  DOWN: "▼",
  SIDEWAYS: "▬",
  INSUFFICIENT_DATA: "—",
};

function trendClass(trend: string | null | undefined): string {
  if (trend === "UP") return "pos";
  if (trend === "DOWN") return "neg";
  return "mut";
}

export function CryptoMultiTimeframePanel({
  data,
  loading,
  error,
  selectedTimeframe,
  onSelect,
}: CryptoMultiTimeframePanelProps) {
  const rows = [...(data?.rows ?? [])].sort(
    (a, b) => durationOf(a.timeframe) - durationOf(b.timeframe)
  );
  const summary = data?.summary ?? {};

  return (
    <section className="panel crypto-mtf-panel">
      <div className="crypto-panel-head">
        <h2>Multi-timeframe view</h2>
        <span className="crypto-chip">7 native + 1 roll-up</span>
      </div>

      {loading && rows.length === 0 && <p className="empty">Computing every timeframe…</p>}
      {error && <div className="warn-banner" role="alert">{error}</div>}

      {rows.length > 0 && (
        <div className="crypto-table-wrap">
          <table className="crypto-table">
            <thead>
              <tr>
                <th scope="col">Timeframe</th>
                <th scope="col">Trend</th>
                <th scope="col">Strength</th>
                <th scope="col">Return</th>
                <th scope="col">Return (20)</th>
                <th scope="col">Volatility</th>
                <th scope="col">Regime</th>
                <th scope="col">ATR %</th>
                <th scope="col">Vol Δ</th>
                <th scope="col">Status</th>
                <th scope="col">Quality</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const active = row.timeframe === selectedTimeframe;
                return (
                  <tr
                    key={row.timeframe}
                    className={active ? "active" : undefined}
                    onClick={() => onSelect(row.timeframe)}
                    title={row.error ? `Error: ${row.error}` : `View ${row.label}`}
                  >
                    <td>
                      <button type="button" className="crypto-tf-link">
                        {row.timeframe}
                      </button>
                      <span className="dim"> {row.label}</span>
                    </td>
                    <td className={trendClass(row.trend)}>
                      <span aria-hidden>{TREND_ARROW[row.trend] ?? "—"}</span> {row.trend}
                    </td>
                    <td>{row.trend_strength != null ? `${(row.trend_strength * 100).toFixed(0)}%` : NA}</td>
                    <td className={trendClass((row.return ?? 0) >= 0 ? "UP" : "DOWN")}>
                      {formatPercent(row.return ?? null)}
                    </td>
                    <td>{formatPercent(row.return_over_20 ?? null)}</td>
                    <td>{row.volatility != null ? `${(row.volatility * 100).toFixed(2)}%` : NA}</td>
                    <td>{row.volatility_regime ?? NA}</td>
                    <td>{formatPercentPlain(row.atr_percent ?? null)}</td>
                    <td>{formatPercent(row.volume_change ?? null)}</td>
                    <td>
                      <span className={`freshness ${statusTone(row.data_status)}`}>{row.data_status}</span>
                    </td>
                    <td>{row.error ? <span className="neg">error</span> : row.quality ?? NA}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(summary).length > 0 && (
        <details className="crypto-details">
          <summary>Cross-timeframe summary</summary>
          <div className="crypto-kv">
            {Object.entries(summary).map(([key, value]) => (
              <div key={key}>
                <span>{key.replace(/_/g, " ")}</span>
                <b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b>
              </div>
            ))}
          </div>
        </details>
      )}

      {data?.note && <p className="crypto-note">{data.note}</p>}
    </section>
  );
}

/** Order timeframes shortest → longest without importing the registry (UI-only). */
function durationOf(id: string): number {
  const map: Record<string, number> = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    "1M": 2592000,
    "1Y": 31536000,
  };
  return map[id] ?? Number.MAX_SAFE_INTEGER;
}

export default CryptoMultiTimeframePanel;
