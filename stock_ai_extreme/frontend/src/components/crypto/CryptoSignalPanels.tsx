/**
 * Phase 22C — micro-trend card, volatility card and the micro-trend timeline.
 *
 * Every figure is derived from the Phase 22B engines for the *selected*
 * timeframe (spec §5/§6/§7). A metric the data cannot support is omitted, never
 * shown as 0. Trend direction is conveyed with an arrow glyph + word + tone, so
 * it does not depend on colour alone (spec §27).
 */
import { useMemo } from "react";
import Plot from "react-plotly.js";

import type { AnalyticsResponse, CryptoCandle } from "../../lib/crypto";
import {
  formatPercent,
  formatPercentPlain,
  formatPrice,
  NA,
  statusTone,
} from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoSkeleton, CryptoStat, CryptoWidgetError } from "./CryptoStates";

const TREND_ARROW: Record<string, string> = {
  UP: "▲",
  DOWN: "▼",
  SIDEWAYS: "▬",
  INSUFFICIENT_DATA: "—",
};

const REGIME_TONE: Record<string, "pos" | "neg" | "warn" | "mut"> = {
  LOW: "mut",
  NORMAL: "mut",
  HIGH: "warn",
  EXTREME: "neg",
  INSUFFICIENT_DATA: "mut",
};

function trendTone(direction: string | null | undefined): "pos" | "neg" | "mut" {
  if (direction === "UP") return "pos";
  if (direction === "DOWN") return "neg";
  return "mut";
}

export interface MicroTrendCardProps {
  analytics: AnalyticsResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function CryptoMicroTrendCard({ analytics, loading, error, onRetry }: MicroTrendCardProps) {
  const trend = analytics?.trend;

  return (
    <CryptoPanel
      title="Micro trend"
      badge={
        analytics ? (
          <span className={`freshness ${statusTone(analytics.data_status)}`}>{analytics.data_status}</span>
        ) : undefined
      }
      className="crypto-trend-panel"
    >
      {loading && !analytics && <CryptoSkeleton height={140} label="Loading micro trend" />}
      {error && <CryptoWidgetError title="MICRO TREND UNAVAILABLE" message={error} onRetry={onRetry} />}
      {!loading && !error && !analytics && (
        <CryptoEmpty reason="No analytics were returned for this symbol and timeframe." />
      )}

      {analytics && trend && (
        <>
          <div className="crypto-trend-dir-row">
            <span className={`crypto-trend-dir ${trendTone(trend.direction)}`} role="status">
              <span aria-hidden>{TREND_ARROW[trend.direction] ?? "—"}</span>
              {trend.direction}
            </span>
            <span className="crypto-chip">{analytics.timeframe_label}</span>
          </div>
          <div className="crypto-stat-grid compact">
            <CryptoStat label="Strength" value={`${(trend.strength * 100).toFixed(0)}%`} title="Blended factor strength (0–100%)" />
            <CryptoStat label="Confidence" value={`${(trend.confidence * 100).toFixed(0)}%`} title="Sample adequacy × factor agreement — not a probability of the future" />
            <CryptoStat
              label="Recent return"
              value={formatPercent(trend.recent_return ?? null)}
              tone={trendTone((trend.recent_return ?? 0) >= 0 ? "UP" : "DOWN")}
            />
            <CryptoStat
              label="Volatility"
              value={analytics.volatility?.regime ?? NA}
              sub={
                analytics.volatility?.realized_volatility != null
                  ? `${(analytics.volatility.realized_volatility * 100).toFixed(2)}% annualised`
                  : undefined
              }
            />
            <CryptoStat label="Data quality" value={analytics.quality?.label ?? NA} />
            <CryptoStat label="Sample size" value={analytics.sample_size ? String(analytics.sample_size) : NA} />
          </div>
        </>
      )}
    </CryptoPanel>
  );
}

export interface VolatilityCardProps {
  analytics: AnalyticsResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function CryptoVolatilityCard({ analytics, loading, error, onRetry }: VolatilityCardProps) {
  const vol = analytics?.volatility;
  const percentile = vol?.volatility_percentile ?? null;

  return (
    <CryptoPanel
      title="Volatility"
      badge={
        vol ? (
          <span className={`crypto-chip ${vol.regime === "EXTREME" ? "danger" : vol.regime === "HIGH" ? "warn" : "native"}`}>
            {vol.regime}
          </span>
        ) : undefined
      }
      className="crypto-vol-panel"
    >
      {loading && !analytics && <CryptoSkeleton height={140} label="Loading volatility" />}
      {error && <CryptoWidgetError title="VOLATILITY UNAVAILABLE" message={error} onRetry={onRetry} />}
      {!loading && !error && !vol && (
        <CryptoEmpty reason="No volatility snapshot was returned for this timeframe." />
      )}

      {vol && (
        <>
          <div className="crypto-stat-grid compact">
            <CryptoStat
              label="Current volatility"
              value={
                vol.realized_volatility != null
                  ? `${(vol.realized_volatility * 100).toFixed(2)}%`
                  : NA
              }
              sub="annualised realised"
            />
            <CryptoStat
              label="Historical percentile"
              value={percentile != null ? `${percentile.toFixed(0)}${ordinalSuffix(percentile)}` : NA}
              sub="vs the asset's own history"
              title="Percentile of the latest realised volatility within the asset's own rolling distribution"
            />
            <CryptoStat
              label="ATR"
              value={vol.atr != null ? formatPrice(vol.atr) : NA}
              sub={vol.atr_percent != null ? `${formatPercentPlain(vol.atr_percent)} of close` : undefined}
            />
            <CryptoStat
              label="Rolling std"
              value={vol.rolling_std != null ? vol.rolling_std.toFixed(6) : NA}
              sub={vol.window ? `${vol.window}-bar window` : undefined}
            />
            <CryptoStat
              label="Range volatility"
              value={vol.range_volatility != null ? formatPercentPlain(vol.range_volatility * 100) : NA}
              sub="mean (H−L)/close"
            />
            <CryptoStat label="Samples" value={vol.sample_size ? String(vol.sample_size) : NA} />
          </div>
          {vol.regime === "INSUFFICIENT_DATA" && (
            <p className="crypto-note">
              Not enough history to place this reading in the asset's own distribution — the regime is
              reported as insufficient rather than guessed.
            </p>
          )}
        </>
      )}
    </CryptoPanel>
  );
}

export interface MicroTrendChartProps {
  candles: CryptoCandle[];
  timeframeLabel: string;
  trendDirection: string | null | undefined;
  volatilityRegime: string | null | undefined;
  loading: boolean;
}

/**
 * Compact visual timeline of real price observations. The line is the actual
 * close series; hover shows the real timestamp and price, and the card states
 * the current trend/volatility read so the tooltip context is explicit.
 */
export function CryptoMicroTrendChart({
  candles,
  timeframeLabel,
  trendDirection,
  volatilityRegime,
  loading,
}: MicroTrendChartProps) {
  // Keep the timeline compact: the most recent 120 observations.
  const points = useMemo(() => candles.slice(-120), [candles]);
  const traces = useMemo(
    () => [
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Close",
        x: points.map((c) => c.timestamp),
        y: points.map((c) => c.close),
        line: { color: "#5E9FE8", width: 1.6 },
        marker: {
          size: points.map((c) => (c.close >= c.open ? 5 : 5)),
          color: points.map((c) => (c.close >= c.open ? "#72BC8F" : "#E97366")),
        },
        customdata: points.map((c) => [c.open, c.high, c.low, c.volume]),
        hovertemplate:
          "<b>%{x}</b><br>Close %{y}<br>O %{customdata[0]} · H %{customdata[1]} · L %{customdata[2]}<br>Vol %{customdata[3]:,.0f}<extra></extra>",
      },
    ] as never[],
    [points]
  );

