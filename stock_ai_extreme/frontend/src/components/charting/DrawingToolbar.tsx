/**
 * Phase 11 — drawing toolbar (spec §17, §18).
 *
 * Compact icon strip: the six cursor modes, then undo / redo / delete / clear.
 * When a drawing is selected its style controls (colour, width, dash, fill,
 * visibility, lock) appear inline, so shaping a zone never requires a second
 * panel. Every control has a tooltip and an explicit active state.
 */
import {
  AlignJustify,
  ArrowUpRight,
  Circle,
  Eraser,
  Eye,
  EyeOff,
  Layers,
  Lock,
  Minus,
  MousePointer2,
  MoveUpRight,
  MoveVertical,
  Redo2,
  Ruler,
  Spline,
  Square,
  Trash2,
  TrendingUp,
  Undo2,
  Unlock,
  Waves,
} from "lucide-react";
import type { ReactNode } from "react";
import type { DrawingShape, DrawingStyle, DrawingTool } from "../../lib/charting/types";
import { DRAWING_COLORS, DRAWING_TOOL_META } from "../../lib/charting/drawings";

const ICONS: Record<DrawingTool, ReactNode> = {
  select: <MousePointer2 size={15} />,
  trendline: <TrendingUp size={15} />,
  ray: <MoveUpRight size={15} />,
  hline: <Minus size={15} />,
  vline: <MoveVertical size={15} />,
  channel: <Layers size={15} />,
  rectangle: <Square size={15} />,
  circle: <Circle size={15} />,
  parabola: <Spline size={15} />,
  semicircle: <Waves size={15} />,
  "fib-retracement": <AlignJustify size={15} />,
  "fib-extension": <ArrowUpRight size={15} />,
  measure: <Ruler size={15} />,
};

interface DrawingToolbarProps {
  tool: DrawingTool;
  drawingCount: number;
  selected: DrawingShape | null;
  canUndo: boolean;
  canRedo: boolean;
  onTool: (tool: DrawingTool) => void;
  onUndo: () => void;
  onRedo: () => void;
  onDelete: () => void;
  onClear: () => void;
  onStyle: (patch: Partial<DrawingStyle>) => void;
  onToggleVisible: () => void;
  onToggleLock: () => void;
  disabled?: boolean;
}

export default function DrawingToolbar({
  tool,
  drawingCount,
  selected,
  canUndo,
  canRedo,
  onTool,
  onUndo,
  onRedo,
  onDelete,
  onClear,
  onStyle,
  onToggleVisible,
  onToggleLock,
  disabled = false,
}: DrawingToolbarProps) {
  return (
    <div className="chart-toolgroup" role="toolbar" aria-label="Drawing tools">
      {DRAWING_TOOL_META.map((meta) => (
        <button
          key={meta.id}
          type="button"
          className={`chart-icon-btn${tool === meta.id ? " on" : ""}`}
          onClick={() => onTool(meta.id)}
          aria-pressed={tool === meta.id}
          aria-label={meta.label}
          title={`${meta.label} — ${meta.hint}`}
          disabled={disabled}
        >
          {ICONS[meta.id]}
        </button>
      ))}

      <span className="chart-toolgroup-sep" aria-hidden="true" />

      <button
        type="button"
        className="chart-icon-btn"
        onClick={onUndo}
        disabled={!canUndo || disabled}
        aria-label="Undo annotation change"
        title="Undo (annotation changes)"
      >
        <Undo2 size={15} />
      </button>
      <button
        type="button"
        className="chart-icon-btn"
        onClick={onRedo}
        disabled={!canRedo || disabled}
        aria-label="Redo annotation change"
        title="Redo"
      >
        <Redo2 size={15} />
      </button>
      <button
        type="button"
        className="chart-icon-btn"
        onClick={onDelete}
        disabled={!selected || disabled}
        aria-label="Delete selected annotation"
        title={selected ? "Delete the selected annotation (Del)" : "Select an annotation to delete"}
      >
        <Trash2 size={15} />
      </button>
      <button
        type="button"
        className="chart-icon-btn"
        onClick={onClear}
        disabled={drawingCount === 0 || disabled}
        aria-label="Clear all drawings"
        title={`Clear all drawings${drawingCount ? ` (${drawingCount})` : ""}`}
      >
        <Eraser size={15} />
      </button>

      {selected && (
        <>
          <span className="chart-toolgroup-sep" aria-hidden="true" />
          <div className="chart-style-row" aria-label={`Style for ${selected.type}`}>
            <div className="chart-swatches">
              {DRAWING_COLORS.map((color) => (
                <button
                  key={color}
                  type="button"
                  className={`chart-swatch${selected.style.color.toLowerCase() === color.toLowerCase() ? " on" : ""}`}
                  style={{ background: color }}
                  onClick={() => onStyle({ color })}
                  aria-label={`Colour ${color}`}
                  title={`Colour ${color}`}
                />
              ))}
            </div>
            <label className="chart-ind-field" title="Line width">
              <span className="chart-sr">Line width</span>
              <input
                type="number"
                min={1}
                max={6}
                step={0.2}
                value={selected.style.width}
                onChange={(event) => {
                  const width = Number(event.target.value);
                  if (Number.isFinite(width)) onStyle({ width: Math.max(1, Math.min(6, width)) });
                }}
                aria-label="Line width"
              />
            </label>
            <select
              value={selected.style.dash}
              onChange={(event) => onStyle({ dash: event.target.value as DrawingStyle["dash"] })}
              aria-label="Line dash"
              title="Line style"
            >
              <option value="solid">Solid</option>
              <option value="dash">Dashed</option>
              <option value="dot">Dotted</option>
            </select>
            <label className="chart-ind-field" title="Fill opacity">
              <span className="chart-sr">Fill opacity</span>
              <input
                type="number"
                min={0}
                max={0.6}
                step={0.02}
                value={selected.style.fillOpacity}
                onChange={(event) => {
                  const fillOpacity = Number(event.target.value);
                  if (Number.isFinite(fillOpacity)) onStyle({ fillOpacity: Math.max(0, Math.min(0.6, fillOpacity)) });
                }}
                aria-label="Fill opacity"
              />
            </label>
            <button
              type="button"
              className={`chart-icon-btn${selected.visible ? "" : " off"}`}
              onClick={onToggleVisible}
              aria-pressed={!selected.visible}
              aria-label={selected.visible ? "Hide annotation" : "Show annotation"}
              title={selected.visible ? "Hide annotation" : "Show annotation"}
            >
              {selected.visible ? <Eye size={14} /> : <EyeOff size={14} />}
            </button>
            <button
              type="button"
              className={`chart-icon-btn${selected.locked ? " on" : ""}`}
              onClick={onToggleLock}
              aria-pressed={selected.locked}
              aria-label={selected.locked ? "Unlock annotation" : "Lock annotation"}
              title={selected.locked ? "Unlock annotation" : "Lock annotation (blocks move/resize)"}
            >
              {selected.locked ? <Lock size={14} /> : <Unlock size={14} />}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
