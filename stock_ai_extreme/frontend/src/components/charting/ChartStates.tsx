/**
 * Phase 11 — chart panel states (spec §29).
 *
 * A chart is never allowed to be an unexplained blank rectangle. Each failure
 * mode reports what happened and what to do next:
 *
 *   loading          → a sized skeleton (so the layout does not jump)
 *   invalid symbol   → the reason + one-click working symbols
 *   no bars          → the window that came back empty
 *   fetch failure    → the error + retry
 *   render guard     → the panel catches its own render errors
 */
import { AlertTriangle, RefreshCw, SearchX } from "lucide-react";
import type { Candle } from "../../lib/charting/types";

interface ChartStateProps {
  kind: "loading" | "invalid" | "empty" | "error";
  title: string;
  message?: string;
  suggestions?: { symbol: string; entityType: "STOCK" | "INDEX" }[];
  onPickSymbol?: (symbol: string, entityType: "STOCK" | "INDEX") => void;
  onRetry?: () => void;
}

export default function ChartState({ kind, title, message, suggestions, onPickSymbol, onRetry }: ChartStateProps) {
  return (
    <div className={`chart-state chart-state-${kind}`} role={kind === "error" || kind === "invalid" ? "alert" : "status"}>
      {kind === "error" || kind === "invalid" ? <AlertTriangle size={18} /> : <SearchX size={18} />}
      <div className="chart-state-body">
        <strong>{title}</strong>
        {message && <span>{message}</span>}
      </div>
      {onRetry && (
        <button type="button" className="chart-btn" onClick={onRetry}>
          <RefreshCw size={13} />
          <span className="chart-btn-label">Retry</span>
        </button>
      )}
      {suggestions && suggestions.length > 0 && onPickSymbol && (
        <div className="chart-state-suggest">
          <span>Try</span>
          {suggestions.map((s) => (
            <button
              key={s.symbol}
              type="button"
              className="chart-chip"
              onClick={() => onPickSymbol(s.symbol, s.entityType)}
              title={s.entityType === "INDEX" ? "PSX index" : "PSX stock"}
            >
              {s.symbol}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Loading placeholder that reserves the plot's height. */
export function ChartSkeleton({ bars = 48 }: { bars?: number }) {
  return (
    <div className="chart-skeleton" role="status" aria-label="Loading chart data">
      <div className="chart-skeleton-bars" aria-hidden="true">
        {Array.from({ length: bars }).map((_, index) => (
          <span key={index} style={{ height: `${24 + ((index * 37) % 56)}%` }} />
        ))}
      </div>
      <span className="chart-skeleton-label">Loading candles…</span>
    </div>
  );
}

/**
 * "Empty dataset" copy that states the window and the reason, rather than
 * pretending the chart is fine.
 */
export function describeEmpty(window: string, symbol: string, points: Candle[]): { title: string; message: string } {
  return {
    title: `No bars for ${symbol} on ${window}`,
    message: points.length
      ? `${points.length} bar${points.length === 1 ? "" : "s"} remained after validation — not enough to plot a candle.`
      : "The provider returned no candles for this window. Try another timeframe or symbol.",
  };
}