  return (
    <CryptoPanel
      title={`Micro-trend timeline · ${timeframeLabel}`}
      badge={
        <span className="crypto-chip">
          {TREND_ARROW[trendDirection ?? ""] ?? "—"} {trendDirection ?? "INSUFFICIENT_DATA"}
          {volatilityRegime ? ` · ${volatilityRegime}` : ""}
        </span>
      }
      className="crypto-trend-chart"
    >
      {loading && points.length === 0 && <CryptoSkeleton height={220} label="Loading trend timeline" />}
      {!loading && points.length === 0 && (
        <CryptoEmpty reason="No candle observations are available for this timeframe." />
      )}
      {points.length > 0 && (
        <Plot
          data={traces}
          layout={
            {
              height: 240,
              margin: { t: 6, l: 44, r: 10, b: 26 },
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#e6edf7", size: 10 },
              showlegend: false,
              xaxis: { gridcolor: "#26345833", type: "date" },
              yaxis: { gridcolor: "#26345833", title: { text: "Price", font: { size: 10 } } },
              hovermode: "closest",
            } as never
          }
          config={{ responsive: true, displaylogo: false }}
          style={{ width: "100%", height: 240 }}
          useResizeHandler
        />
      )}
    </CryptoPanel>
  );
}

function ordinalSuffix(value: number): string {
  const rounded = Math.round(value);
  const mod100 = rounded % 100;
  if (mod100 >= 11 && mod100 <= 13) return "th";
  switch (rounded % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
}

/** Re-exported tone helpers so panels stay consistent. */
export { trendTone, REGIME_TONE };
