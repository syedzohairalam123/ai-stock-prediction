/**
 * Phase 11 — one chart panel (spec §4).
 *
 * Owns exactly one `ChartInstance`: its data query, its indicator computation,
 * its axis window, its annotation commands, its fullscreen state. Two panels
 * never share any of that, which is what makes split mode safe — changing Chart
 * A's symbol or timeframe cannot disturb Chart B, and both can hold the same
 * symbol on different timeframes.
 *
 * Indicator maths is memoized at this level (and again inside the engine), so the
 * hover crosshair — which lives in the plot surface below — never triggers a
 * recalculation (spec §9, §27).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ErrorBoundary } from "react-error-boundary";
import type { IndicatorConfig, IndicatorType, PriceLevel, PriceLevelType, DrawingStyle } from "../../lib/charting/types";
import type { StockRange } from "../../lib/timeframes";
import { computeIndicators } from "../../lib/charting/indicators";
import { defaultRange, fitRangeWithIndicators, resolveInitialRange, type PlotRange } from "../../lib/charting/plotModel";
import { dataQualitySummary, ChartDataError, entityDisplayName, POPULAR_CHART_SYMBOLS } from "../../lib/charting/dataSource";
import { createDrawing } from "../../lib/charting/drawings";
import { useChartDataset } from "../../hooks/useChartData";
import { useChartTheme } from "../../hooks/useChartTheme";
import { useFullscreen } from "../../hooks/useFullscreen";
import { selectChart, useChartStore } from "../../store/useChartStore";
import ChartState, { ChartSkeleton, describeEmpty } from "./ChartStates";
import ChartToolbar, { type PanelDataState } from "./ChartToolbar";
import PlotSurface, { type ChartInteractionController } from "./PlotSurface";

interface ChartPanelProps {
  id: string;
  label: string;
  isSplit: boolean;
}

/** Fallback UI for a panel whose render threw — the other panel keeps working. */
function PanelCrash({ error, resetErrorBoundary }: { error: Error; resetErrorBoundary: () => void }) {
  return (
    <div className="chart-panel-crash">
      <ChartState
        kind="error"
        title="This chart could not be rendered"
        message={error?.message ?? "An unexpected rendering error occurred."}
        onRetry={resetErrorBoundary}
      />
    </div>
  );
}

