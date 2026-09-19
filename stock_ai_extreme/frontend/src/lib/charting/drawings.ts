/**
 * Phase 11 — drawing & price-level data-model helpers (spec §15–§21).
 *
 * Everything here is pure: create / translate / re-anchor an annotation, or
 * describe a toolbar entry. Shapes live in data space (see `geometry.ts`), so
 * the only mutations that make sense are "move these anchors by Δt/Δp" — never
 * "set this pixel".
 */
import type {
  DrawingShape,
  DrawingStyle,
  DrawingTool,
  DrawingType,
  Point2D,
  PriceLevel,
  PriceLevelType,
} from "./types";

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

let sequence = 0;

/**
 * Stable unique id. `crypto.randomUUID` when available (all evergreen browsers
 * and Node 19+), with a monotonic fallback so ids are never duplicated inside
 * one session even on an old runtime.
 */
export function annotationId(prefix: string): string {
  sequence += 1;
  const runtimeUuid = typeof globalThis.crypto?.randomUUID === "function" ? globalThis.crypto.randomUUID() : null;
  const tail = runtimeUuid ?? `${Date.now().toString(36)}-${sequence.toString(36)}`;
  return `${prefix}-${tail}`;
}

// ---------------------------------------------------------------------------
// Drawing catalog
// ---------------------------------------------------------------------------

export interface DrawingToolMeta {
  id: DrawingTool;
  label: string;
  hint: string;
}

/** The drawing toolbar (spec §18), in display order. */
export const DRAWING_TOOL_META: DrawingToolMeta[] = [
  { id: "select", label: "Select", hint: "Select, move and resize existing drawings" },
  { id: "trendline", label: "Trend Line", hint: "Click a start point, then an end point" },
  { id: "rectangle", label: "Rectangle", hint: "Drag two opposite corners of the zone" },
  { id: "circle", label: "Circle", hint: "Drag the circle's bounding box" },
  { id: "parabola", label: "Parabola", hint: "First click sets the vertex, second a point on the curve" },
  { id: "semicircle", label: "Semicircle", hint: "Drag the semicircle's diameter" },
];

export const DEFAULT_DRAWING_STYLE: DrawingStyle = {
  color: "#5E9FE8",
  width: 1.8,
  dash: "solid",
  fillOpacity: 0.12,
};

/** Palette offered in the drawing-style menu. */
export const DRAWING_COLORS = ["#5E9FE8", "#72BC8F", "#E97366", "#DE9255", "#BF8EDA", "#2dd4bf", "#facc15", "#9daed9"];

// ---------------------------------------------------------------------------
// Drawing factory + mutations
// ---------------------------------------------------------------------------

export function createDrawing(
  type: DrawingType,
  coordinates: Point2D[],
  style: Partial<DrawingStyle> = {}
): DrawingShape {
  return {
    id: annotationId(type),
    type,
    coordinates: coordinates.map((c) => ({ t: c.t, p: c.p })),
    style: { ...DEFAULT_DRAWING_STYLE, ...style },
    visible: true,
    locked: false,
  };
}

/** Shift a whole shape by Δt bars / Δp price. */
export function translateDrawing(shape: DrawingShape, dt: number, dp: number): DrawingShape {
  return {
    ...shape,
    coordinates: shape.coordinates.map((c) => ({ t: c.t + dt, p: c.p + dp })),
  };
}

/** Replace one anchor (resize / reshape). */
export function moveAnchor(shape: DrawingShape, index: number, point: Point2D): DrawingShape {
  if (index < 0 || index >= shape.coordinates.length) return shape;
  const coordinates = shape.coordinates.map((c, i) => (i === index ? { t: point.t, p: point.p } : { ...c }));
  return { ...shape, coordinates };
}

/** Patch style / visibility / lock without touching geometry. */
export function patchDrawing(shape: DrawingShape, patch: Partial<Omit<DrawingShape, "id">>): DrawingShape {
  return { ...shape, ...patch, style: patch.style ? { ...shape.style, ...patch.style } : shape.style };
}

