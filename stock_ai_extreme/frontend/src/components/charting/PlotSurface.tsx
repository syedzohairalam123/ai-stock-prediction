/**
 * Phase 11 — the interactive plot surface.
 *
 * One component owns everything between the toolbar and the candles:
 *
 *   - a memoized Plotly figure (the only thing that may trigger a Plotly.react),
 *   - the SVG annotation layer that shares the plot rectangle with Plotly,
 *   - all pointer gestures (place / select / move / resize / drag a level),
 *   - the hover readout + indicator legend.
 *
 * Performance contract (spec §27)
 * ------------------------------
 * `data` / `layout` / `config` are memoized on their *real* dependencies — hover
 * and drag state are deliberately not among them. react-plotly.js bails out of
 * `Plotly.react` when those three props are referentially unchanged, so moving
 * the mouse across the chart never re-lays-out Plotly, and indicator maths is
 * memoized further upstream. Drags render from a local override and commit to the
 * store exactly once, on pointer up (one undo step per gesture, one write to
 * localStorage per gesture).
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Plot from "react-plotly.js";
import type { Figure } from "react-plotly.js";
import type { Config, Data, Layout, PlotHoverEvent, PlotlyHTMLElement } from "plotly.js";
import type { Candle, ChartInstance, DrawingShape, DrawingType, Point2D, PriceLevel, PriceLevelType } from "../../lib/charting/types";
import type { IndicatorLine } from "../../lib/charting/indicators";
import { drawingGeometry, makeTransform, toData } from "../../lib/charting/geometry";
import {
  buildDrawingLayers,
  buildPriceLevelLayers,
  hitTestDrawings,
  hitTestLayerAnchor,
  hitTestPriceLevels,
  type DrawingLayer,
  type PriceLevelLayer,
} from "../../lib/charting/annotations";
import { DEFAULT_DRAWING_STYLE, moveAnchor, translateDrawing } from "../../lib/charting/drawings";
import {
  buildConfig,
  buildLayout,
  buildTraces,
  interpretRelayout,
  nearestIndexByTime,
  parseAxisX,
  pricePaneRect,
  type ChartTheme,
  type PlotRange,
} from "../../lib/charting/plotModel";
import { useElementSize } from "../../hooks/useElementSize";
import AnnotationLayer from "./AnnotationLayer";
import ChartHud from "./ChartHud";

const PLOT_STYLE = { width: "100%", height: "100%" } as const;

/**
 * The graph div is also an event emitter (Plotly mixes `on`/`removeListener`
 * into it as *own* properties). Typed structurally — and every method is
 * optional — because `@types/plotly.js` declares the `on` overloads but not the
 * matching `removeListener`, and because `Plotly.purge` deletes the whole mixin
 * again (see `ChartPlot`).
 */
interface GraphEmitter {
  on?(event: string, handler: (payload: unknown) => void): void;
  removeListener?(event: string, handler: (payload: unknown) => void): void;
  addEventListener?(event: string, handler: (payload: unknown) => void): void;
  removeEventListener?(event: string, handler: (payload: unknown) => void): void;
}

/** Plotly hands back a sparse object; never trust its shape. */
function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/** Gesture in progress, held locally until pointer-up commits it. */
type DragState =
  | { kind: "move"; id: string; origin: DrawingShape; start: Point2D; point: Point2D }
  | { kind: "anchor"; id: string; origin: DrawingShape; anchor: number; point: Point2D }
  | { kind: "level"; id: string; origin: PriceLevel; price: number };

interface DraftState {
  type: DrawingType;
  from: Point2D;
  to: Point2D;
}

export interface ChartInteractionController {
  tool: string;
  priceLevelTool: PriceLevelType | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onCompleteDrawing: (type: DrawingType, from: Point2D, to: Point2D) => void;
  onToolSettled: () => void;
  onMoveDrawing: (id: string, dt: number, dp: number) => void;
  onResizeDrawing: (id: string, anchor: number, point: Point2D) => void;
  onPlacePriceLevel: (type: PriceLevelType, price: number) => void;
  onMovePriceLevel: (id: string, price: number) => void;
  /** Escape pressed with a tool armed — hand the cursor back to Select. */
  onDisarmTool: () => void;
}

