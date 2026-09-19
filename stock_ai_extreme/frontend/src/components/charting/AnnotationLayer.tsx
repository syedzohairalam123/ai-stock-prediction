/**
 * Phase 11 — annotation overlay (spec §15, §16, §19, §21, §22).
 *
 * Everything the analyst places on a chart is painted here, on top of the Plotly
 * canvas, in a single SVG that shares the plot area's geometry. The layer is
 * presentational only (`pointer-events: none`) — all interaction is routed
 * through the panel so hit testing and rendering can never disagree.
 *
 * Because the parent hands us a `PlotTransform`, positions are recomputed from
 * data space on every frame: zooming, resizing, switching timeframe or moving the
 * viewport all keep a level glued to its price.
 */
import type { CSSProperties } from "react";
import type { DrawingLayer, PriceLevelLayer } from "../../lib/charting/annotations";
import type { PlotTransform } from "../../lib/charting/geometry";
import { toPixel } from "../../lib/charting/geometry";
import { priceLevelDisplayText, priceLevelMeta } from "../../lib/charting/drawings";
import { formatPrice } from "../../lib/charting/drawings";

interface AnnotationLayerProps {
  width: number;
  height: number;
  transform: PlotTransform | null;
  layers: DrawingLayer[];
  levels: PriceLevelLayer[];
  selectedDrawingId: string | null;
  hoveredDrawingId: string | null;
  hoveredLevelId: string | null;
  /** The shape currently being placed (rubber band). */
  draftLayer: DrawingLayer | null;
  lastClose: number | null;
  showLastPrice: boolean;
}

const DASH_ARRAY: Record<string, string | undefined> = {
  solid: undefined,
  dash: "6 4",
  dot: "1.5 3.5",
};

export default function AnnotationLayer({
  width,
  height,
  transform,
  layers,
  levels,
  selectedDrawingId,
  hoveredDrawingId,
  hoveredLevelId,
  draftLayer,
  lastClose,
  showLastPrice,
}: AnnotationLayerProps) {
  if (width <= 0 || height <= 0) return null;

  const lastY = transform && lastClose !== null ? toPixel({ t: transform.xRange[0], p: lastClose }, transform).y : null;

  return (
    <svg
      className="chart-svg"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
      focusable="false"
    >
      {/* Last traded price — a reference, not an editable annotation. */}
      {showLastPrice && transform && lastY !== null && lastY >= 0 && lastY <= height && (
        <g className="chart-svg-last">
          <line
            x1={transform.rect.left}
            x2={transform.rect.left + transform.rect.width}
            y1={lastY}
            y2={lastY}
            stroke="var(--chart-last, #9daed9)"
            strokeWidth={1}
            strokeDasharray="4 4"
          />
          <g transform={`translate(${transform.rect.left + transform.rect.width - 4} ${lastY - 8})`}>
            <rect
              className="chart-svg-chip"
              x={-62}
              y={-10}
              width={62}
              height={15}
              rx={4}
              fill="var(--chart-chip-bg, rgba(94,159,232,.16))"
              stroke="var(--chart-chip-border, rgba(94,159,232,.5))"
            />
            <text className="chart-svg-chip-text" x={-4} y={1} textAnchor="end" fontSize={10}>
              {formatPrice(lastClose ?? 0)}
            </text>
          </g>
        </g>
      )}

      {/* Analyst price levels (spec §19–§21) */}
      {transform &&
        levels.map(({ level, y }) => {
          const meta = priceLevelMeta(level.type);
          const hovered = hoveredLevelId === level.id;
          const selected = selectedDrawingId === level.id;
          // Name + live price, never a price baked into the label: dragging the
          // line up must move the number with it (spec §21).
          const chipText = priceLevelDisplayText(level);
          const chipWidth = Math.min(210, Math.max(74, chipText.length * 5.6 + 16));
          return (
            <g key={level.id} className="chart-svg-level" data-hovered={hovered || selected ? "true" : undefined}>
              <line
                x1={transform.rect.left}
                x2={transform.rect.left + transform.rect.width}
                y1={y}
                y2={y}
                stroke={meta.color}
                strokeWidth={hovered || selected ? 1.8 : 1.2}
                strokeDasharray={DASH_ARRAY[meta.dash]}
                opacity={level.locked ? 0.75 : 1}
              />
              {/* Drag handle: the interactive gesture the panel listens for. */}
              <circle cx={transform.rect.left + 4} cy={y} r={hovered || selected ? 4.5 : 3} fill={meta.color} />
              <g transform={`translate(${transform.rect.left + 12} ${y - 8})`}>
                <rect
                  className="chart-svg-chip"
                  x={0}
                  y={-10}
                  width={chipWidth}
                  height={15}
                  rx={4}
                  fill="var(--chart-chip-bg, rgba(15,20,35,.72))"
                  stroke={meta.color}
                  strokeOpacity={0.55}
                />
                <text className="chart-svg-chip-text" x={6} y={1} fontSize={10}>
                  {chipText}
                  {level.locked ? " 🔒" : ""}
                </text>
              </g>
            </g>
          );
        })}

      {/* Drawings (spec §15–§18) */}
      {layers.map((layer) => {
        const { shape, geometry } = layer;
        const selected = selectedDrawingId === shape.id;
        const hovered = hoveredDrawingId === shape.id;
        const style: CSSProperties = {};
        return (
          <g key={shape.id} className="chart-svg-drawing" data-selected={selected ? "true" : undefined}>
            {geometry.closed && shape.style.fillOpacity > 0 && (
              <path
                d={geometry.path}
                fill={shape.style.color}
                fillOpacity={shape.style.fillOpacity}
                stroke="none"
              />
            )}
            <path
              d={geometry.path}
              fill="none"
              stroke={shape.style.color}
              strokeWidth={hovered || selected ? shape.style.width + 0.8 : shape.style.width}
              strokeDasharray={DASH_ARRAY[shape.style.dash]}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={shape.locked ? 0.8 : 1}
              style={style}
            />
            {(selected || hovered) && (
              <path
                d={geometry.path}
                fill="none"
                stroke={shape.style.color}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.55}
                transform="translate(0,0)"
              />
            )}
            {selected &&
              geometry.anchors.map((anchor, index) => (
                <g key={`${shape.id}-anchor-${index}`} className="chart-svg-anchor">
                  <circle cx={anchor.x} cy={anchor.y} r={7} fill="transparent" />
                  <rect
                    x={anchor.x - 3.5}
                    y={anchor.y - 3.5}
                    width={7}
                    height={7}
                    rx={1.5}
                    fill="var(--surface, #202020)"
                    stroke={shape.style.color}
                    strokeWidth={1.6}
                  />
                </g>
              ))}
          </g>
        );
      })}

      {/* Live preview of the shape being placed. */}
      {draftLayer && (
        <g className="chart-svg-draft">
          {draftLayer.geometry.closed && (
            <path d={draftLayer.geometry.path} fill={draftLayer.shape.style.color} fillOpacity={0.08} stroke="none" />
          )}
          <path
            d={draftLayer.geometry.path}
            fill="none"
            stroke={draftLayer.shape.style.color}
            strokeWidth={draftLayer.shape.style.width}
            strokeDasharray="6 4"
          />
          {draftLayer.geometry.anchors.map((anchor, index) => (
            <circle key={`draft-anchor-${index}`} cx={anchor.x} cy={anchor.y} r={3} fill={draftLayer.shape.style.color} />
          ))}
        </g>
      )}
    </svg>
  );
}