/** Data-space bounding box — used to place an export label or clamp a drag. */
export function drawingBounds(shape: DrawingShape): { tMin: number; tMax: number; pMin: number; pMax: number } | null {
  if (shape.coordinates.length === 0) return null;
  let tMin = Infinity;
  let tMax = -Infinity;
  let pMin = Infinity;
  let pMax = -Infinity;
  for (const c of shape.coordinates) {
    if (!Number.isFinite(c.t) || !Number.isFinite(c.p)) continue;
    if (c.t < tMin) tMin = c.t;
    if (c.t > tMax) tMax = c.t;
    if (c.p < pMin) pMin = c.p;
    if (c.p > pMax) pMax = c.p;
  }
  if (!Number.isFinite(tMin)) return null;
  return { tMin, tMax, pMin, pMax };
}

/** Does this shape depend on two anchors (i.e. is it still being drawn)? */
export function isAnchorShape(type: DrawingType): boolean {
  return type === "trendline" || type === "rectangle" || type === "circle" || type === "parabola" || type === "semicircle";
}

// ---------------------------------------------------------------------------
// Price levels (spec §19, §20)
// ---------------------------------------------------------------------------

export interface PriceLevelMeta {
  type: PriceLevelType;
  label: string;
  short: string;
  color: string;
  dash: "solid" | "dash" | "dot";
  hint: string;
}

export const PRICE_LEVEL_META: PriceLevelMeta[] = [
  { type: "SUPPORT", label: "Support", short: "SUP", color: "#72BC8F", dash: "dash", hint: "Click the chart at the support price" },
  { type: "RESISTANCE", label: "Resistance", short: "RES", color: "#E97366", dash: "dash", hint: "Click the chart at the resistance price" },
  { type: "ENTRY", label: "Entry", short: "ENT", color: "#5E9FE8", dash: "solid", hint: "Click the chart at your intended entry" },
  { type: "STOP_LOSS", label: "Stop Loss", short: "SL", color: "#DE9255", dash: "dot", hint: "Click the chart at your stop-loss level" },
  { type: "TARGET", label: "Target", short: "TGT", color: "#BF8EDA", dash: "dot", hint: "Click the chart at your profit target" },
];

export function priceLevelMeta(type: PriceLevelType): PriceLevelMeta {
  return PRICE_LEVEL_META.find((m) => m.type === type) ?? PRICE_LEVEL_META[0];
}

/** Human price rendering shared with the price axis (2dp, thousands separated). */
export function formatPrice(price: number, digits = 2): string {
  if (!Number.isFinite(price)) return "—";
  return price.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/**
 * Default *name* for a level — `"Support"`, not `"Support 1,234.50"`.
 *
 * The price deliberately lives in `price` and is rendered from there
 * (`priceLevelDisplayText`), so dragging a level can never leave a label behind
 * quoting the old price (spec §21: the line is attached to its price).
 */
export function defaultPriceLevelLabel(type: PriceLevelType): string {
  return priceLevelMeta(type).label;
}

/** What a level chip/tooltip shows: its name plus its *live* price. */
export function priceLevelDisplayText(level: Pick<PriceLevel, "type" | "price" | "label">): string {
  const name = level.label?.trim() ? level.label.trim() : priceLevelMeta(level.type).label;
  return `${name} ${formatPrice(level.price)}`;
}

export function createPriceLevel(
  type: PriceLevelType,
  price: number,
  label?: string
): PriceLevel {
  return {
    id: annotationId(`level-${type.toLowerCase()}`),
    type,
    price,
    label: label?.trim() ? label.trim() : defaultPriceLevelLabel(type),
    visible: true,
    locked: false,
  };
}

/** Sorted, cheapest-first, for stable list rendering and last-price proximity. */
export function sortPriceLevels(levels: readonly PriceLevel[]): PriceLevel[] {
  return [...levels].sort((a, b) => a.price - b.price);
}

/**
 * Next free price level of a type. Repeat placements stack by a small ATR-like
 * offset instead of landing exactly on top of each other (which would look like
 * a failed click).
 */
export function nudgeDuplicatePrice(levels: readonly PriceLevel[], price: number, step: number): number {
  if (!levels.some((l) => Math.abs(l.price - price) < step * 0.25)) return price;
  let candidate = price + step;
  let guard = 0;
  while (levels.some((l) => Math.abs(l.price - candidate) < step * 0.25) && guard < 24) {
    candidate += step;
    guard += 1;
  }
  return candidate;
}