/**
 * Memoized wrapper: Plotly is only re-configured when the figure really changed.
 *
 * Event wiring is owned here instead of through react-plotly's `onHover` /
 * `onRelayout` props, because that wrapper keeps its own registry of attached
 * handlers: on a re-mount it re-attaches only what it *believes* it lost. A
 * React StrictMode double-mount runs `Plotly.purge` (which empties the graph
 * div's emitter) while that registry still lists `plotly_hover` / `plotly_unhover`
 * / `plotly_relayout` as attached — so the chart silently stops receiving hover
 * and relayout events in development. Subscribing ourselves, and re-binding from
 * `onInitialized` (which fires on every mount), keeps the contract independent of
 * the wrapper's bookkeeping and is idempotent by construction: every effect run
 * pairs a fresh set of closures with a matching teardown.
 *
 * Teardown hazard (why every call below is guarded)
 * -------------------------------------------------
 * `Plotly.purge` does not merely clear listeners — it *deletes* `on` /
 * `removeListener` from the graph div, because Plotly mixes them in as own
 * properties. React tears a child down before its parent, so when this plot is
 * unmounted (switching split → single, going mobile, leaving the route, or the
 * StrictMode double-mount) react-plotly has already purged the div by the time
 * this effect's cleanup runs. Calling `removeListener` then would throw
 * `TypeError: emitter.removeListener is not a function` from inside a passive
 * unmount, which React cannot recover from — it propagates past the panel's
 * error boundary and blanks the whole workspace. So the detach functions are
 * captured (bound) at *attach* time and every call is guarded: a purged div
 * simply has nothing left to detach, which is exactly what we want.
 */
const ChartPlot = memo(function ChartPlot({
  data,
  layout,
  config,
  onRelayout,
  onHover,
  onUnhover,
}: {
  data: Data[];
  layout: Partial<Layout>;
  config: Partial<Config>;
  onRelayout: (event: Record<string, unknown>) => void;
  onHover: (event: PlotHoverEvent) => void;
  onUnhover: () => void;
}) {
  /**
   * Held as `{ div, epoch }` rather than the bare element: a re-mount hands back
   * the *same* node, and a plain `setState` of an equal value would not re-run the
   * binding effect.
   */
  const [binding, setBinding] = useState<{ div: PlotlyHTMLElement; epoch: number } | null>(null);
  const runtime = useRef({ onRelayout, onHover, onUnhover });
  runtime.current = { onRelayout, onHover, onUnhover };

  const handleInitialized = useCallback((_figure: Readonly<Figure>, graphDiv: Readonly<HTMLElement>) => {
    setBinding((prev) => ({ div: graphDiv as PlotlyHTMLElement, epoch: (prev?.epoch ?? 0) + 1 }));
  }, []);

  useEffect(() => {
    if (!binding) return;
    const emitter = binding.div as unknown as GraphEmitter;

    const relayout = (payload: unknown) => runtime.current.onRelayout(asRecord(payload));
    const hover = (payload: unknown) => runtime.current.onHover(payload as PlotHoverEvent);
    const unhover = () => runtime.current.onUnhover();

    // Prefer Plotly's own emitter (the documented API); fall back to native DOM
    // events so a future Plotly that drops the mixin still delivers hover and
    // relayout instead of silently going dead.
    let attach: ((event: string, handler: (payload: unknown) => void) => void) | null = null;
    let detach: ((event: string, handler: (payload: unknown) => void) => void) | null = null;
    if (typeof emitter.on === "function" && typeof emitter.removeListener === "function") {
      attach = emitter.on.bind(emitter);
      detach = emitter.removeListener.bind(emitter);
    } else if (typeof emitter.addEventListener === "function" && typeof emitter.removeEventListener === "function") {
      attach = emitter.addEventListener.bind(emitter);
      detach = emitter.removeEventListener.bind(emitter);
    }
    if (!attach) return;

    try {
      attach("plotly_relayout", relayout);
      attach("plotly_hover", hover);
      attach("plotly_unhover", unhover);
    } catch {
      // The div was purged between render and effect — nothing to subscribe to.
      return;
    }

    // `detach` was captured before the purge could delete it, and the call is
    // still guarded: detaching from a already-purged plot is a no-op, not a crash.
    return () => {
      try {
        detach?.("plotly_relayout", relayout);
        detach?.("plotly_hover", hover);
        detach?.("plotly_unhover", unhover);
      } catch {
        /* purged — the listeners are already gone */
      }
    };
  }, [binding]);

  return (
    <Plot
      data={data}
      layout={layout}
      config={config}
      style={PLOT_STYLE}
      useResizeHandler
      onInitialized={handleInitialized}
    />
  );
});

