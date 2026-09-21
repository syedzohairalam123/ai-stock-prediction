/**
 * Phase 11 — persisted chart-workspace state (spec §4, §17, §26).
 *
 * Built on the project's existing persistence architecture (zustand +
 * `persist`, exactly like `useWatchlistStore` / `useSettingsStore`), so the whole
 * workspace — panel layout, per-chart symbol/timeframe/style, indicator toggles
 * and periods, drawings, price levels and saved viewports — survives a reload
 * without introducing a new storage mechanism.
 *
 * Undo/redo stacks are deliberately **not** persisted: they describe this
 * session's editing history, and replaying a stale stack after a reload would
 * mutate annotations the user can no longer see.
 *
 * Phase 12 — dynamic chart ids. The two fixed workspace panels keep their ids
 * (`chart-a` / `chart-b`); chart *widgets* register additional instances under
 * `chart-<widgetId>` through `ensureChart`, and `merge` now restores every
 * persisted chart whose id it recognizes (fixed ids first, dynamic ids after).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  ChartInstance,
  ChartLayout,
  ChartSettings,
  ChartSnapshot,
  ChartStyle,
  DrawingShape,
  DrawingStyle,
  DrawingTool,
  EntityType,
  IndicatorConfig,
  IndicatorType,
  Point2D,
  PriceLevel,
  PriceLevelType,
  Viewport,
} from "../lib/charting/types";
import {
  CHART_IDS,
  DEFAULT_INDEX_SYMBOL,
  DEFAULT_SETTINGS,
  DEFAULT_SYMBOL,
  createChartInstance,
  defaultIndicators,
  nextPanelId,
} from "../lib/charting/defaults";
import { inferEntityType } from "../lib/charting/dataSource";
import type { StockRange } from "../lib/timeframes";
import { createPriceLevel, nudgeDuplicatePrice, patchDrawing, translateDrawing, moveAnchor } from "../lib/charting/drawings";

const UNDO_LIMIT = 60;

export interface ChartEditState {
  past: ChartSnapshot[];
  future: ChartSnapshot[];
}

export interface ChartWorkspaceState {
  /** The two fixed panels first, then grid panels and Phase-12 widget charts. */
  charts: ChartInstance[];
  /** The panel the toolbar and single-chart view act on. */
  activeId: string;
  layout: ChartLayout;
  /** Columns used by the `grid` layout (1–3). */
  gridColumns: number;

  // -- Phase 11: cross-panel linking -------------------------------------
  /** When on, the chosen properties follow the user across every open panel. */
  linkEnabled: boolean;
  /** Which properties link. All three default on, but only apply when enabled. */
  linkGroup: { symbol: boolean; timeframe: boolean; crosshair: boolean };
  /**
   * Phase 11 — per-panel opt-in. A missing id means "in the group", so a
   * workspace saved before this field existed keeps every panel linked; `false`
   * takes one panel out without touching the global switch.
   */
  panelLinked: Record<string, boolean>;

  /** Active drawing tool (shared by all panels — it is a cursor mode). */
  tool: DrawingTool;
  /** Active price-level tool, or `null` when placing levels is off. */
  priceLevelTool: PriceLevelType | null;
  /** Currently selected drawing per chart id. */
  selected: Record<string, string | null>;
  /** This-session undo stacks, keyed by chart id (never persisted). */
  edits: Record<string, ChartEditState>;

  // -- workspace ---------------------------------------------------------
  setLayout: (layout: ChartLayout) => void;
  /** Phase 11: columns for the grid layout (clamped to 1–3). */
  setGridColumns: (columns: number) => void;
  /**
   * Phase 11: open another panel. Returns the new id, or `""` when the panel
   * cap is reached. The caller decides the layout (the workspace switches to
   * the grid so the new panel is actually visible).
   */
  addChart: (symbol?: string, timeframe?: StockRange) => string;
  /** Phase 11: close a panel, keeping at least one open and re-homing `activeId`. */
  removeChart: (id: string) => void;
  /**
   * Phase 11: move a panel next to another one. `position` is where the moved
   * panel lands relative to `targetId`; the array order is the display order.
   */
  moveChart: (id: string, targetId: string, position?: "before" | "after") => void;
  setActiveChart: (id: string) => void;
  /** Phase 11: toggle cross-panel linking. */
  setLinkEnabled: (enabled: boolean) => void;
  /** Phase 11: choose which properties the link drives. */
  setLinkGroup: (patch: Partial<{ symbol: boolean; timeframe: boolean; crosshair: boolean }>) => void;
  /** Phase 11: add or remove one panel from the link group. */
  setPanelLink: (id: string, linked: boolean) => void;
  /** Phase 11: flip one panel's link-group membership. */
  togglePanelLink: (id: string) => void;
  resetWorkspace: () => void;
  /** Phase 12: return the instance for `id`, creating it on first use. */
  ensureChart: (id: string, symbol?: string, timeframe?: StockRange) => ChartInstance;
  /** Phase 12: drop a widget chart's instance (widget removed). */
  releaseChart: (id: string) => void;

  // -- per-chart configuration -------------------------------------------
  updateChart: (id: string, patch: Partial<ChartInstance>) => void;
  setSymbol: (id: string, symbol: string) => void;
  setEntityType: (id: string, entityType: EntityType) => void;
  setTimeframe: (id: string, timeframe: StockRange) => void;
  setChartStyle: (id: string, chartType: ChartStyle) => void;
  setVolumeVisible: (id: string, visible: boolean) => void;
  setCrosshairEnabled: (id: string, enabled: boolean) => void;
  updateSettings: (id: string, patch: Partial<ChartSettings>) => void;
  setViewport: (id: string, viewport: Viewport | null) => void;
  resetChart: (id: string) => void;

  // -- indicators ---------------------------------------------------------
  toggleIndicator: (id: string, indicatorId: string) => void;
  updateIndicator: (id: string, indicatorId: string, patch: Partial<IndicatorConfig>) => void;
  addIndicator: (id: string, type: IndicatorType, period: number) => void;
  removeIndicator: (id: string, indicatorId: string) => void;
  resetIndicators: (id: string) => void;

  // -- drawings -------------------------------------------------------
  setTool: (tool: DrawingTool) => void;
  setPriceLevelTool: (type: PriceLevelType | null) => void;
  selectDrawing: (chartId: string, drawingId: string | null) => void;
  addDrawing: (chartId: string, drawing: DrawingShape) => void;
  moveDrawing: (chartId: string, drawingId: string, dt: number, dp: number) => void;
  resizeDrawing: (chartId: string, drawingId: string, anchor: number, point: Point2D) => void;
  styleDrawing: (chartId: string, drawingId: string, style: Partial<DrawingStyle>) => void;
  setDrawingVisible: (chartId: string, drawingId: string, visible: boolean) => void;
  setDrawingLocked: (chartId: string, drawingId: string, locked: boolean) => void;
  deleteDrawing: (chartId: string, drawingId: string) => void;
  clearDrawings: (chartId: string) => void;

  // -- price levels -------------------------------------------------------
  addPriceLevelAt: (chartId: string, type: PriceLevelType, price: number, step: number) => void;
  updatePriceLevel: (chartId: string, levelId: string, patch: Partial<PriceLevel>) => void;
  deletePriceLevel: (chartId: string, levelId: string) => void;
  clearPriceLevels: (chartId: string) => void;

  // -- history ------------------------------------------------------------
  undo: (chartId: string) => void;
  redo: (chartId: string) => void;
  canUndo: (chartId: string) => boolean;
  canRedo: (chartId: string) => boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Merge a possibly-stale persisted chart with the current defaults, so a chart
 * saved by an older build (missing settings, a new indicator, …) still loads.
 * Unknown/duplicate indicators are dropped rather than trusted.
 */