export default function ChartPanel({ id, label, isSplit }: ChartPanelProps) {
  const instance = useChartStore((s) => selectChart(s, id));
  const activeId = useChartStore((s) => s.activeId);
  const tool = useChartStore((s) => s.tool);
  const priceLevelTool = useChartStore((s) => s.priceLevelTool);
  const selectedId = useChartStore((s) => s.selected[id] ?? null);
  const editStack = useChartStore((s) => s.edits[id]);
  const enabledIndicatorCount = instance.indicators.filter((i) => i.enabled).length;

  const setActiveChart = useChartStore((s) => s.setActiveChart);
  const setSymbol = useChartStore((s) => s.setSymbol);
  const setEntityType = useChartStore((s) => s.setEntityType);
  const setTimeframe = useChartStore((s) => s.setTimeframe);
  const setChartStyle = useChartStore((s) => s.setChartStyle);
  const setVolumeVisible = useChartStore((s) => s.setVolumeVisible);
  const setCrosshairEnabled = useChartStore((s) => s.setCrosshairEnabled);
  const updateSettings = useChartStore((s) => s.updateSettings);
  const setViewport = useChartStore((s) => s.setViewport);
  const resetChart = useChartStore((s) => s.resetChart);
  const toggleIndicator = useChartStore((s) => s.toggleIndicator);
  const updateIndicator = useChartStore((s) => s.updateIndicator);
  const addIndicator = useChartStore((s) => s.addIndicator);
  const removeIndicator = useChartStore((s) => s.removeIndicator);
  const resetIndicators = useChartStore((s) => s.resetIndicators);
  const setTool = useChartStore((s) => s.setTool);
  const setPriceLevelTool = useChartStore((s) => s.setPriceLevelTool);
  const selectDrawing = useChartStore((s) => s.selectDrawing);
  const addDrawing = useChartStore((s) => s.addDrawing);
  const moveDrawing = useChartStore((s) => s.moveDrawing);
  const resizeDrawing = useChartStore((s) => s.resizeDrawing);
  const styleDrawing = useChartStore((s) => s.styleDrawing);
  const setDrawingVisible = useChartStore((s) => s.setDrawingVisible);
  const setDrawingLocked = useChartStore((s) => s.setDrawingLocked);
  const deleteDrawing = useChartStore((s) => s.deleteDrawing);
  const clearDrawings = useChartStore((s) => s.clearDrawings);
  const addPriceLevelAt = useChartStore((s) => s.addPriceLevelAt);
  const updatePriceLevel = useChartStore((s) => s.updatePriceLevel);
  const deletePriceLevel = useChartStore((s) => s.deletePriceLevel);
  const clearPriceLevels = useChartStore((s) => s.clearPriceLevels);
  const undo = useChartStore((s) => s.undo);
  const redo = useChartStore((s) => s.redo);

  const theme = useChartTheme();
  const isActive = activeId === id;
  const fullscreen = useFullscreen<HTMLElement>();

  const query = useChartDataset(instance.symbol, instance.entityType, instance.timeframe);
  const dataset = query.data;
  const points = useMemo(() => dataset?.points ?? [], [dataset]);
  const lastClose = points.length ? points[points.length - 1].close : null;

  // -- indicators (memoized in the engine; recomputed only when they change) --
  const computed = useMemo(
    () =>
      computeIndicators(points, instance.indicators, {
        intraday: dataset?.intraday ?? false,
        datasetKey: `${id}:${dataset?.fitKey ?? instance.symbol}`,
      }),
    [points, instance.indicators, dataset?.intraday, dataset?.fitKey, id, instance.symbol]
  );

  // -- axis window ----------------------------------------------------------
  const [range, setRange] = useState<PlotRange | null>(null);
  const appliedFitKey = useRef<string | null>(null);
  const liveRange = useRef<PlotRange | null>(null);

  useEffect(() => {
    if (!dataset) {
      setRange(null);
      appliedFitKey.current = null;
      return;
    }
    if (appliedFitKey.current === dataset.fitKey) return;
    appliedFitKey.current = dataset.fitKey;
    liveRange.current = null;
    const restored = resolveInitialRange(dataset.points, dataset.fitKey, instance.viewport);
    setRange(restored ?? defaultRange(dataset.points));
    // Intentionally keyed on the dataset identity, not on `instance.viewport`:
    // re-applying a viewport whenever it is persisted would fight the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset?.fitKey, dataset]);

  /**
   * Persist the window the user settled on (debounced upstream). `null` means the
   * axes were reset to the layout default, so the saved viewport is dropped —
   * otherwise a later reload would restore a zoom the analyst had deliberately
   * undone.
   */
  const handleViewportSettled = useCallback(
    (settled: PlotRange | null) => {
      liveRange.current = settled;
      if (!dataset) return;
      setViewport(id, settled ? { xRange: settled.x, yRange: settled.y, fitKey: dataset.fitKey } : null);
    },
    [dataset, id, setViewport]
  );

  const handleResetView = useCallback(() => {
    if (!dataset) return;
    const xRange = liveRange.current?.x ?? range?.x;
    const fitted = xRange
      ? fitRangeWithIndicators(dataset.points, computed.lines, xRange)
      : defaultRange(dataset.points, dataset.points.length);
    if (fitted) {
      setRange(fitted);
      liveRange.current = fitted;
    }
  }, [computed.lines, dataset, range?.x]);

  // -- selection ------------------------------------------------------------
  const selectedDrawing = useMemo(
    () => instance.drawings.find((d) => d.id === selectedId) ?? null,
    [instance.drawings, selectedId]
  );
  const selectedLevel = useMemo(
    () => instance.priceLevels.find((l) => l.id === selectedId) ?? null,
    [instance.priceLevels, selectedId]
  );

  const handleSelect = useCallback((nextId: string | null) => selectDrawing(id, nextId), [id, selectDrawing]);

  /** A nudge that reads as "one meaningful step" on this instrument's scale. */
  const priceStep = useMemo(() => {
    const sample = points.slice(-20);
    if (sample.length === 0) return 0.01;
    const avgRange = sample.reduce((sum, c) => sum + Math.abs(c.high - c.low), 0) / sample.length;
    return Math.max(0.01, avgRange / 4);
  }, [points]);

  const controller = useMemo<ChartInteractionController>(
    () => ({
      tool,
      priceLevelTool,
      selectedId,
      onSelect: handleSelect,
      onCompleteDrawing: (type, from, to) => {
        const drawing = createDrawing(type, [from, to], selectedDrawing?.style);
        addDrawing(id, drawing);
        selectDrawing(id, drawing.id);
        // Back to the neutral cursor so the chart can be panned again.
        setTool("select");
      },
      onToolSettled: () => setTool("select"),
      onMoveDrawing: (drawingId, dt, dp) => moveDrawing(id, drawingId, dt, dp),
      onResizeDrawing: (drawingId, anchor, point) => resizeDrawing(id, drawingId, anchor, point),
      onPlacePriceLevel: (type: PriceLevelType, price: number) => addPriceLevelAt(id, type, price, priceStep),
      onMovePriceLevel: (levelId, price) => updatePriceLevel(id, levelId, { price }),
      onDisarmTool: () => {
        setPriceLevelTool(null);
        setTool("select");
      },
    }),
    [
      addDrawing,
      addPriceLevelAt,
      handleSelect,
      id,
      moveDrawing,
      priceLevelTool,
      priceStep,
      resizeDrawing,
      selectDrawing,
      selectedDrawing?.style,
      selectedId,
      setPriceLevelTool,
      setTool,
      tool,
      updatePriceLevel,
    ]
  );

  // -- delete / clear -------------------------------------------------------
  const handleDeleteSelected = useCallback(() => {
    if (!selectedId) return;
    if (selectedDrawing) deleteDrawing(id, selectedId);
    else if (selectedLevel) deletePriceLevel(id, selectedId);
  }, [deleteDrawing, deletePriceLevel, id, selectedDrawing, selectedId, selectedLevel]);

  useEffect(() => {
    if (!isActive) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (event.key === "Delete" || event.key === "Backspace") {
        if (selectedId) {
          event.preventDefault();
          handleDeleteSelected();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleDeleteSelected, isActive, selectedId]);

  // -- states ---------------------------------------------------------------
  const isLoading = query.isPending || (query.isFetching && !dataset);
  const dataError = query.error;
  const dataState: PanelDataState = isLoading ? "loading" : dataError ? "error" : "ready";

  const errorKind = dataError instanceof ChartDataError ? dataError.code : "FETCH_FAILED";
  const emptyCopy = describeEmpty(instance.timeframe, instance.symbol, points);

  return (
    <section
      ref={fullscreen.ref}
      className={`chart-panel${isActive && isSplit ? " active" : ""}${fullscreen.isFullscreen ? " fs" : ""}${fullscreen.isFallback ? " fs-fallback" : ""}`}
      aria-label={`${label}: ${instance.symbol} ${instance.timeframe}`}
      data-chart-id={id}
      onFocusCapture={() => setActiveChart(id)}
    >
      <ChartToolbar
        instance={instance}
        label={label}
        isActive={isActive}
        isSplit={isSplit}
        entityName={entityDisplayName(instance.symbol, instance.entityType)}
        dataState={dataState}
        unavailable={computed.unavailable}
        controller={{ tool, priceLevelTool, onTool: setTool }}
        selectedDrawing={selectedDrawing}
        selectedLevel={selectedLevel}
        canUndo={(editStack?.past.length ?? 0) > 0}
        canRedo={(editStack?.future.length ?? 0) > 0}
        isFullscreen={fullscreen.isFullscreen}
        lastClose={lastClose}
        onActivate={() => setActiveChart(id)}
        onSymbol={(symbol, entityType) => {
          setSymbol(id, symbol);
          setEntityType(id, entityType);
        }}
        onEntityType={(entityType) => setEntityType(id, entityType)}
        onTimeframe={(timeframe: StockRange) => setTimeframe(id, timeframe)}
        onChartStyle={(style) => setChartStyle(id, style)}
        onToggleVolume={() => setVolumeVisible(id, !instance.volumeVisible)}
        onToggleCrosshair={() => setCrosshairEnabled(id, !instance.crosshairEnabled)}
        onSettings={(patch) => updateSettings(id, patch)}
        onToggleIndicator={(indicatorId) => toggleIndicator(id, indicatorId)}
        onUpdateIndicator={(indicatorId: string, patch: Partial<IndicatorConfig>) => updateIndicator(id, indicatorId, patch)}
        onAddIndicator={(type: IndicatorType, period: number) => addIndicator(id, type, period)}
        onRemoveIndicator={(indicatorId) => removeIndicator(id, indicatorId)}
        onResetIndicators={() => resetIndicators(id)}
        onUndo={() => undo(id)}
        onRedo={() => redo(id)}
        onDeleteSelected={handleDeleteSelected}
        onClearDrawings={() => clearDrawings(id)}
        onStyleDrawing={(patch: Partial<DrawingStyle>) => {
          if (selectedDrawing) styleDrawing(id, selectedDrawing.id, patch);
        }}
        onToggleDrawingVisible={() => {
          if (selectedDrawing) setDrawingVisible(id, selectedDrawing.id, !selectedDrawing.visible);
        }}
        onToggleDrawingLocked={() => {
          if (selectedDrawing) setDrawingLocked(id, selectedDrawing.id, !selectedDrawing.locked);
        }}
        onArmPriceLevel={(type: PriceLevelType | null) => {
          setPriceLevelTool(type);
          if (type) setTool("select");
        }}
        onPlacePriceLevel={(type: PriceLevelType, price: number) => addPriceLevelAt(id, type, price, priceStep)}
        onUpdatePriceLevel={(levelId: string, patch: Partial<PriceLevel>) => updatePriceLevel(id, levelId, patch)}
        onDeletePriceLevel={(levelId) => deletePriceLevel(id, levelId)}
        onClearPriceLevels={() => clearPriceLevels(id)}
        onSelect={handleSelect}
        onResetView={handleResetView}
        onResetChart={() => resetChart(id)}
        onToggleFullscreen={fullscreen.toggle}
      />

      <div className="chart-panel-meta">
        <span className="chart-meta-chip brand">{instance.entityType === "INDEX" ? "INDEX" : "STOCK"}</span>
        <span className="chart-meta-chip">{points.length.toLocaleString("en-US")} bars</span>
        {dataset && (
          <>
            <span className="chart-meta-chip">{dataset.source === "psx-index" ? "PSX index series" : "Market history API"}</span>
            <span className={`chart-meta-chip status-${(dataset.status ?? "unknown").toLowerCase()}`}>
              {dataset.status ?? "—"}
              {dataset.providerSource ? ` · ${dataset.providerSource}` : ""}
            </span>
            {dataQualitySummary(dataset.stats) && (
              <span className="chart-meta-chip warn" title={dataQualitySummary(dataset.stats) ?? ""}>
                data cleaned
              </span>
            )}
          </>
        )}
        <span className="chart-meta-chip ghost">
          {enabledIndicatorCount} of {instance.indicators.length} indicators on
        </span>
        {instance.drawings.length > 0 && <span className="chart-meta-chip ghost">{instance.drawings.length} drawings</span>}
        {instance.priceLevels.length > 0 && <span className="chart-meta-chip ghost">{instance.priceLevels.length} levels</span>}
      </div>

      <ErrorBoundary
        resetKeys={[dataset?.fitKey, instance.chartType, instance.symbol, instance.timeframe]}
        FallbackComponent={({ error, resetErrorBoundary }) => (
          <PanelCrash error={error as Error} resetErrorBoundary={resetErrorBoundary} />
        )}
      >
        {isLoading && <ChartSkeleton />}

        {!isLoading && dataError && (
          <ChartState
            kind={errorKind === "FETCH_FAILED" ? "error" : "invalid"}
            title={
              errorKind === "INVALID_SYMBOL"
                ? `Unknown symbol “${instance.symbol}”`
                : errorKind === "NO_DATA"
                  ? emptyCopy.title
                  : "Chart data unavailable"
            }
            message={dataError.message}
            onRetry={() => query.refetch()}
            suggestions={POPULAR_CHART_SYMBOLS}
            onPickSymbol={(symbol, entityType) => {
              setSymbol(id, symbol);
              setEntityType(id, entityType);
            }}
          />
        )}

        {!isLoading && !dataError && points.length === 0 && (
          <ChartState
            kind="empty"
            title={emptyCopy.title}
            message={emptyCopy.message}
            onRetry={() => query.refetch()}
            suggestions={POPULAR_CHART_SYMBOLS}
            onPickSymbol={(symbol, entityType) => {
              setSymbol(id, symbol);
              setEntityType(id, entityType);
            }}
          />
        )}

        {!isLoading && !dataError && points.length > 0 && range && dataset && (
          <PlotSurface
            instance={instance}
            points={points}
            lines={computed.lines}
            theme={theme}
            range={range}
            lastClose={lastClose}
            controller={controller}
            isActive={isActive}
            onViewportSettled={handleViewportSettled}
          />
        )}
      </ErrorBoundary>
    </section>
  );
}
