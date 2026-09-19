/**
 * Phase 11 — chart geometry: the single place that converts between **data
 * space** (time-axis value `t` in epoch ms + price `p`) and **screen pixels**.
 *
 * Why this module exists
 * ----------------------
 * The chart plots on a date x-axis and a price y-axis, and every stored
 * annotation keeps its meaning in that space:
 *
 *   t = time-axis value (epoch ms; fractional values allowed)
 *   p = price
 *
 * Nothing in the workspace is allowed to persist pixel positions. A drawing is
 * therefore still correct after a zoom, a resize, a timeframe switch or a
 * viewport pan — the pixels are recomputed from the anchors on every frame
 * (spec §16, §21).
 *
 * Curve shapes (circle / semicircle) are *parametrized* in pixels but driven by
 * two data-space anchors, which is the only way a "circle" can still look round
 * on a screen whose price/time scales are wildly different.
 */
import type { DrawingShape, Point2D } from "./types";

/** Plot area (the rectangle inside the axes), in container-relative pixels. */
export interface PlotRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** The affine mapping from data space to pixels for one rendered frame. */
export interface PlotTransform {
  rect: PlotRect;
  xRange: [number, number];
  yRange: [number, number];
}

export interface PixelPoint {
  x: number;
  y: number;
}

export interface PixelBounds {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** How many segments the curved primitives are sampled into. */
export const CURVE_SAMPLES = 64;

/**
 * Build a transform, or `null` when the frame cannot be mapped (zero-size plot
 * area or a degenerate axis range). Callers must treat `null` as "don't draw"
 * rather than guessing — a guessed transform is how a drawing ends up in the
 * wrong place.
 */
export function makeTransform(
  rect: PlotRect,
  xRange: [number, number],
  yRange: [number, number]
): PlotTransform | null {
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (!Number.isFinite(xRange[0]) || !Number.isFinite(xRange[1])) return null;
  if (!Number.isFinite(yRange[0]) || !Number.isFinite(yRange[1])) return null;
  if (xRange[0] === xRange[1] || yRange[0] === yRange[1]) return null;
  return { rect, xRange, yRange };
}

/** Data point → pixel point. */
export function toPixel(point: Point2D, tf: PlotTransform): PixelPoint {
  const { rect, xRange, yRange } = tf;
  const nx = (point.t - xRange[0]) / (xRange[1] - xRange[0]);
  const ny = (yRange[1] - point.p) / (yRange[1] - yRange[0]);
  return { x: rect.left + nx * rect.width, y: rect.top + ny * rect.height };
}

/** Pixel point → data point (inverse of `toPixel`). */
export function toData(px: number, py: number, tf: PlotTransform): Point2D {
  const { rect, xRange, yRange } = tf;
  const nx = (px - rect.left) / rect.width;
  const ny = (py - rect.top) / rect.height;
  return {
    t: xRange[0] + nx * (xRange[1] - xRange[0]),
    p: yRange[1] - ny * (yRange[1] - yRange[0]),
  };
}

/** Price → pixel Y (used by the horizontal price-level lines). */
export function priceToY(price: number, tf: PlotTransform): number {
  return toPixel({ t: tf.xRange[0], p: price }, tf).y;
}

/** Pixel Y → price. */
export function yToPrice(y: number, tf: PlotTransform): number {
  return toData(tf.rect.left, y, tf).p;
}

/**
 * Geometric render description of one drawing.
 *
 * `path` is a ready-to-write SVG path in pixel space; `anchors` are the
 * draggable control points; `bounds` is the hit-test box.
 */
export interface DrawingGeometry {
  path: string;
  closed: boolean;
  anchors: PixelPoint[];
  bounds: PixelBounds;
}

function boundsOf(points: PixelPoint[]): PixelBounds {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const p of points) {
    if (p.x < left) left = p.x;
    if (p.x > right) right = p.x;
    if (p.y < top) top = p.y;
    if (p.y > bottom) bottom = p.y;
  }
  return { left, top, right, bottom };
}