function sanitizeChart(raw: unknown, fallbackId: string): ChartInstance {
  const base = createChartInstance(fallbackId, DEFAULT_SYMBOL, "STOCK", "6M");
  if (!raw || typeof raw !== "object") return base;
  const input = raw as Partial<ChartInstance>;

  const catalogIds = new Set(defaultIndicators().map((i) => i.id));
  const indicators: IndicatorConfig[] = Array.isArray(input.indicators)
    ? input.indicators
        .filter((c): c is IndicatorConfig => Boolean(c) && typeof c === "object" && typeof c.id === "string")
        .map((c) => {
          const seed = defaultIndicators().find((d) => d.id === c.id);
          return {
            ...(seed ?? { id: c.id, type: c.type, enabled: true, period: c.period, color: c.color, lineWidth: 1.5 }),
            ...c,
            period: Number.isFinite(c.period) ? c.period : seed?.period ?? 20,
            enabled: Boolean(c.enabled),
          };
        })
    : base.indicators;

  // Guarantee the default catalog is present so the panel is never empty.
  for (const seed of defaultIndicators()) {
    if (!indicators.some((c) => c.id === seed.id) && catalogIds.has(seed.id)) indicators.push(seed);
  }

  const drawings: DrawingShape[] = Array.isArray(input.drawings)
    ? input.drawings.filter(
        (d) => d && typeof d === "object" && typeof d.id === "string" && Array.isArray(d.coordinates) && d.coordinates.length >= 2
      )
    : [];

  const priceLevels: PriceLevel[] = Array.isArray(input.priceLevels)
    ? input.priceLevels.filter((l) => l && typeof l === "object" && typeof l.id === "string" && Number.isFinite(l.price))
    : [];

  return {
    ...base,
    ...input,
    id: fallbackId,
    symbol: typeof input.symbol === "string" && input.symbol.trim() ? input.symbol.trim().toUpperCase() : base.symbol,
    entityType: input.entityType === "INDEX" ? "INDEX" : "STOCK",
    timeframe: (input.timeframe ?? base.timeframe) as StockRange,
    chartType: input.chartType === "line" || input.chartType === "candles" ? input.chartType : "volume-candles",
    indicators,
    drawings,
    priceLevels,
    viewport: input.viewport && typeof input.viewport === "object" ? (input.viewport as Viewport) : null,
    volumeVisible: input.volumeVisible ?? base.volumeVisible,
    crosshairEnabled: input.crosshairEnabled ?? base.crosshairEnabled,
    settings: { ...DEFAULT_SETTINGS, ...(input.settings ?? {}) },
  };
}

