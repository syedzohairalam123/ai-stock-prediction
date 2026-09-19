/**
 * Phase 11 — annotation model (render layers + hit testing).
 *
 * Bridges the stored, data-space annotations to the SVG layer: one pass computes
 * every drawing's pixel geometry, and the same pass feeds both rendering and hit
 * testing. Keeping them together is what guarantees "clickable where it is
 * drawn" — a separate hit-test implementation would inevitably drift.
 */
import { anchorAt, drawingGeometry, hitTest, priceToY, type DrawingGeometry, type PlotTransform } from "./geometry";
import type { DrawingShape, PriceLevel } from "./types";

export interface DrawingLayer {
  shape: DrawingShape;
  geometry: DrawingGeometry;
}

/** Renderable drawings, in paint order (last = on top). */
export function buildDrawingLayers(drawings: readonly DrawingShape[], tf: PlotTransform | null): DrawingLayer[] {
  if (!tf) return [];
  const layers: DrawingLayer[] = [];
  for (const shape of drawings) {
    if (!shape.visible) continue;
    const geometry = drawingGeometry(shape, tf);
    if (geometry && geometry.path) layers.push({ shape, geometry });
  }
  return layers;
}

/** Topmost drawing under the pointer (searches the newest first). */
export function hitTestDrawings(layers: readonly DrawingLayer[], px: number, py: number, tolerance = 7): DrawingLayer | null {
  for (let i = layers.length - 1; i >= 0; i--) {
    if (hitTest(layers[i].geometry, px, py, tolerance)) return layers[i];
  }
  return null;
}

/** Anchor index under the pointer for a single layer, or -1. */
export function hitTestLayerAnchor(layer: DrawingLayer, px: number, py: number, tolerance = 9): number {
  return anchorAt(layer.geometry, px, py, tolerance);
}

export interface PriceLevelLayer {
  level: PriceLevel;
  y: number;
}

/** Visible price levels with their current pixel row. */
export function buildPriceLevelLayers(levels: readonly PriceLevel[], tf: PlotTransform | null): PriceLevelLayer[] {
  if (!tf) return [];
  return levels
    .filter((level) => level.visible && Number.isFinite(level.price))
    .map((level) => ({ level, y: priceToY(level.price, tf) }))
    .filter((layer) => Number.isFinite(layer.y));
}

/** Price level whose line is under the pointer. */
export function hitTestPriceLevels(
  layers: readonly PriceLevelLayer[],
  py: number,
  tolerance = 5
): PriceLevelLayer | null {
  let best: PriceLevelLayer | null = null;
  let bestDistance = Infinity;
  for (const layer of layers) {
    const distance = Math.abs(layer.y - py);
    if (distance <= tolerance && distance < bestDistance) {
      best = layer;
      bestDistance = distance;
    }
  }
  return best;
}

/**
 * Contract a shape's hit box by a few pixels so the drag handle of a very small
 * shape is still reachable, and expand it slightly for thin lines.
 */
export function layerIsTiny(layer: DrawingLayer, threshold = 6): boolean {
  const { bounds } = layer.geometry;
  return Math.abs(bounds.right - bounds.left) < threshold || Math.abs(bounds.bottom - bounds.top) < threshold;
}
