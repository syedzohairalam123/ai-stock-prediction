/**
 * Phase 12 — Chart widget (spec §3, §4 NEW_CHART).
 *
 * A *single-panel instance* of the Phase-11 charting engine — the real
 * `ChartPanel` with its full toolbar, indicators, drawings and price levels —
 * not a rebuilt or reduced chart. Each widget instance keeps its own chart
 * state through the Phase-11 store's per-chart ids: the widget's `settings`
 * map to a unique chart id (`chart-<widgetId>`), so multiple chart widgets
 * stay independent and persist with the workspace.
 */
import { useMemo } from "react";
import ChartPanel from "../../charting/ChartPanel";

interface ChartWidgetProps {
  widgetId: string;
  settings?: Record<string, unknown>;
  onSettingsChange?: (patch: Record<string, unknown>) => void;
}

export default function ChartWidget({ widgetId, settings }: ChartWidgetProps) {
  // One Phase-11 chart id per widget instance. The Phase-11 store persists
  // per-chart state (symbol/timeframe/indicators/drawings/levels) under this
  // id, so two chart widgets never collide and survive reloads.
  const chartId = useMemo(() => `chart-${widgetId}`, [widgetId]);

  const symbol = typeof settings?.symbol === "string" ? settings.symbol : "OGDC";
  const timeframe = typeof settings?.timeframe === "string" ? settings.timeframe : "6M";

  return (
    <div className="ws-widget-body ws-chart-widget">
      <ChartPanel id={chartId} label={`Chart · ${symbol} ${timeframe}`} isSplit={false} />
    </div>
  );
}
