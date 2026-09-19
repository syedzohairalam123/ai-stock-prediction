/**
 * Phase 12 — layout engine (spec §4, §5, §9, §10, §18).
 *
 * Pure grid maths — no React, no DOM, no imports beyond the type model. The
 * whole module is unit-testable in Node exactly like the Phase-11 charting
 * engine, which is why every rule the spec names (bounds, collisions, min/max
 * sizes, duplicate limits, add/remove/hide) is expressed here once.
 *
 * The grid is 12 columns wide and auto-extends downward. Compaction: widgets
 * pull *up* into the first gap (gravity), preserving left-to-right reading
 * order — the same behaviour react-grid-layout's vertical compactor gives, but
 * computed here so presets, the store and tests all share one implementation.
 */
import type { PresetId, SavedWorkspace, WidgetInstance, WidgetType, WorkspaceLayout } from "./types";

export const GRID_COLS = 12;
/** px per row; widgets size in these units, the grid renders them. */
export const ROW_HEIGHT = 44;
export const GRID_GAP = 10;

export const LAYOUT_VERSION = 1;

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function makeId(prefix = "w"): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Does rect `a` overlap rect `b` (touching edges do not count)? */
export function collides(a: WidgetRectLike, b: WidgetRectLike): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

/** Accepts a full widget instance (its x/y/width/height) or a bare rect. */
export function asRect(w: WidgetRectLike | WidgetInstance): WidgetRectLike {
  const r = w as WidgetRectLike & Partial<WidgetInstance>;
  return { x: r.x, y: r.y, w: r.w ?? r.width ?? 1, h: r.h ?? r.height ?? 1 };
}