export interface PlotSurfaceProps {
  instance: ChartInstance;
  points: Candle[];
  lines: IndicatorLine[];
  theme: ChartTheme;
  /** The window the chart should adopt (a new value re-applies the zoom). */
  range: PlotRange;
  lastClose: number | null;
  controller: ChartInteractionController;
  isActive: boolean;
  /**
   * Debounced persistence of the user's zoom window. `null` means the axes went
   * back to the layout default (double-click / autorange), so any saved viewport
   * for this dataset should be dropped.
   */
  onViewportSettled: (range: PlotRange | null) => void;
}

export default function PlotSurface({
  instance,
  points,
  lines,
  theme,
  range,
  lastClose,
  controller,
  isActive,
  onViewportSettled,
}: PlotSurfaceProps) {
  const { ref: boxRef, size } = useElementSize<HTMLDivElement>();
  const showVolume = useMemo(() => instance.chartType === "volume-candles" || instance.volumeVisible, [instance.chartType, instance.volumeVisible]);
  const rect = useMemo(() => pricePaneRect(size.width, size.height, showVolume), [size.width, size.height, showVolume]);

  // What Plotly currently reports — drives the annotation transform only. It is
  // intentionally *not* fed back into the layout (that would fight the user).
  const [liveRange, setLiveRange] = useState<PlotRange | null>(null);
  const effectiveRange = liveRange ?? range;  const transform = useMemo(
    () => makeTransform(rect, effectiveRange.x, effectiveRange.y),
    [rect, effectiveRange.x, effectiveRange.y]
  );

  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [hoveredDrawingId, setHoveredDrawingId] = useState<string | null>(null);
  const [hoveredAnchor, setHoveredAnchor] = useState(false);
  const [hoveredLevelId, setHoveredLevelId] = useState<string | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);
  /** Boolean (not the drag state itself) so a moving pointer cannot re-react Plotly. */
  const isDragging = drag !== null;

  // Refs keep the memoized callbacks stable while still seeing fresh data.
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const persistTimer = useRef<number | null>(null);
  /** The layout window we were given — the base for partial relayouts. */
  const rangeRef = useRef(range);
  rangeRef.current = range;
  /** Mirror of `liveRange` for the memoized handler (no stale reads). */
  const liveRangeRef = useRef<PlotRange | null>(null);

  /** Single writer for the tracked window, so state and ref cannot diverge. */
  const applyLiveRange = useCallback((next: PlotRange | null) => {
    liveRangeRef.current = next;
    setLiveRange(next);
  }, []);

  // A new dataset invalidates the on-screen window we were tracking.
  useEffect(() => {
    applyLiveRange(null);
  }, [applyLiveRange, instance.symbol, instance.timeframe, instance.entityType]);

  // Switching tools mid-placement abandons the half-drawn shape.
  useEffect(() => {
    if (draft && draft.type !== controller.tool) setDraft(null);
  }, [controller.tool, draft]);

  useEffect(
    () => () => {
      if (persistTimer.current !== null) window.clearTimeout(persistTimer.current);
    },
    []
  );

  /**
   * Axis-window changes from Plotly — decisions live in the pure
   * `interpretRelayout` (unit-tested), this only dispatches them. Zoom/pan fires
   * many times per second, so persistence is debounced: the store (and
   * localStorage) sees one write per gesture, not per wheel tick.
   */
  const handleRelayout = useCallback(
    (event: Record<string, unknown>) => {
      const base = liveRangeRef.current ?? rangeRef.current;
      const outcome = interpretRelayout(event, base);
      if (outcome.kind === "ignore") return;

      // A reset or a new window both cancel whatever gesture was being timed.
      if (persistTimer.current !== null) window.clearTimeout(persistTimer.current);

      if (outcome.kind === "reset") {
        applyLiveRange(null);
        onViewportSettled(null);
        return;
      }

      applyLiveRange(outcome.range);
      persistTimer.current = window.setTimeout(() => onViewportSettled(outcome.range), 500);
    },
    [applyLiveRange, onViewportSettled]
  );

  /**
   * Resolve the hovered bar from Plotly's hover event (authoritative path).
   *
   * A candlestick trace does not put `pointIndex` on its hover point, so the
   * index is taken from whichever numeric field Plotly did provide and, failing
   * that, recovered from the hovered time value. `trackHoverFromPointer` below
   * is the fallback that keeps the readout correct when this event never fires.
   */
  const handleHover = useCallback((event: PlotHoverEvent) => {
    const first = event?.points?.[0];
    if (!first) return;
    const length = pointsRef.current.length;
    if (length === 0) return;

    const raw = (first as { pointIndex?: number; pointNumber?: number });
    const numeric = typeof raw.pointIndex === "number" ? raw.pointIndex : typeof raw.pointNumber === "number" ? raw.pointNumber : null;
    if (numeric !== null && numeric >= 0 && numeric < length) {
      setHoverIndex(numeric);
      return;
    }

    const timestamp = parseAxisX(first.x);
    if (timestamp !== null) {
      const index = nearestIndexByTime(pointsRef.current, timestamp);
      setHoverIndex(index >= 0 ? index : null);
      return;
    }
    setHoverIndex(null);
  }, []);

  const handleUnhover = useCallback(() => setHoverIndex(null), []);

  // -- figure ---------------------------------------------------------------
  const data = useMemo(
    () => buildTraces({ instance, points, lines, name: instance.symbol, theme }),
    [instance, points, lines, theme]
  );
  const layout = useMemo(
    () =>
      buildLayout({
        instance,
        points,
        lines,
        name: instance.symbol,
        theme,
        range,
        showVolume,
        uirevision: `${instance.id}:${instance.symbol}:${instance.timeframe}:${points.length}`,
        // Panning is only safe when nothing else owns the drag. `isDragging` also
        // covers pointer types with no hover phase (touch): the moment a gesture
        // seizes an annotation, Plotly's own pan is switched off.
        dragmode:
          controller.tool === "select" && !controller.priceLevelTool && !hoveredDrawingId && !hoveredLevelId && !isDragging
            ? "pan"
            : false,
      }),
    [
      instance,
      points,
      lines,
      theme,
      range,
      showVolume,
      controller.tool,
      controller.priceLevelTool,
      hoveredDrawingId,
      hoveredLevelId,
      isDragging,
    ]
  );
  const config = useMemo(() => buildConfig(), []);

  // -- annotation layers (drag override applied in the render pass) ----------
  const drawings = useMemo(() => {
    if (!drag || drag.kind === "level") return instance.drawings;
    if (drag.kind === "move") {
      const dt = drag.point.t - drag.start.t;
      const dp = drag.point.p - drag.start.p;
      return instance.drawings.map((d) => (d.id === drag.id ? translateDrawing(d, dt, dp) : d));
    }
    return instance.drawings.map((d) => (d.id === drag.id ? moveAnchor(d, drag.anchor, drag.point) : d));
  }, [instance.drawings, drag]);

  const levels = useMemo(() => {
    if (!drag || drag.kind !== "level") return instance.priceLevels;
    return instance.priceLevels.map((l) => (l.id === drag.id ? { ...l, price: drag.price } : l));
  }, [instance.priceLevels, drag]);

  const layers = useMemo(() => buildDrawingLayers(drawings, transform), [drawings, transform]);
  const levelLayers = useMemo(() => buildPriceLevelLayers(levels, transform), [levels, transform]);

  const draftLayer = useMemo<DrawingLayer | null>(() => {
    if (!draft || !transform) return null;
    const shape: DrawingShape = {
      id: "draft",
      type: draft.type,
      coordinates: [draft.from, draft.to],
      style: DEFAULT_DRAWING_STYLE,
      visible: true,
      locked: false,
    };
    const geometry = drawingGeometry(shape, transform);
    return geometry ? { shape, geometry } : null;
  }, [draft, transform]);

  // -- pointer plumbing -----------------------------------------------------
  const localPoint = useCallback((event: { clientX: number; clientY: number }) => {
    const node = boxRef.current;
    if (!node) return { px: 0, py: 0 };
    const box = node.getBoundingClientRect();
    return { px: event.clientX - box.left, py: event.clientY - box.top };
  }, [boxRef]);

  const insidePlot = useCallback(
    (px: number, py: number) =>
      px >= rect.left && px <= rect.left + rect.width && py >= rect.top && py <= rect.top + rect.height,
    [rect]
  );

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (!transform) return;
      const { px, py } = localPoint(event);
      if (!insidePlot(px, py)) return;
      const dataPoint = toData(px, py, transform);

      // 1. An armed price-level tool owns the click (spec §19) — but a click that
      //    lands on a level already on the chart selects and drags *that* level
      //    instead of stacking another one on top of it. Without this an analyst
      //    could never adjust a level they had just placed.
      if (controller.priceLevelTool) {
        event.preventDefault();
        const existing = hitTestPriceLevels(levelLayers, py);
        if (existing) {
          controller.onSelect(existing.level.id);
          if (existing.level.locked) return;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag({ kind: "level", id: existing.level.id, origin: existing.level, price: existing.level.price });
          return;
        }
        controller.onPlacePriceLevel(controller.priceLevelTool, dataPoint.p);
        return;
      }

      // 2. An armed drawing tool: click once for the anchor, again to commit.
      if (controller.tool !== "select" && draft === null) {
        event.preventDefault();
        setDraft({ type: controller.tool as DrawingType, from: dataPoint, to: dataPoint });
        return;
      }
      if (controller.tool !== "select" && draft) {
        event.preventDefault();
        controller.onCompleteDrawing(draft.type, draft.from, dataPoint);
        setDraft(null);
        return;
      }

      // 3. Select mode: resize handle → shape → price level → deselect.
      const selectedLayer = controller.selectedId
        ? layers.find((layer) => layer.shape.id === controller.selectedId) ?? null
        : null;
      if (selectedLayer && !selectedLayer.shape.locked) {
        const anchor = hitTestLayerAnchor(selectedLayer, px, py);
        if (anchor >= 0) {
          event.preventDefault();
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag({ kind: "anchor", id: selectedLayer.shape.id, origin: selectedLayer.shape, anchor, point: dataPoint });
          return;
        }
      }

      const shapeHit = hitTestDrawings(layers, px, py);
      if (shapeHit) {
        controller.onSelect(shapeHit.shape.id);
        if (!shapeHit.shape.locked) {
          event.preventDefault();
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag({ kind: "move", id: shapeHit.shape.id, origin: shapeHit.shape, start: dataPoint, point: dataPoint });
        }
        return;
      }

      const levelHit = hitTestPriceLevels(levelLayers, py);
      if (levelHit) {
        controller.onSelect(levelHit.level.id);
        if (!levelHit.level.locked) {

          event.preventDefault();
          event.currentTarget.setPointerCapture?.(event.pointerId);
          setDrag({ kind: "level", id: levelHit.level.id, origin: levelHit.level, price: levelHit.level.price });
        }
        return;
      }

      controller.onSelect(null);
    },
    [controller, draft, insidePlot, layers, levelLayers, localPoint, transform]
  );

  /**
   * Crosshair tracking (spec §22), independent of Plotly's hover events.
   *
   * Plotly's `plotly_hover` emitter has proven unreliable on candlestick
   * figures — in emulated/headless viewports and after some in-place figure
   * updates the event simply stops firing while scatter traces keep working,
   * which left the readout sitting on "latest" while the analyst pointed at a
   * specific candle. The readout therefore also tracks the pointer through the
   * same data-space transform the annotation layer uses: the hovered bar is
   * recovered from the pointer's time coordinate with the shared binary
   * search. Plotly's event stays wired and authoritative when it does fire;
   * this path only guarantees the readout is never stale. Cost per move is one
   * O(log n) binary search and a deduped state write (spec §27).
   */
  const trackHoverFromPointer = useCallback(
    (px: number, py: number) => {
      if (!transform) return;
      if (!insidePlot(px, py)) {
        setHoverIndex(null);
        return;
      }
      const t = toData(px, py, transform).t;
      const index = nearestIndexByTime(pointsRef.current, t);
      setHoverIndex(index >= 0 ? index : null);
    },
    [transform, insidePlot]
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!transform) return;
      const { px, py } = localPoint(event);
      trackHoverFromPointer(px, py);

      if (drag) {
        const dataPoint = toData(px, py, transform);
        if (drag.kind === "level") setDrag({ ...drag, price: dataPoint.p });
        else setDrag({ ...drag, point: dataPoint });
        return;
      }

      if (draft) {
        const dataPoint = toData(px, py, transform);
        setDraft((prev) => (prev ? { ...prev, to: dataPoint } : prev));
        return;
      }

      if (!insidePlot(px, py)) {
        setHoveredDrawingId(null);
        setHoveredLevelId(null);
        setHoveredAnchor(false);
        return;
      }

      const selectedLayer = controller.selectedId
        ? layers.find((layer) => layer.shape.id === controller.selectedId) ?? null
        : null;
      if (selectedLayer && !selectedLayer.shape.locked && hitTestLayerAnchor(selectedLayer, px, py) >= 0) {
        setHoveredAnchor(true);
        setHoveredDrawingId(selectedLayer.shape.id);
        setHoveredLevelId(null);
        return;
      }
      setHoveredAnchor(false);

      const shapeHit = hitTestDrawings(layers, px, py);
      if (shapeHit) {
        setHoveredDrawingId(shapeHit.shape.id);
        setHoveredLevelId(null);
        return;
      }
      setHoveredDrawingId(null);

      const levelHit = hitTestPriceLevels(levelLayers, py);
      setHoveredLevelId(levelHit?.level.id ?? null);
    },
    [controller.selectedId, drag, draft, insidePlot, layers, levelLayers, localPoint, trackHoverFromPointer, transform]
  );

  const handlePointerUp = useCallback(() => {
    if (!drag) return;
    if (drag.kind === "move") {
      const dt = drag.point.t - drag.start.t;
      const dp = drag.point.p - drag.start.p;
      if (dt !== 0 || dp !== 0) controller.onMoveDrawing(drag.id, dt, dp);
    } else if (drag.kind === "anchor") {
      controller.onResizeDrawing(drag.id, drag.anchor, drag.point);
    } else {
      controller.onMovePriceLevel(drag.id, drag.price);
    }
    setDrag(null);
  }, [controller, drag]);

  const handlePointerLeave = useCallback(() => {
    if (drag) return;
    setHoverIndex(null);
    setHoveredDrawingId(null);
    setHoveredLevelId(null);
    setHoveredAnchor(false);
  }, [drag]);

  /**
   * Escape unwinds the cursor mode, exactly as the toolbar promises:
   *   1. a half-placed shape is abandoned,
   *   2. a selected annotation is deselected,
   *   3. an armed tool is disarmed (which also restores panning).
   */
  useEffect(() => {
    if (!isActive) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (draft) {
        setDraft(null);
        return;
      }
      if (drag) {
        setDrag(null);
        return;
      }
      if (controller.priceLevelTool) {
        controller.onDisarmTool();
        return;
      }
      if (controller.selectedId) {
        controller.onSelect(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [controller, draft, drag, isActive]);

  const cursor = useMemo(() => {
    if (controller.priceLevelTool || controller.tool !== "select") return "crosshair";
    if (drag) return drag.kind === "level" ? "ns-resize" : "grabbing";
    if (hoveredAnchor) return "pointer";
    if (hoveredDrawingId) return "move";
    if (hoveredLevelId) return "ns-resize";
    return "crosshair";
  }, [controller.priceLevelTool, controller.tool, drag, hoveredAnchor, hoveredDrawingId, hoveredLevelId]);

  const touchAction = controller.tool !== "select" || controller.priceLevelTool || drag ? "none" : "auto";

  return (
    <div className="chart-surface">
      <div
        ref={boxRef}
        className="chart-surface-plot"
        style={{ cursor, touchAction }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onPointerLeave={handlePointerLeave}
        onContextMenu={(event) => {
          if (draft) {
            event.preventDefault();
            setDraft(null);
          }
        }}
      >
        <ChartPlot
          data={data}
          layout={layout}
          config={config}
          onRelayout={handleRelayout}
          onHover={handleHover}
          onUnhover={handleUnhover}
        />
        <AnnotationLayer
          width={size.width}
          height={size.height}
          transform={transform}
          layers={layers}
          levels={levelLayers}
          selectedDrawingId={controller.selectedId}
          hoveredDrawingId={hoveredDrawingId}
          hoveredLevelId={hoveredLevelId}
          draftLayer={draftLayer}
          lastClose={lastClose}
          showLastPrice={instance.settings.lastPriceLine}
        />
      </div>

      <ChartHud
        instance={instance}
        points={points}
        lines={lines}
        transform={transform}
        hoverIndex={hoverIndex}
        showLegend={instance.settings.legend}
      />
    </div>
  );
}
