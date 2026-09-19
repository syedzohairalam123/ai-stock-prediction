/**
 * Phase 11 — the chart workspace (spec §3, §28).
 *
 * Owns the layout decision only. Panels are independent; this shell decides how
 * many of them are on screen and how they are arranged:
 *
 *   desktop single   one full-width panel (the active one)
 *   desktop split    Chart A above Chart B, each ~50% tall
 *   tablet           the same stack, which already reads as "stacked charts"
 *   mobile           exactly one panel at a time + an explicit chart switcher
 *
 * The layout choice is persisted, but mobile is stronger than the setting: a
 * 390px-wide viewport never gets two squeezed plots.
 */
import { ChartSpline, Info, LayoutGrid, RotateCcw, Rows2, Smartphone } from "lucide-react";
import { useState } from "react";
import { useIsMobileChart, useIsTabletChart } from "../../hooks/useMediaQuery";
import { CHART_IDS } from "../../lib/charting/defaults";
import { useChartStore } from "../../store/useChartStore";
import ChartPanel from "./ChartPanel";

const LABELS: Record<string, string> = { "chart-a": "Chart A", "chart-b": "Chart B" };

export default function ChartWorkspace() {
  const layout = useChartStore((s) => s.layout);
  const activeId = useChartStore((s) => s.activeId);
  const setLayout = useChartStore((s) => s.setLayout);
  const setActive = useChartStore((s) => s.setActiveChart);
  const resetWorkspace = useChartStore((s) => s.resetWorkspace);
  // The `charts` array is a stable reference between store writes (never build a
  // fresh array inside a zustand selector — the snapshot would never be equal).
  const charts = useChartStore((s) => s.charts);

  const isMobile = useIsMobileChart();
  const isTablet = useIsTabletChart();
  const [showHelp, setShowHelp] = useState(false);

  const panels = isMobile ? [activeId] : layout === "split" ? [...CHART_IDS] : [activeId];
  const symbolChips = charts.map((c) => `${LABELS[c.id] ?? c.id} · ${c.symbol} ${c.timeframe}`);

  return (
    <div className={`chart-workspace${isMobile ? " mobile" : layout === "split" ? " split" : " single"}`}>
      <div className="chart-workspace-bar">
        <div className="chart-workspace-title">
          <ChartSpline size={16} />
          <span>Technical analysis workspace</span>
        </div>

        {isMobile ? (
          <div className="chart-switcher" role="group" aria-label="Active chart">
            <Smartphone size={13} aria-hidden="true" />
            {CHART_IDS.map((id) => (
              <button
                key={id}
                type="button"
                className={id === activeId ? "on" : ""}
                onClick={() => setActive(id)}
                aria-pressed={id === activeId}
                title={`Show ${LABELS[id]}`}
              >
                {LABELS[id]}
              </button>
            ))}
          </div>
        ) : (
          <div className="chart-layout-switch" role="group" aria-label="Workspace layout">
            <button
              type="button"
              className={layout === "single" ? "on" : ""}
              onClick={() => setLayout("single")}
              aria-pressed={layout === "single"}
              title="One chart at a time"
            >
              <LayoutGrid size={14} />
              Single
            </button>
            <button
              type="button"
              className={layout === "split" ? "on" : ""}
              onClick={() => setLayout("split")}
              aria-pressed={layout === "split"}
              title="Chart A above Chart B"
            >
              <Rows2 size={14} />
              Split
            </button>
          </div>
        )}

        <div className="chart-workspace-meta" title="Each panel keeps its own symbol, timeframe and annotations">
          {symbolChips.map((entry) => (
            <span key={entry} className="chart-meta-chip ghost">
              {entry}
            </span>
          ))}
        </div>

        <button
          type="button"
          className="chart-icon-btn"
          onClick={() => setShowHelp((v) => !v)}
          aria-expanded={showHelp}
          aria-label="Chart workspace help"
          title="How to use the workspace"
        >
          <Info size={15} />
        </button>
        <button
          type="button"
          className="chart-icon-btn"
          onClick={() => {
            if (window.confirm("Reset both charts to defaults? Drawings and price levels will be cleared.")) {
              resetWorkspace();
            }
          }}
          aria-label="Reset the workspace"
          title="Reset both charts, drawings and price levels"
        >
          <RotateCcw size={15} />
        </button>
      </div>

      {showHelp && (
        <div className="chart-workspace-help">
          <p>
            <b>Pan & zoom</b> — drag the plot to pan, scroll to zoom, and use <b>Reset view</b> in the settings menu to
            re-fit.
          </p>
          <p>
            <b>Drawings</b> — pick a tool, click once for the first anchor and once more to finish. In{" "}
            <b>Select</b> mode drag a shape to move it or its handles to reshape it.
          </p>
          <p>
            <b>Price levels</b> — arm a level tool, then click the chart (or use “place at last price”). Drag a level
            line to fine-tune it.
          </p>
          <p>
            <b>Each panel is independent</b> — symbol, timeframe, chart style, indicators, drawings and price levels
            are stored per chart and persisted for your next visit.
          </p>
        </div>
      )}

      {isTablet && layout === "split" && (
        <p className="chart-workspace-note">Tablet layout: the two charts are stacked vertically.</p>
      )}

      <div className={`chart-grid${panels.length > 1 ? " two" : ""}`}>
        {panels.map((id) => (
          <ChartPanel key={id} id={id} label={LABELS[id] ?? id} isSplit={panels.length > 1} />
        ))}
      </div>
    </div>
  );
}
