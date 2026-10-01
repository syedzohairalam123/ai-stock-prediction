/**
 * Phase 22A — OHLCV candlestick chart with volume.
 *
 * The REST history is the authoritative series; a live candle tail from the
 * WebSocket gateway is merged on top (same timestamp replaces, newer appends),
 * so the current bar forms in real time without inventing a candle (spec §14).
 * The chart never averages or smooths — extrema stay visible.
 */
import { useMemo } from "react";
import Plot from "react-plotly.js";

import type { CryptoCandle } from "../../lib/crypto";
import type { LiveCandle } from "../../store/useCryptoStore";

export interface CryptoCandleChartProps {
  symbol: string;
  name: string;
  timeframeLabel: string;
  candles: CryptoCandle[];
  liveTail: LiveCandle[] | undefined;
  aggregated: boolean;
  downsampled: boolean;
  downsampleNote: string | null;
  loading: boolean;
}

/** Merge authoritative history with a live tail: same timestamp replaces. */
function mergeSeries(candles: CryptoCandle[], tail: LiveCandle[] | undefined): CryptoCandle[] {
  if (!tail || tail.length === 0) return candles;
  const byTime = new Map<number, CryptoCandle>();
  for (const candle of candles) byTime.set(candle.epoch_ms, candle);
  for (const live of tail) {
    const epoch = new Date(live.timestamp).getTime();
    if (!Number.isFinite(epoch)) continue;
    if (live.open == null || live.high == null || live.low == null || live.close == null) continue;
    byTime.set(epoch, {
      timestamp: live.timestamp,
      epoch_ms: epoch,
      open: live.open,
      high: live.high,
      low: live.low,
      close: live.close,
      volume: live.volume ?? 0,
    });
  }
  return Array.from(byTime.values()).sort((a, b) => a.epoch_ms - b.epoch_ms);
}

export function CryptoCandleChart({
  symbol,
  name,
  timeframeLabel,
  candles,
  liveTail,
  aggregated,
  downsampled,
  downsampleNote,
  loading,
}: CryptoCandleChartProps) {
  const merged = useMemo(() => mergeSeries(candles, liveTail), [candles, liveTail]);

  const traces = useMemo(() => {
    // Plotly renders time axes best from ISO strings; the browser converts the
    // UTC instant to the viewer's local timezone for display (spec §13).
    const x = merged.map((c) => c.timestamp);
    return [
      {
        type: "candlestick",
        name: `${symbol} ${timeframeLabel}`,
        x,
        open: merged.map((c) => c.open),
        high: merged.map((c) => c.high),
        low: merged.map((c) => c.low),
        close: merged.map((c) => c.close),
        increasing: { line: { color: "#72BC8F" }, fillcolor: "#72BC8F" },
        decreasing: { line: { color: "#E97366" }, fillcolor: "#E97366" },
        xaxis: "x",
        yaxis: "y",
      },
      {
        type: "bar",
        name: "Volume",
        x,
        y: merged.map((c) => c.volume),
        marker: { color: merged.map((c) => (c.close >= c.open ? "#72BC8F55" : "#E9736655")) },
        xaxis: "x",
        yaxis: "y2",
        hovertemplate: "%{y:,.0f}<extra>volume</extra>",
      },
    ] as never[];
  }, [merged, symbol, timeframeLabel]);

  const last = merged[merged.length - 1];
  const first = merged[0];
  const change =
    first && last && first.open !== 0 ? ((last.close - first.open) / first.open) * 100 : null;

  return (
    <section className="panel crypto-chart-panel">
      <div className="crypto-panel-head">
        <h2>
          OHLCV · {timeframeLabel}
          <span className={`crypto-chip ${aggregated ? "warn" : "native"}`}>
            {aggregated ? "AGGREGATED" : "NATIVE"}
          </span>
        </h2>
        <div className="crypto-chart-meta">
          <span>{merged.length.toLocaleString()} candles</span>
          {change != null && (
            <span className={change >= 0 ? "pos" : "neg"}>
              {change >= 0 ? "+" : ""}
              {change.toFixed(2)}% over window
            </span>
          )}
          {downsampled && <span className="dim" title={downsampleNote ?? undefined}>downsampled</span>}
        </div>
      </div>

      {loading && merged.length === 0 && (
        <div className="skeleton" style={{ height: 460 }} aria-busy="true" />
      )}

      {!loading && merged.length === 0 && (
        <div className="crypto-empty" role="status">
          <strong>No candles for {symbol} at {timeframeLabel}</strong>
          <span>The provider returned no data for this timeframe. Try another timeframe or asset.</span>
        </div>
      )}

      {merged.length > 0 && (
        <Plot
          data={traces}
          layout={
            {
              uirevision: `${symbol}:${timeframeLabel}`,
              dragmode: "pan",
              paper_bgcolor: "transparent",
              plot_bgcolor: "transparent",
              font: { color: "#e6edf7", size: 11 },
              margin: { t: 12, l: 58, r: 16, b: 34 },
              showlegend: false,
              xaxis: {
                gridcolor: "#26345855",
                rangeslider: { visible: false },
                type: "date",
              },
              yaxis: {
                title: { text: "Price", font: { size: 11 } },
                gridcolor: "#26345855",
                domain: [0.28, 1],
              },
              yaxis2: {
                title: { text: "Volume", font: { size: 10 } },
                gridcolor: "#26345833",
                domain: [0, 0.22],
                showgrid: false,
              },
              hovermode: "x unified",
            } as never
          }
          config={{ responsive: true, displaylogo: false, scrollZoom: true }}
          style={{ width: "100%", height: 520 }}
          useResizeHandler
        />
      )}
    </section>
  );
}

export default CryptoCandleChart;