/** One of the two seed panels, opening on a stock and an index respectively. */
function seedCharts(): ChartInstance[] {
  const first = createChartInstance(CHART_IDS[0], DEFAULT_SYMBOL, "STOCK", "6M");
  const second = createChartInstance(CHART_IDS[1], DEFAULT_INDEX_SYMBOL, "INDEX", "1Y");
  return [first, second];
}

function snapshot(chart: ChartInstance): ChartSnapshot {
  return { drawings: chart.drawings, priceLevels: chart.priceLevels };
}

/**
 * Apply a change to a chart's annotations and record the previous state on the
 * undo stack. Returns the partial state to merge.
 */
function withHistory(
  state: ChartWorkspaceState,
  chartId: string,
  mutate: (chart: ChartInstance) => ChartInstance
): Partial<ChartWorkspaceState> {
  const chart = state.charts.find((c) => c.id === chartId);
  if (!chart) return {};
  const next = mutate(chart);
  if (next === chart) return {};

  const stack = state.edits[chartId] ?? { past: [], future: [] };
  const past = [...stack.past, snapshot(chart)].slice(-UNDO_LIMIT);
  return {
    charts: state.charts.map((c) => (c.id === chartId ? next : c)),
    edits: { ...state.edits, [chartId]: { past, future: [] } },
  };
}

function replaceChart(
  state: ChartWorkspaceState,
  chartId: string,
  mutate: (chart: ChartInstance) => ChartInstance
): Partial<ChartWorkspaceState> {
  const chart = state.charts.find((c) => c.id === chartId);
  if (!chart) return {};
  const next = mutate(chart);
  if (next === chart) return {};
  return { charts: state.charts.map((c) => (c.id === chartId ? next : c)) };
}

/**
 * Phase 11 — is this panel part of the link group? Missing entries mean "yes",
 * so panels created before per-panel linking existed (or restored from an older
 * workspace) stay linked. Only an explicit `false` excludes a panel.
 */
