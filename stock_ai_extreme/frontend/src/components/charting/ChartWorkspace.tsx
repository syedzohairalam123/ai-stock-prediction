/**
 * Phase 11 — the chart workspace (spec §3, §28).
 *
 * Owns the layout decision only. Panels are independent; this shell decides how
 * many of them are on screen and how they are arranged:
 *
 *   desktop single   one full-width panel (the active one)
 *   desktop split    every open panel stacked in one column (A above B, …)
 *   desktop grid     every open panel in a multi-column grid
 *   tablet           stacked, which already reads as "charts", never a squeezed grid
 *   mobile           exactly one panel at a time + an explicit chart switcher
 *
 * The two seed panels (`chart-a` / `chart-b`) keep their original behaviour, so
 * a workspace saved before the grid existed restores exactly as it was. Panels
 * beyond those are opened from the bar and continue the alphabet (`chart-c` …).
 *
 * The layout choice is persisted, but mobile is stronger than the setting: a
 * 390px-wide viewport never gets squeezed plots.
 */
import { ChartSpline, GripVertical, Info, LayoutGrid, Link2, Plus, RotateCcw, Rows2, Smartphone, X } from "lucide-react";
import { useState, type CSSProperties, type DragEvent, type KeyboardEvent } from "react";
import { useIsMobileChart, useIsTabletChart } from "../../hooks/useMediaQuery";
import { GRID_COLUMN_OPTIONS } from "../../lib/charting/types";
import { chartLabel, nextPanelId } from "../../lib/charting/defaults";
import { isPanelLinked, useChartStore } from "../../store/useChartStore";
import ChartPanel from "./ChartPanel";

