/**
 * Phase 12 — workspace type model (spec §4, §5, §6, §14, §15).
 *
 * One file owns the shapes every layer agrees on: the widget instance, the
 * layout that positions instances, the saved-workspace record and the storage
 * contract. Widgets never import this for behaviour — layout maths lives in
 * the engine, data fetching in each widget, persistence in the store.
 *
 * Serializability (spec §6): every field is JSON-safe by construction. No
 * component references, no Maps, no class instances — a layout round-trips
 * through `JSON.stringify` and the backend (when one exists) unchanged.
 */

// ---------------------------------------------------------------------------
// Grid geometry
// ---------------------------------------------------------------------------

/** Grid units. The engine converts to pixels; widgets never see coordinates. */
export interface WidgetRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

// ---------------------------------------------------------------------------
// Widget instance (spec §5)
// ---------------------------------------------------------------------------

/**
 * One placed widget. `id` is unique per placement (two widgets of the same type
 * still differ), `type` keys into the registry. `settings` is widget-owned and
 * opaque to the engine — the chart stores its symbol here, the pulse its gauge.
 */
export interface WidgetInstance {
  id: string;
  type: WidgetType;
  x: number;
  y: number;
  width: number;
  height: number;
  visible: boolean;
  minimized: boolean;
  maximized: boolean;
  settings: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Layout (spec §6)
// ---------------------------------------------------------------------------

export type PresetId = "chart-chat" | "trading" | "research";

/** The complete, serializable state of one workspace. */
export interface WorkspaceLayout {
  workspaceId: string;
  preset: PresetId;
  widgets: WidgetInstance[];
  /** Schema version — lets future migrations upgrade stored layouts safely. */
  version: number;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Saved custom workspaces (spec §14)
// ---------------------------------------------------------------------------

export interface SavedWorkspace {
  id: string;
  name: string;
  layout: WorkspaceLayout;
  createdAt: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Storage contract (spec §15)
// ---------------------------------------------------------------------------

/**
 * The UI talks to this interface only. `localStorage` implements it today; an
 * authenticated backend implementation is a drop-in swap — widgets and the
 * store never learn which one is live.
 */
export interface WorkspaceStorage {
  loadActive(): Promise<Record<PresetId, WorkspaceLayout> | null>;
  saveActive(layouts: Record<PresetId, WorkspaceLayout>): Promise<void>;
  loadSaved(): Promise<SavedWorkspace[]>;
  saveSaved(workspaces: SavedWorkspace[]): Promise<void>;
}

// ---------------------------------------------------------------------------
// Registry types (spec §4)
// ---------------------------------------------------------------------------

/** Stable widget-type ids. Doubles as the persistence key. */
export type WidgetType =
  | "NEW_CHART"
  | "DATA"
  | "MARKET_MOVERS"
  | "CATALYSTS_NEWS"
  | "POSITIONS_TRADES"
  | "MARKET_PULSE"
  | "AI_ASSISTANT";

/** How a widget presents in the Add Widget menu (spec §7). */
export interface WidgetDescriptor {
  /** Registry id — the stable string above. */
  type: WidgetType;
  name: string;
  description: string;
  /** lucide-react icon component. */
  icon: unknown;
  /** Grid size a fresh instance starts at. */
  defaultSize: { w: number; h: number };
  /** Never render smaller — content would clip or break. */
  minSize: { w: number; h: number };
  /** `Infinity` when unlimited instances are allowed (charts). */
  maxInstances: number;
  resizable: boolean;
  /** Every widget can be closed except the workspace's primary chart. */
  removable: boolean;
}

// ---------------------------------------------------------------------------
// Presets (spec §2, §3)
// ---------------------------------------------------------------------------

/** A preset is a real configuration object: widget types + grid placement. */
export interface PresetDefinition {
  id: PresetId;
  name: string;
  description: string;
  build: () => WorkspaceLayout;
}

/** Small helper for building instances without repeating defaults. */
export function makeWidget(
  partial: Pick<WidgetInstance, "type" | "x" | "y" | "width" | "height"> &
    Partial<Omit<WidgetInstance, "type" | "x" | "y" | "width" | "height">> & {
      id?: string;
      settings?: Record<string, unknown>;
    }
): WidgetInstance {
  return {
    id: partial.id ?? `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    type: partial.type,
    x: partial.x,
    y: partial.y,
    width: partial.width,
    height: partial.height,
    visible: partial.visible ?? true,
    minimized: partial.minimized ?? false,
    maximized: partial.maximized ?? false,
    settings: partial.settings ?? {},
  };
}