export interface WidgetRectLike {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Lowest bottom edge in the layout — where the next widget would land. */
export function bottommost(widgets: readonly WidgetRectLike[]): number {
  return widgets.reduce((max, r) => Math.max(max, r.y + r.h), 0);
}

/**
 * Move `rect` down until it no longer collides with any rect in `others`
 * (used when inserting without reflowing the whole board).
 */
export function firstFreeSpot(rect: WidgetRectLike, others: readonly WidgetRectLike[]): WidgetRectLike {
  let candidate = { ...rect };
  while (others.some((o) => collides(candidate, o))) {
    candidate = { ...candidate, y: candidate.y + 1 };
  }
  return candidate;
}

/**
 * Gravity compaction: repeatedly pull every widget up into the highest gap.
 * Hidden widgets occupy no space and are skipped entirely.
 */
export function compact(widgets: WidgetInstance[]): WidgetInstance[] {
  const placed: WidgetRectLike[] = [];
  const order = [...widgets].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: WidgetInstance[] = [];
  for (const w of order) {
    if (!w.visible) {
      out.push(w); // hidden widgets keep their coordinates but render nothing
      continue;
    }
    let y = w.y;
    const probe = { x: w.x, y, w: w.width, h: w.height };
    while (y > 0 && placed.some((p) => collides({ ...probe, y: y - 1 }, p))) {
      // cannot move up
      break;
    }
    // Step up while free (bounded by collisions with already-placed rects).
    let moved = true;
    while (moved) {
      moved = false;
      if (y > 0 && !placed.some((p) => collides({ x: w.x, y: y - 1, w: w.width, h: w.height }, p))) {
        y -= 1;
        moved = true;
      }
    }
    const next = { ...w, y };
    placed.push({ x: next.x, y: next.y, w: next.width, h: next.height });
    out.push(next);
  }
  // Restore a stable order (original array order, not geometric).
  return widgets.map((w) => out.find((o) => o.id === w.id)!);
}

/** Clamp a rect into the grid bounds and its own min/max size. */
export function clampRect(
  rect: WidgetRectLike,
  min: { w: number; h: number },
  max: { w: number; h: number }
): WidgetRectLike {
  const w = Math.max(min.w, Math.min(max.w, rect.w));
  const h = Math.max(min.h, Math.min(max.h, rect.h));
  const x = Math.max(0, Math.min(GRID_COLS - w, rect.x));
  const y = Math.max(0, rect.y);
  return { x, y, w, h };
}

// ---------------------------------------------------------------------------
// Instance factories (registry-driven — the store passes the descriptor)
// ---------------------------------------------------------------------------

export interface InstanceBounds {
  defaultSize: { w: number; h: number };
  minSize: { w: number; h: number };
}

/**
 * Create a widget instance of `type`, placed in the first free spot at or below
 * `preferredY` so it never lands on top of an existing widget (spec §9).
 */
export function createWidgetInstance(
  type: WidgetType,
  bounds: InstanceBounds,
  widgets: readonly WidgetInstance[],
  settings: Record<string, unknown> = {}
): WidgetInstance {
  const width = Math.min(bounds.defaultSize.w, GRID_COLS);
  const height = bounds.defaultSize.h;
  // Start at the bottom-left; `firstFreeSpot` nudges it down past collisions.
  const base = { x: 0, y: bottommost(widgets.filter((w) => w.visible).map((w) => ({ x: w.x, y: w.y, w: w.width, h: w.height }))), w: width, h: height };
  const spot = firstFreeSpot(base, widgets.filter((w) => w.visible).map((w) => ({ x: w.x, y: w.y, w: w.width, h: w.height })));
  return {
    id: makeId(type.toLowerCase()),
    type,
    x: spot.x,
    y: spot.y,
    width: spot.w,
    height: spot.h,
    visible: true,
    minimized: false,
    maximized: false,
    settings: { ...settings },
  };
}

/** Add an instance, clamped and compacted. */
export function addWidget(layout: WorkspaceLayout, instance: WidgetInstance): WorkspaceLayout {
  const rect = clampRect(
    asRect(instance),
    { w: 1, h: 1 },
    { w: GRID_COLS, h: Number.MAX_SAFE_INTEGER }
  );
  const widgets = compact([...layout.widgets, { ...instance, ...rect }]);
  return touch({ ...layout, widgets });
}

/** Remove by id — hidden or not (spec §7). */
export function removeWidget(layout: WorkspaceLayout, id: string): WorkspaceLayout {
  return touch({ ...layout, widgets: layout.widgets.filter((w) => w.id !== id) });
}

/** Hide: keeps the instance (and its settings) but takes no space (spec §11). */
export function setWidgetVisible(layout: WorkspaceLayout, id: string, visible: boolean): WorkspaceLayout {
  const widgets = compact(
    layout.widgets.map((w) => (w.id === id ? { ...w, visible } : w))
  );
  return touch({ ...layout, widgets });
}

/** Minimize: collapsed to its header row; content unmounts (spec §18). */
export function setWidgetMinimized(layout: WorkspaceLayout, id: string, minimized: boolean): WorkspaceLayout {
  return touch({
    ...layout,
    widgets: layout.widgets.map((w) => (w.id === id ? { ...w, minimized } : w)),
  });
}

/**
 * Maximize: one widget fills the viewport; every other widget is temporarily
 * hidden (kept in state so restore is lossless). Only one maximized at a time.
 */
export function setWidgetMaximized(layout: WorkspaceLayout, id: string, maximized: boolean): WorkspaceLayout {
  const widgets = layout.widgets.map((w) => {
    if (w.id === id) return { ...w, maximized };
    return { ...w, maximized: false };
  });
  return touch({ ...layout, widgets });
}

/**
 * Resize with registry min/max enforcement (spec §10).
 *
 * During an interactive resize react-grid-layout has already resolved what the
 * rest of the board looks like — re-compacting here would fight RGL's own
 * collision model mid-gesture (the widget visibly snaps back). The grid
 * surface commits RGL's result verbatim via commitMove/commitResize;
 * compaction remains a structural-operation concern only.
 */
export function resizeWidget(
  layout: WorkspaceLayout,
  id: string,
  size: { w: number; h: number },
  bounds: InstanceBounds
): WorkspaceLayout {
  const target = layout.widgets.find((w) => w.id === id);
  if (!target) return layout;
  const rect = clampRect(
    { x: target.x, y: target.y, ...size },
    bounds.minSize,
    { w: GRID_COLS, h: Number.MAX_SAFE_INTEGER }
  );
  const widgets = compact(
    layout.widgets.map((w) => (w.id === id ? { ...w, width: rect.w, height: rect.h, x: rect.x, y: rect.y } : w))
  );
  return touch({ ...layout, widgets });
}

/**
 * Reposition (drag) with bounds (spec §9).
 *
 * Programmatic path: keeps gravity compaction for direct API callers.
 * The interactive grid path uses commitMove below, which trusts RGL's
 * collision resolution for the duration of a drag.
 */
export function moveWidget(layout: WorkspaceLayout, id: string, x: number, y: number): WorkspaceLayout {
  const target = layout.widgets.find((w) => w.id === id);
  if (!target) return layout;
  const rect = clampRect(
    { x, y, w: target.width, h: target.height },
    { w: 1, h: 1 },
    { w: GRID_COLS, h: Number.MAX_SAFE_INTEGER }
  );
  const widgets = compact(
    layout.widgets.map((w) => (w.id === id ? { ...w, x: rect.x, y: rect.y } : w))
  );
  return touch({ ...layout, widgets });
}

/**
 * Verbatim interactive commit (drag). react-grid-layout has already applied
 * its collision model to produce `x, y` for the moving item — re-running our
 * gravity compaction against it mid-gesture produces a tug-of-war (the widget
 * snaps back under the pointer). Trust RGL as the geometry authority for the
 * interactive gesture; bounds are still enforced at the grid layer.
 */
export function commitMove(
  layout: WorkspaceLayout,
  id: string,
  x: number,
  y: number
): WorkspaceLayout {
  return touch({
    ...layout,
    widgets: layout.widgets.map((w) => (w.id === id ? { ...w, x, y } : w)),
  });
}

/** Verbatim interactive commit (resize) — same rationale as commitMove. */
export function commitResize(
  layout: WorkspaceLayout,
  id: string,
  size: { w: number; h: number }
): WorkspaceLayout {
  return touch({
    ...layout,
    widgets: layout.widgets.map((w) =>
      w.id === id ? { ...w, width: size.w, height: size.h } : w
    ),
  });
}

/** Update a widget's private settings (chart symbol, pulse period, …). */
export function updateWidgetSettings(
  layout: WorkspaceLayout,
  id: string,
  patch: Record<string, unknown>
): WorkspaceLayout {
  return touch({
    ...layout,
    widgets: layout.widgets.map((w) =>
      w.id === id ? { ...w, settings: { ...w.settings, ...patch } } : w
    ),
  });
}

// ---------------------------------------------------------------------------
// Layout-level operations (spec §12, §13, §14)
// ---------------------------------------------------------------------------

/** Stamp `updatedAt` so persistence can tell fresh layouts from stale ones. */
function touch(layout: WorkspaceLayout): WorkspaceLayout {
  return { ...layout, updatedAt: new Date().toISOString() };
}

/** Validate/repair a loaded layout: drops unknown types, clamps rects. */
export function sanitizeLayout(layout: WorkspaceLayout, boundsFor: (type: WidgetType) => InstanceBounds): WorkspaceLayout {
  const seen = new Set<string>();
  const widgets: WidgetInstance[] = [];
  for (const w of layout.widgets ?? []) {
    // An empty-string id would collide with every other id-less row, so it is
    // treated exactly like a missing id: dropped, never guessed.
    if (!w || typeof w.id !== "string" || w.id.length === 0 || seen.has(w.id)) continue;
    if (typeof w.type !== "string") continue;
    const bounds = boundsFor(w.type);
    if (!bounds) continue; // unknown widget type — drop, never guess
    seen.add(w.id);
    const rect = clampRect(
      { x: w.x ?? 0, y: w.y ?? 0, w: w.width ?? bounds.defaultSize.w, h: w.height ?? bounds.defaultSize.h },
      bounds.minSize,
      { w: GRID_COLS, h: Number.MAX_SAFE_INTEGER }
    );
    widgets.push({
      id: w.id,
      type: w.type,
      x: rect.x,
      y: rect.y,
      width: rect.w,
      height: rect.h,
      visible: w.visible ?? true,
      minimized: w.minimized ?? false,
      maximized: false, // never restore a maximized state across reloads
      settings: typeof w.settings === "object" && w.settings !== null ? { ...w.settings } : {},
    });
  }
  return {
    workspaceId: typeof layout.workspaceId === "string" ? layout.workspaceId : makeId("ws"),
    preset: layout.preset,
    widgets: compact(widgets),
    version: LAYOUT_VERSION,
    updatedAt: layout.updatedAt ?? new Date().toISOString(),
  };
}

/** Reset one workspace back to its preset (spec §12) — other presets untouched. */
export function resetLayout(preset: PresetId, build: () => WorkspaceLayout): WorkspaceLayout {
  const fresh = build();
  return { ...fresh, workspaceId: makeId("ws"), preset, updatedAt: new Date().toISOString() };
}

/** Saved-workspace list helpers (spec §14). */
export function upsertSaved(list: SavedWorkspace[], next: SavedWorkspace): SavedWorkspace[] {
  const idx = list.findIndex((s) => s.id === next.id);
  if (idx === -1) return [...list, next];
  const copy = [...list];
  copy[idx] = next;
  return copy;
}

export function renameSaved(list: SavedWorkspace[], id: string, name: string): SavedWorkspace[] {
  // A blank rename is refused, not applied — a saved workspace can never lose
  // its name through an accidental empty submit.
  const trimmed = name.trim();
  if (!trimmed) return list;
  return list.map((s) => (s.id === id ? { ...s, name: trimmed, updatedAt: new Date().toISOString() } : s));
}

export function deleteSaved(list: SavedWorkspace[], id: string): SavedWorkspace[] {
  return list.filter((s) => s.id !== id);
}