function pathFromPoints(points: PixelPoint[], closed: boolean): string {
  if (points.length === 0) return "";
  const head = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  const rest = points
    .slice(1)
    .map((p) => `L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
  return closed ? `${head} ${rest} Z` : `${head} ${rest}`;
}

/**
 * Sample a `circle` defined by two anchors: the anchors sit on the ellipse's
 * bounding box corners, so the shape is an on-screen ellipse inscribed in the
 * rectangle the user dragged. Radii are derived from the anchor pixels, which is
 * what keeps it glued to the chart through zoom.
 */
function circlePoints(a: PixelPoint, b: PixelPoint): PixelPoint[] {
  const cx = (a.x + b.x) / 2;
  const cy = (a.y + b.y) / 2;
  const rx = Math.abs(b.x - a.x) / 2;
  const ry = Math.abs(b.y - a.y) / 2;
  const out: PixelPoint[] = [];
  for (let i = 0; i < CURVE_SAMPLES; i++) {
    const theta = (i / CURVE_SAMPLES) * Math.PI * 2;
    out.push({ x: cx + Math.cos(theta) * rx, y: cy + Math.sin(theta) * ry });
  }
  return out;
}

/**
 * Sample a `semicircle` whose diameter is the segment A→B, bulging towards the
 * top of the screen. Screen-round by construction (`r = |AB| / 2`), and both
 * endpoints stay exactly on their data-space anchors.
 */
function semicirclePoints(a: PixelPoint, b: PixelPoint): PixelPoint[] {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return [a, b];
  const r = len / 2;
  const cx = (a.x + b.x) / 2;
  const cy = (a.y + b.y) / 2;
  // Unit vector along the diameter, and a normal that always points "up".
  let ux = dx / len;
  let uy = dy / len;
  let nx = -uy;
  let ny = ux;
  if (ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  const out: PixelPoint[] = [];
  for (let i = 0; i <= CURVE_SAMPLES; i++) {
    const theta = (i / CURVE_SAMPLES) * Math.PI;
    const c = Math.cos(theta);
    const s = Math.sin(theta);
    out.push({ x: cx + c * r * ux + s * r * nx, y: cy + c * r * uy + s * r * ny });
  }
  return out;
}

/**
 * Sample a `parabola`: the first anchor is the vertex, the second is a point the
 * curve must pass through. The axis is vertical in *data* space (price), so the
 * shape keeps its meaning when the viewport changes, and it is drawn symmetric
 * about the vertex over twice the anchor distance.
 */
export function parabolaPoints(a: Point2D, b: Point2D, tf: PlotTransform): PixelPoint[] {
  const dt = b.t - a.t;
  if (Math.abs(dt) < 1e-9) {
    // Vertical drag: no horizontal extent to curve over — render the segment.
    return [toPixel(a, tf), toPixel(b, tf)];
  }
  const m = (b.p - a.p) / (dt * dt);
  const span = Math.abs(dt);
  const from = a.t - span;
  const to = a.t + span;
  const out: PixelPoint[] = [];
  for (let i = 0; i <= CURVE_SAMPLES; i++) {
    const t = from + ((to - from) * i) / CURVE_SAMPLES;
    const p = a.p + m * (t - a.t) * (t - a.t);
    out.push(toPixel({ t, p }, tf));
  }
  return out;
}

/**
 * Build the renderable geometry for one drawing.
 * Returns `null` when the shape is not currently renderable (missing anchors or
 * an unusable transform) — the chart then simply omits it instead of drawing
 * nonsense.
 */
export function drawingGeometry(shape: DrawingShape, tf: PlotTransform): DrawingGeometry | null {
  const coords = shape.coordinates;
  if (coords.length < 2) return null;

  const aData = coords[0];
  const bData = coords[1];
  if (!Number.isFinite(aData.t) || !Number.isFinite(aData.p)) return null;
  if (!Number.isFinite(bData.t) || !Number.isFinite(bData.p)) return null;

  const a = toPixel(aData, tf);
  const b = toPixel(bData, tf);
  const anchors: PixelPoint[] = [a, b];

  switch (shape.type) {
    case "trendline": {
      return { path: pathFromPoints([a, b], false), closed: false, anchors, bounds: boundsOf([a, b]) };
    }
    case "rectangle": {
      const corners: PixelPoint[] = [
        { x: a.x, y: a.y },
        { x: b.x, y: a.y },
        { x: b.x, y: b.y },
        { x: a.x, y: b.y },
      ];
      return { path: pathFromPoints(corners, true), closed: true, anchors, bounds: boundsOf(corners) };
    }
    case "circle": {
      const pts = circlePoints(a, b);
      return { path: pathFromPoints(pts, true), closed: true, anchors, bounds: boundsOf(pts) };
    }
    case "semicircle": {
      const pts = semicirclePoints(a, b);
      return { path: pathFromPoints(pts, false), closed: false, anchors, bounds: boundsOf(pts) };
    }
    case "parabola": {
      const pts = parabolaPoints(aData, bData, tf);
      return { path: pathFromPoints(pts, false), closed: false, anchors, bounds: boundsOf(pts) };
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Hit testing (selection, drag, resize)
// ---------------------------------------------------------------------------

function distanceToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const vx = bx - ax;
  const vy = by - ay;
  const len2 = vx * vx + vy * vy;
  if (len2 === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * vx + (py - ay) * vy) / len2;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return Math.hypot(px - (ax + t * vx), py - (ay + t * vy));
}

/** Is `(px, py)` within `tolerance` px of the shape's outline or inside it? */
export function hitTest(geometry: DrawingGeometry, px: number, py: number, tolerance = 6): boolean {
  const { bounds } = geometry;
  if (
    px < bounds.left - tolerance ||
    px > bounds.right + tolerance ||
    py < bounds.top - tolerance ||
    py > bounds.bottom + tolerance
  ) {
    return false;
  }

  // The sampled path doubles as the hit polyline: parse it back from the
  // geometry's anchors is not possible for curves, so walk the `d` string.
  const points = parsePath(geometry.path);
  for (let i = 0; i < points.length - 1; i++) {
    const d = distanceToSegment(px, py, points[i].x, points[i].y, points[i + 1].x, points[i + 1].y);
    if (d <= tolerance) return true;
  }
  if (geometry.closed && points.length >= 3) {
    return pointInPolygon(px, py, points);
  }
  return false;
}

/** Minimal `M/L/Z` path reader — we only ever write those commands. */
export function parsePath(d: string): PixelPoint[] {
  const out: PixelPoint[] = [];
  const re = /([ML])\s+(-?[\d.]+)\s+(-?[\d.]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(d)) !== null) {
    out.push({ x: Number(m[2]), y: Number(m[3]) });
  }
  return out;
}

/** Even-odd ray casting. */
export function pointInPolygon(px: number, py: number, polygon: PixelPoint[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Index of the anchor under the pointer, or -1. */
export function anchorAt(geometry: DrawingGeometry, px: number, py: number, tolerance = 9): number {
  for (let i = 0; i < geometry.anchors.length; i++) {
    const a = geometry.anchors[i];
    if (Math.hypot(a.x - px, a.y - py) <= tolerance) return i;
  }
  return -1;
}

// ---------------------------------------------------------------------------
// Viewport helpers
// ---------------------------------------------------------------------------

export interface CandleBounds {
  xMin: number;
  xMax: number;
  yMin: number;
  yMax: number;
}

/**
 * Vertical fit for a candle series with a little headroom so the wick of the
 * extreme candle is not clipped against the frame.
 */
export function boundsOfCandles(
  candles: readonly { high: number; low: number }[],
  padRatio = 0.06
): { yMin: number; yMax: number } | null {
  if (candles.length === 0) return null;
  let yMin = Infinity;
  let yMax = -Infinity;
  for (const c of candles) {
    if (Number.isFinite(c.low) && c.low < yMin) yMin = c.low;
    if (Number.isFinite(c.high) && c.high > yMax) yMax = c.high;
  }
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) return null;
  if (yMin === yMax) {
    const bump = Math.abs(yMin) * 0.01 || 1;
    return { yMin: yMin - bump, yMax: yMax + bump };
  }
  const pad = (yMax - yMin) * padRatio;
  return { yMin: yMin - pad, yMax: yMax + pad };
}

/** Clamp a viewport so it can never invert or collapse. */
export function clampRange(range: [number, number], minSpan: number, lo: number, hi: number): [number, number] {
  let [a, b] = range;
  if (a > b) [a, b] = [b, a];
  const span = b - a;
  if (span < minSpan) {
    const mid = (a + b) / 2;
    a = mid - minSpan / 2;
    b = mid + minSpan / 2;
  }
  if (a < lo) {
    const shift = lo - a;
    a += shift;
    b += shift;
  }
  if (b > hi) {
    const shift = b - hi;
    a -= shift;
    b -= shift;
  }
  return [Math.max(lo, a), Math.min(hi, b)];
}

/** Half-open compare used when deciding whether a persisted view is still valid. */
export function rangesEqual(a: [number, number] | undefined, b: [number, number] | undefined): boolean {
  if (!a || !b) return false;
  return Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4;
}
