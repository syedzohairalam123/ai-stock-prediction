/**
 * Phase 11 — chart HUD: crosshair readout + indicator legend (spec §22, §23).
 *
 * Floating, non-interactive overlay in the plot's top-left corner. It follows the
 * hovered candle and falls back to the latest bar when the pointer leaves, so the
 * panel always reports a concrete reading rather than going blank.
 *
 * Values come from the already-computed, memoized indicator lines — the HUD does
 * no maths of its own, so sweeping the crosshair across 5,000 bars costs nothing.
 */
import { useMemo } from "react";
import type { Candle, ChartInstance } from "../../lib/charting/types";
import { lineValueAt, type IndicatorLine } from "../../lib/charting/indicators";
import type { PlotTransform } from "../../lib/charting/geometry";
import { formatCompactNumber, formatValue } from "../../lib/charting/plotModel";

interface ChartHudProps {
  instance: ChartInstance;
  points: Candle[];
  lines: IndicatorLine[];
  transform: PlotTransform | null;
  hoverIndex: number | null;
  showLegend: boolean;
}

interface LegendEntry {
  indicatorId: string;
  label: string;
  color: string;
  parts: { role: string; value: number | null }[];
}

/** `"BB 20 / 2 upper"` → `"BB 20 / 2"`. */
function baseLabel(label: string): string {
  return label.replace(/ (upper|mid|lower)$/, "");
}

function formatStamp(timestamp: number, intraday: boolean): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(intraday ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export default function ChartHud({ instance, points, lines, transform, hoverIndex, showLegend }: ChartHudProps) {
  const index = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < points.length ? hoverIndex : points.length - 1;
  const candle = index >= 0 ? points[index] : null;
  const intraday = instance.timeframe === "1D" || instance.timeframe === "7D";

  const legend = useMemo<LegendEntry[]>(() => {
    const grouped = new Map<string, LegendEntry>();
    for (const line of lines) {
      const entry =
        grouped.get(line.indicatorId) ??
        ({ indicatorId: line.indicatorId, label: baseLabel(line.label), color: line.color, parts: [] } as LegendEntry);
      entry.parts.push({ role: line.role, value: lineValueAt(line, index) });
      grouped.set(line.indicatorId, entry);
    }
    return Array.from(grouped.values());
  }, [lines, index]);

  if (!candle) return null;

  const up = candle.close >= candle.open;
  const previous = index > 0 ? points[index - 1].close : null;
  const change = previous !== null ? candle.close - previous : null;
  const changePct = previous !== null && previous !== 0 ? (change! / previous) * 100 : null;

  return (
    <div
      className="chart-hud"
      style={{
        left: transform ? Math.round(transform.rect.left) + 10 : 74,
        top: transform ? Math.round(transform.rect.top) + 8 : 20,
      }}
      aria-live="off"
    >
      <div className="chart-hud-head">
        <b>{instance.symbol}</b>
        <span className="chart-hud-sep">·</span>
        <span>{instance.timeframe}</span>
        <span className="chart-hud-sep">·</span>
        <span className="chart-hud-stamp">{formatStamp(candle.timestamp, intraday)}</span>
        <span className="chart-hud-sep">·</span>
        <span className="chart-hud-count">
          bar {index + 1}/{points.length}
        </span>
        {hoverIndex === null && <span className="chart-hud-latest">latest</span>}
      </div>

      <div className="chart-hud-ohlc">
        <span>
          O <b className="num">{formatValue(candle.open)}</b>
        </span>
        <span>
          H <b className="num">{formatValue(candle.high)}</b>
        </span>
        <span>
          L <b className="num">{formatValue(candle.low)}</b>
        </span>
        <span>
          C{" "}
          <b className={`num ${up ? "up" : "dn"}`}>{formatValue(candle.close)}</b>
        </span>
        <span>
          V <b className="num">{candle.hasVolume ? formatCompactNumber(candle.volume) : "n/a"}</b>
        </span>
        {change !== null && changePct !== null && (
          <span className={change >= 0 ? "up" : "dn"}>
            {change >= 0 ? "▲" : "▼"} <b className="num">{formatValue(Math.abs(change))}</b>{" "}
            <b className="num">({Math.abs(changePct).toFixed(2)}%)</b>
          </span>
        )}
      </div>

      {showLegend && legend.length > 0 && (
        <div className="chart-hud-legend">
          {legend.map((entry) => {
            const missing = entry.parts.every((part) => part.value === null);
            return (
              <div key={entry.indicatorId} className="chart-hud-legend-row">
                <span className="chart-hud-swatch" style={{ background: entry.color }} aria-hidden="true" />
                <span className="chart-hud-legend-label">{entry.label}</span>
                {missing ? (
                  <span className="chart-hud-legend-missing" title="Not enough history for this indicator yet">
                    insufficient history
                  </span>
                ) : (
                  <span className="chart-hud-legend-values num">
                    {entry.parts
                      .filter((part) => part.role !== "upper" && part.role !== "lower")
                      .map((part) => formatValue(part.value))
                      .join("  ·  ")}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