export function isPanelLinked(
  state: Pick<ChartWorkspaceState, "panelLinked">,
  id: string
): boolean {
  return state.panelLinked[id] !== false;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useChartStore = create<ChartWorkspaceState>()(
  persist(
    (set, get) => ({
      charts: seedCharts(),
      activeId: CHART_IDS[0],
      layout: "single",
      gridColumns: 2,
      linkEnabled: false,
      linkGroup: { symbol: true, timeframe: true, crosshair: true },
      panelLinked: {},
      tool: "select",
      priceLevelTool: null,
      selected: {},
      edits: {},

      setLayout: (layout) => set({ layout }),

      setGridColumns: (columns) =>
        set({ gridColumns: Math.max(1, Math.min(3, Math.floor(columns) || 2)) }),

      addChart: (symbol, timeframe) => {
        const state = get();
        const id = nextPanelId(state.charts);
        if (!id) return "";
        const resolvedSymbol = symbol?.trim().toUpperCase() || DEFAULT_SYMBOL;
        const instance = createChartInstance(
          id,
          resolvedSymbol,
          inferEntityType(resolvedSymbol),
          (timeframe as StockRange) ?? "6M"
        );
        set({ charts: [...state.charts, instance] });
        return id;
      },

      moveChart: (id, targetId, position = "before") =>
        set((s) => {
          if (id === targetId) return {};
          const from = s.charts.findIndex((c) => c.id === id);
          if (from === -1 || !s.charts.some((c) => c.id === targetId)) return {};
          const charts = [...s.charts];
          const [moved] = charts.splice(from, 1);
          // Resolve the anchor *after* removing the moved panel, so an earlier
          // source index can never shift the destination by one.
          const anchor = charts.findIndex((c) => c.id === targetId);
          charts.splice(anchor + (position === "after" ? 1 : 0), 0, moved);
          return { charts };
        }),

      removeChart: (id) =>
        set((s) => {
          if (s.charts.length <= 1) return {};
          const index = s.charts.findIndex((c) => c.id === id);
          if (index === -1) return {};
          const charts = s.charts.filter((c) => c.id !== id);
          const selected = { ...s.selected };
          const edits = { ...s.edits };
          const panelLinked = { ...s.panelLinked };
          delete selected[id];
          delete edits[id];
          delete panelLinked[id];
          // Re-home the active panel to its neighbour (or the first one left),
          // and fall back out of a multi-panel layout when only one remains.
          const activeId = s.activeId === id ? (charts[index] ?? charts[charts.length - 1]).id : s.activeId;
          const layout = charts.length < 2 && s.layout !== "single" ? "single" : s.layout;
          return { charts, selected, edits, panelLinked, activeId, layout };
        }),

      setLinkEnabled: (linkEnabled) => set({ linkEnabled }),
      setLinkGroup: (patch) => set((s) => ({ linkGroup: { ...s.linkGroup, ...patch } })),

      setPanelLink: (id, linked) =>
        set((s) => {
          if (!s.charts.some((c) => c.id === id)) return {};
          if (isPanelLinked(s, id) === linked) return {};
          return { panelLinked: { ...s.panelLinked, [id]: linked } };
        }),

      togglePanelLink: (id) => get().setPanelLink(id, !isPanelLinked(get(), id)),

      // Switching the active panel also stops an armed price-level tool, because
      // the next click would otherwise land on the other chart.
      setActiveChart: (id) => set((s) => (s.charts.some((c) => c.id === id) ? { activeId: id } : {})),

      resetWorkspace: () =>
        set({
          charts: seedCharts(),
          activeId: CHART_IDS[0],
          layout: "single",
          gridColumns: 2,
          linkEnabled: false,
          linkGroup: { symbol: true, timeframe: true, crosshair: true },
          panelLinked: {},
          tool: "select",
          priceLevelTool: null,
          selected: {},
          edits: {},
        }),

      /**
       * Phase 12 — idempotent instance lookup for widget charts. Creates the
       * instance on first use (seeded from the widget's settings) and is a
       * no-op read afterwards, so React effects can call it every render.
       */
      ensureChart: (id, symbol, timeframe) => {
        const existing = get().charts.find((c) => c.id === id);
        if (existing) return existing;
        const instance = createChartInstance(id, symbol ?? DEFAULT_SYMBOL, "STOCK", (timeframe as StockRange) ?? "6M");
        set((s) => ({ charts: [...s.charts, instance] }));
        return instance;
      },

      /** Phase 12 — remove a widget chart's instance and its edit history. */
      releaseChart: (id) =>
        set((s) => {
          if (!s.charts.some((c) => c.id === id)) return {};
          const charts = s.charts.filter((c) => c.id !== id);
          const selected = { ...s.selected };
          const edits = { ...s.edits };
          const panelLinked = { ...s.panelLinked };
          delete selected[id];
          delete edits[id];
          delete panelLinked[id];
          return {
            charts,
            selected,
            edits,
            panelLinked,
            activeId: s.activeId === id ? CHART_IDS[0] : s.activeId,
          };
        }),

      updateChart: (id, patch) => set((s) => replaceChart(s, id, (c) => ({ ...c, ...patch }))),

      // A new instrument invalidates the saved zoom (different bar count) but
      // keeps every annotation — levels drawn for a name are the analyst's.
      //
      // Phase 11: when cross-panel linking is on and `symbol` is a linked
      // property, the change is applied to every panel at once. With linking
      // off (the default) this is byte-for-byte the old single-panel behaviour.
      setSymbol: (id, symbol) =>
        set((s) => {
          const next = symbol.trim().toUpperCase();
          if (!next) return {};
          // Linking only broadcasts between panels that joined the group; a panel
          // that opted out (or the global switch being off) stays put.
          const linked = s.linkEnabled && s.linkGroup.symbol && isPanelLinked(s, id);
          const charts = s.charts.map((c) => {
            if (c.id !== id && !(linked && isPanelLinked(s, c.id))) return c;
            if (next === c.symbol) return c;
            const inferred = inferEntityType(next);
            return { ...c, symbol: next, entityType: inferred, viewport: null };
          });
          return charts.some((c, index) => c !== s.charts[index]) ? { charts } : {};
        }),

      setEntityType: (id, entityType) =>
        set((s) => replaceChart(s, id, (c) => (c.entityType === entityType ? c : { ...c, entityType, viewport: null }))),

      setTimeframe: (id, timeframe) =>
        set((s) => {
          if (!s.charts.some((c) => c.id === id)) return {};
          const linked = s.linkEnabled && s.linkGroup.timeframe && isPanelLinked(s, id);
          const charts = s.charts.map((c) => {
            if (c.id !== id && !(linked && isPanelLinked(s, c.id))) return c;
            if (c.timeframe === timeframe) return c;
            return { ...c, timeframe, viewport: null };
          });
          return charts.some((c, index) => c !== s.charts[index]) ? { charts } : {};
        }),

      // Chart-style switching intentionally preserves the viewport, indicators
      // and annotations (spec §5) — only the render style changes.
      setChartStyle: (id, chartType) => set((s) => replaceChart(s, id, (c) => ({ ...c, chartType }))),

      setVolumeVisible: (id, volumeVisible) => set((s) => replaceChart(s, id, (c) => ({ ...c, volumeVisible }))),

      setCrosshairEnabled: (id, crosshairEnabled) =>
        set((s) => {
          const linked = s.linkEnabled && s.linkGroup.crosshair && isPanelLinked(s, id);
          const charts = s.charts.map((c) => {
            if (c.id !== id && !(linked && isPanelLinked(s, c.id))) return c;
            if (c.crosshairEnabled === crosshairEnabled) return c;
            return { ...c, crosshairEnabled };
          });
          return charts.some((c, index) => c !== s.charts[index]) ? { charts } : {};
        }),

      updateSettings: (id, patch) =>
        set((s) => replaceChart(s, id, (c) => ({ ...c, settings: { ...c.settings, ...patch } }))),

      setViewport: (id, viewport) => set((s) => replaceChart(s, id, (c) => ({ ...c, viewport }))),

      resetChart: (id) =>
        set((s) =>
          replaceChart(s, id, (c) => ({
            ...c,
            chartType: "volume-candles",
            indicators: defaultIndicators(),
            drawings: [],
            priceLevels: [],
            viewport: null,
            volumeVisible: true,
            crosshairEnabled: true,
            settings: { ...DEFAULT_SETTINGS },
          }))
        ),

      toggleIndicator: (id, indicatorId) =>
        set((s) =>
          replaceChart(s, id, (c) => ({
            ...c,
            indicators: c.indicators.map((i) => (i.id === indicatorId ? { ...i, enabled: !i.enabled } : i)),
          }))
        ),

      updateIndicator: (id, indicatorId, patch) =>
        set((s) =>
          replaceChart(s, id, (c) => ({
            ...c,
            indicators: c.indicators.map((i) => (i.id === indicatorId ? { ...i, ...patch } : i)),
          }))
        ),

      addIndicator: (id, type, period) =>
        set((s) =>
          replaceChart(s, id, (c) => {
            const safePeriod = Math.max(1, Math.min(400, Math.floor(period) || 20));
            const key = type === "SMA" ? `SMA:${safePeriod}` : type === "EMA" ? `EMA:${safePeriod}` : type;
            if (c.indicators.some((i) => i.id === key)) return c;
            const palette = ["#5E9FE8", "#DE9255", "#BF8EDA", "#72BC8F", "#2dd4bf", "#facc15"];
            // Phase 11 — oscillator sub-panes carry their own pane hint and
            // MACD/Stochastic their fast/slow/signal periods.
            const pane: IndicatorConfig["pane"] =
              type === "RSI" || type === "MACD" || type === "STOCH" || type === "ATR" ? "sub" : "main";
            const seed: IndicatorConfig = {
              id: key,
              type,
              enabled: true,
              period: safePeriod,
              stdDev: type === "BB" ? 2 : undefined,
              ...(type === "MACD" ? { fastPeriod: 12, slowPeriod: 26, signalPeriod: 9 } : {}),
              ...(type === "STOCH" ? { signalPeriod: 3 } : {}),
              color: palette[c.indicators.length % palette.length],
              lineWidth: 1.6,
              configurable: type !== "VWAP",
              pane,
            };
            return { ...c, indicators: [...c.indicators, seed] };
          })
        ),

      removeIndicator: (id, indicatorId) =>
        set((s) =>
          replaceChart(s, id, (c) => ({
            ...c,
            indicators: c.indicators.filter((i) => i.id !== indicatorId),
          }))
        ),

      resetIndicators: (id) => set((s) => replaceChart(s, id, (c) => ({ ...c, indicators: defaultIndicators() }))),

      setTool: (tool) => set((s) => ({ tool, priceLevelTool: tool === "select" ? s.priceLevelTool : null })),

      setPriceLevelTool: (priceLevelTool) => set({ priceLevelTool }),

      selectDrawing: (chartId, drawingId) =>
        set((s) => ({ selected: { ...s.selected, [chartId]: drawingId } })),

      addDrawing: (chartId, drawing) => set((s) => withHistory(s, chartId, (c) => ({ ...c, drawings: [...c.drawings, drawing] }))),

      moveDrawing: (chartId, drawingId, dt, dp) =>
        set((s) =>
          withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.map((d) => (d.id === drawingId && !d.locked ? translateDrawing(d, dt, dp) : d)),
          }))
        ),

      resizeDrawing: (chartId, drawingId, anchor, point) =>
        set((s) =>
          withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.map((d) => (d.id === drawingId && !d.locked ? moveAnchor(d, anchor, point) : d)),
          }))
        ),

      styleDrawing: (chartId, drawingId, style) =>
        set((s) =>
          withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.map((d) => (d.id === drawingId ? patchDrawing(d, { style: { ...d.style, ...style } }) : d)),
          }))
        ),

      setDrawingVisible: (chartId, drawingId, visible) =>
        set((s) =>
          withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.map((d) => (d.id === drawingId ? patchDrawing(d, { visible }) : d)),
          }))
        ),

      setDrawingLocked: (chartId, drawingId, locked) =>
        set((s) =>
          withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.map((d) => (d.id === drawingId ? patchDrawing(d, { locked }) : d)),
          }))
        ),

      deleteDrawing: (chartId, drawingId) =>
        set((s) => {
          const partial = withHistory(s, chartId, (c) => ({
            ...c,
            drawings: c.drawings.filter((d) => d.id !== drawingId),
          }));
          return { ...partial, selected: { ...s.selected, [chartId]: null } };
        }),

      clearDrawings: (chartId) =>
        set((s) => {
          const partial = withHistory(s, chartId, (c) => (c.drawings.length ? { ...c, drawings: [] } : c));
          return { ...partial, selected: { ...s.selected, [chartId]: null } };
        }),

      addPriceLevelAt: (chartId, type, price, step) =>
        set((s) =>
          withHistory(s, chartId, (c) => {
            const level = createPriceLevel(type, nudgeDuplicatePrice(c.priceLevels, price, step));
            return { ...c, priceLevels: [...c.priceLevels, level] };
          })
        ),

      updatePriceLevel: (chartId, levelId, patch) =>
        set((s) =>
          withHistory(s, chartId, (c) => {
            const target = c.priceLevels.find((l) => l.id === levelId);
            if (!target || (target.locked && patch.price !== undefined)) return c;
            return { ...c, priceLevels: c.priceLevels.map((l) => (l.id === levelId ? { ...l, ...patch } : l)) };
          })
        ),

      deletePriceLevel: (chartId, levelId) =>
        set((s) => withHistory(s, chartId, (c) => ({ ...c, priceLevels: c.priceLevels.filter((l) => l.id !== levelId) }))),

      clearPriceLevels: (chartId) =>
        set((s) => withHistory(s, chartId, (c) => (c.priceLevels.length ? { ...c, priceLevels: [] } : c))),

      undo: (chartId) =>
        set((s) => {
          const stack = s.edits[chartId];
          const chart = s.charts.find((c) => c.id === chartId);
          if (!stack || !chart || stack.past.length === 0) return {};
          const previous = stack.past[stack.past.length - 1];
          return {
            charts: s.charts.map((c) =>
              c.id === chartId ? { ...c, drawings: previous.drawings, priceLevels: previous.priceLevels } : c
            ),
            edits: {
              ...s.edits,
              [chartId]: {
                past: stack.past.slice(0, -1),
                future: [snapshot(chart), ...stack.future].slice(0, UNDO_LIMIT),
              },
            },
          };
        }),

      redo: (chartId) =>
        set((s) => {
          const stack = s.edits[chartId];
          const chart = s.charts.find((c) => c.id === chartId);
          if (!stack || !chart || stack.future.length === 0) return {};
          const [next, ...rest] = stack.future;
          return {
            charts: s.charts.map((c) =>
              c.id === chartId ? { ...c, drawings: next.drawings, priceLevels: next.priceLevels } : c
            ),
            edits: {
              ...s.edits,
              [chartId]: { past: [...stack.past, snapshot(chart)].slice(-UNDO_LIMIT), future: rest },
            },
          };
        }),

      canUndo: (chartId) => (get().edits[chartId]?.past.length ?? 0) > 0,
      canRedo: (chartId) => (get().edits[chartId]?.future.length ?? 0) > 0,
    }),
    {
      name: "neural-market-chart-workspace",
      version: 1,
      // Undo history and transient cursor modes stay out of localStorage.
      partialize: (state) => ({
        charts: state.charts,
        activeId: state.activeId,
        layout: state.layout,
        gridColumns: state.gridColumns,
        linkEnabled: state.linkEnabled,
        linkGroup: state.linkGroup,
        panelLinked: state.panelLinked,
      }),
      merge: (persisted, current) => {
        const raw = (persisted ?? {}) as Partial<ChartWorkspaceState>;
        // Fixed panels keep their canonical order; widget charts (dynamic ids)
        // follow afterwards so a Phase-12 workspace restores every chart it had.
        const fixed = CHART_IDS.map((id, index) => sanitizeChart(raw.charts?.[index], id));
        const dynamic = Array.isArray(raw.charts)
          ? raw.charts
              .slice(CHART_IDS.length)
              .filter((c): c is ChartInstance => Boolean(c) && typeof (c as ChartInstance)?.id === "string")
              .map((c) => sanitizeChart(c, (c as ChartInstance).id))
          : [];
        const charts = [...fixed, ...dynamic];
        const activeId = charts.some((c) => c.id === raw.activeId) ? (raw.activeId as string) : CHART_IDS[0];
        return {
          ...current,
          ...raw,
          charts,
          activeId,
          layout: raw.layout === "split" ? "split" : raw.layout === "grid" ? "grid" : "single",
          gridColumns: Math.max(1, Math.min(3, Math.floor(Number(raw.gridColumns)) || 2)),
          linkEnabled: Boolean(raw.linkEnabled),
          linkGroup: {
            symbol: raw.linkGroup?.symbol ?? true,
            timeframe: raw.linkGroup?.timeframe ?? true,
            crosshair: raw.linkGroup?.crosshair ?? true,
          },
          // Only keep real booleans from storage; anything else falls back to the
          // default (missing ⇒ linked).
          panelLinked: Object.fromEntries(
            Object.entries(raw.panelLinked ?? {}).filter(([, value]) => typeof value === "boolean")
          ) as Record<string, boolean>,
          tool: "select" as DrawingTool,
          priceLevelTool: null,
          selected: {},
          edits: {},
        };
      },
    }
  )
);

/** Read one chart instance (never throws — falls back to the active panel). */
export function selectChart(state: ChartWorkspaceState, id: string): ChartInstance {
  return state.charts.find((c) => c.id === id) ?? state.charts[0];
}