export default function ChartWorkspace() {
  const layout = useChartStore((s) => s.layout);
  const gridColumns = useChartStore((s) => s.gridColumns);
  const activeId = useChartStore((s) => s.activeId);
  const setLayout = useChartStore((s) => s.setLayout);
  const setGridColumns = useChartStore((s) => s.setGridColumns);
  const setActive = useChartStore((s) => s.setActiveChart);
  const addChart = useChartStore((s) => s.addChart);
  const removeChart = useChartStore((s) => s.removeChart);
  const moveChart = useChartStore((s) => s.moveChart);
  const resetWorkspace = useChartStore((s) => s.resetWorkspace);
  // The `charts` array is a stable reference between store writes (never build a
  // fresh array inside a zustand selector — the snapshot would never be equal).
  const charts = useChartStore((s) => s.charts);
  const linkEnabled = useChartStore((s) => s.linkEnabled);
  const linkGroup = useChartStore((s) => s.linkGroup);
  const panelLinked = useChartStore((s) => s.panelLinked);

  const isMobile = useIsMobileChart();
  const isTablet = useIsTabletChart();
  const [showHelp, setShowHelp] = useState(false);

  // Mobile and single show the active panel only; split and grid show them all.
  const panels = isMobile || layout === "single" ? [activeId] : charts.map((c) => c.id);
  const nextId = nextPanelId(charts);
  const gridMode = !isMobile && layout === "grid";
  // Never open an empty column: a 3-column grid with two panels reads as a bug.
  const columns = Math.max(1, Math.min(gridColumns, panels.length));

  const symbolChips = charts.map((c) => `${chartLabel(c.id)} · ${c.symbol} ${c.timeframe}`);
  // A compact read-out of the link group: which properties sync, and how many
  // panels are actually following.
  const linkedCount = charts.filter((c) => isPanelLinked({ panelLinked }, c.id)).length;
  const linkProps = (["symbol", "timeframe", "crosshair"] as const).filter((p) => linkGroup[p]);

  // -- drag-to-reorder ------------------------------------------------------
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  // Only worth offering when more than one panel is actually on screen.
  const reorderable = !isMobile && layout !== "single" && panels.length > 1;

  const endDrag = () => {
    setDragId(null);
    setOverId(null);
  };

  /** Drop lands the dragged panel on whichever side of the target it was over. */
  const handleDrop = (targetId: string) => (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const fromId = dragId ?? event.dataTransfer.getData("text/plain");
    const rect = event.currentTarget.getBoundingClientRect();
    const after = gridMode
      ? event.clientX - rect.left > rect.width / 2
      : event.clientY - rect.top > rect.height / 2;
    endDrag();
    if (!fromId || fromId === targetId) return;
    moveChart(fromId, targetId, after ? "after" : "before");
  };

  /** Keyboard parity for the grip: arrow keys move the panel one slot. */
  const handleHandleKey = (event: KeyboardEvent<HTMLButtonElement>, id: string) => {
    const delta =
      event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? -1
        : event.key === "ArrowRight" || event.key === "ArrowDown"
          ? 1
          : 0;
    if (!delta) return;
    const index = panels.indexOf(id);
    const targetId = index === -1 ? undefined : panels[index + delta];
    if (!targetId) return;
    event.preventDefault();
    moveChart(id, targetId, delta < 0 ? "before" : "after");
  };

  const handleAddPanel = () => {
    const id = addChart();
    if (!id) return;
    // The whole point of adding a panel is seeing it, so switch out of `single`.
    setLayout("grid");
    setActive(id);
  };

  const gridClass =
    `chart-grid${panels.length > 1 ? " two" : ""}${panels.length > 2 ? " many" : ""}${gridMode ? " grid" : ""}`;

  return (
    <div className={`chart-workspace${isMobile ? " mobile" : ` ${layout}`}`}>
      <div className="chart-workspace-bar">
        <div className="chart-workspace-title">
          <ChartSpline size={16} />
          <span>Technical analysis workspace</span>
        </div>

        {isMobile ? (
          <div className="chart-switcher" role="group" aria-label="Active chart">
            <Smartphone size={13} aria-hidden="true" />
            {charts.map((c) => (
              <button
                key={c.id}
                type="button"
                className={c.id === activeId ? "on" : ""}
                onClick={() => setActive(c.id)}
                aria-pressed={c.id === activeId}
                title={`Show ${chartLabel(c.id)}`}
              >
                {chartLabel(c.id)}
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
              title={charts.length > 2 ? "All panels stacked vertically" : "Chart A above Chart B"}
            >
              <Rows2 size={14} />
              Split
            </button>
            {charts.length > 1 && (
              <button
                type="button"
                className={layout === "grid" ? "on" : ""}
                onClick={() => setLayout("grid")}
                aria-pressed={layout === "grid"}
                title={`All ${charts.length} panels in a grid`}
              >
                <LayoutGrid size={14} />
                Grid
              </button>
            )}
          </div>
        )}

        {gridMode && panels.length > 2 && (
          <div className="chart-col-switch" role="group" aria-label="Grid columns">
            {GRID_COLUMN_OPTIONS.filter((n) => n > 1).map((n) => (
              <button
                key={n}
                type="button"
                className={gridColumns === n ? "on" : ""}
                onClick={() => setGridColumns(n)}
                aria-pressed={gridColumns === n}
                title={`${n} columns`}
              >
                {n}
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          className="chart-bar-add"
          onClick={handleAddPanel}
          disabled={!nextId}
          title={nextId ? `Open another chart panel (${chartLabel(nextId)})` : "Panel limit reached"}
        >
          <Plus size={14} />
          <span className="chart-btn-label">Add panel</span>
        </button>

        {linkEnabled && (
          <span
            className="chart-meta-chip link"
            title={`Linked: ${linkProps.join(", ") || "nothing"} · ${linkedCount} of ${charts.length} panels in the group`}
          >
            <Link2 size={12} aria-hidden="true" />
            {linkedCount}/{charts.length}
          </span>
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
            if (window.confirm("Reset the workspace? Every panel, drawing and price level will be cleared.")) {
              resetWorkspace();
            }
          }}
          aria-label="Reset the workspace"
          title="Reset every panel, drawing and price level"
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
            <b>Drawings</b> — pick a tool, click once for the first anchor and once more to finish. In <b>Select</b>{" "}
            mode drag a shape to move it or its handles to reshape it.
          </p>
          <p>
            <b>Price levels</b> — arm a level tool, then click the chart (or use “place at last price”). Drag a level
            line to fine-tune it.
          </p>
          <p>
            <b>Each panel is independent</b> — symbol, timeframe, chart style, indicators, drawings and price levels
            are stored per chart and persisted for your next visit.
          </p>
          <p>
            <b>Panels</b> — use <b>Add panel</b> to open more charts, then pick <b>Split</b> for a stack or <b>Grid</b> to
            arrange them in columns. Drag the <b>⠿</b> grip on a panel’s meta strip to reorder it (arrow keys work too),
            and the <b>×</b> closes it.
          </p>
          <p>
            <b>Cross-panel linking</b> — open the <b>Link</b> menu in any toolbar to sync symbol, timeframe and/or
            crosshair across the panels you choose. Every panel has its own toggle, so one can follow the group while
            another stays put.
          </p>
        </div>
      )}

      {isTablet && layout !== "single" && (
        <p className="chart-workspace-note">
          Tablet layout: panels are stacked vertically rather than squeezed into columns.
        </p>
      )}

      <div className={gridClass} style={gridMode ? ({ "--chart-cols": columns } as CSSProperties) : undefined}>
        {panels.map((id) => (
          <div
            key={id}
            className={`chart-grid-cell${dragId === id ? " dragging" : ""}${
              dragId && overId === id && dragId !== id ? " drag-over" : ""
            }`}
            onDragOver={
              reorderable
                ? (event) => {
                    event.preventDefault();
                    event.dataTransfer.dropEffect = "move";
                    setOverId((current) => (current === id ? current : id));
                  }
                : undefined
            }
            onDragLeave={reorderable ? () => setOverId((current) => (current === id ? null : current)) : undefined}
            onDrop={reorderable ? handleDrop(id) : undefined}
          >
            <ChartPanel
              id={id}
              label={chartLabel(id)}
              isSplit={panels.length > 1}
              onClose={charts.length > 1 ? () => removeChart(id) : undefined}
              dragHandle={
                reorderable ? (
                  <button
                    type="button"
                    className="chart-panel-drag"
                    draggable
                    onDragStart={(event) => {
                      setDragId(id);
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", id);
                    }}
                    onDragEnd={endDrag}
                    onKeyDown={(event) => handleHandleKey(event, id)}
                    aria-label={`Reorder ${chartLabel(id)}`}
                    title="Drag to reorder · arrow keys also move this panel"
                  >
                    <GripVertical size={13} />
                  </button>
                ) : undefined
              }
            />
          </div>
        ))}
      </div>

      {panels.length > 1 && (
        <p className="chart-workspace-footer">
          <span>
            {panels.length} panels open
            {gridMode ? ` · ${columns} column${columns > 1 ? "s" : ""}` : ""}
          </span>
          <button type="button" onClick={() => setLayout("single")}>
            <X size={12} /> Show one
          </button>
        </p>
      )}
    </div>
  );
}
