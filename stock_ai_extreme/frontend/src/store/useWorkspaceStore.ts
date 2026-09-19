/**
 * Phase 12 — workspace store (spec §1, §7, §12, §13, §14, §15).
 *
 * Zustand with the project's existing architecture (the same `create` +
 * `persist` pattern as `useStore.ts`), but persistence flows through the
 * `WorkspaceStorage` *interface* — widgets never touch localStorage.
 *
 * State shape:
 *   layouts   the three per-preset working layouts (always present)
 *   preset    which workspace is on screen
 *   saved     user-saved custom workspaces
 *
 * Every mutation is expressed with the pure engine functions so the maths is
 * testable outside React, and every mutation persists (debounced) through the
 * storage adapter.
 */
import { create } from "zustand";
import {
  addWidget,
  commitMove,
  commitResize,
  createWidgetInstance,
  deleteSaved,
  makeId,
  removeWidget,
  renameSaved,
  resetLayout,
  sanitizeLayout,
  setWidgetMaximized,
  setWidgetMinimized,
  setWidgetVisible,
  updateWidgetSettings,
  upsertSaved,
} from "../lib/workspace/engine";
import { PRESETS, PRESET_ORDER, defaultLayouts } from "../lib/workspace/presets";
import { boundsFor } from "../lib/workspace/registry";
import { getWorkspaceStorage } from "../lib/workspace/storage";
import type {
  PresetId,
  SavedWorkspace,
  WidgetInstance,
  WidgetType,
  WorkspaceLayout,
} from "../lib/workspace/types";

interface WorkspaceState {
  ready: boolean;
  preset: PresetId;
  layouts: Record<PresetId, WorkspaceLayout>;
  saved: SavedWorkspace[];

  hydrate: () => Promise<void>;
  switchPreset: (preset: PresetId) => void;

  addWidgetOfType: (type: WidgetType) => void;
  removeWidgetById: (id: string) => void;
  hideWidget: (id: string) => void;
  showWidget: (id: string) => void;
  minimizeWidget: (id: string, minimized: boolean) => void;
  maximizeWidget: (id: string, maximized: boolean) => void;
  moveWidgetTo: (id: string, x: number, y: number) => void;
  resizeWidgetTo: (id: string, size: { w: number; h: number }) => void;
  patchWidgetSettings: (id: string, patch: Record<string, unknown>) => void;

  resetCurrent: () => void;

  saveCurrentAs: (name: string) => string;
  loadSavedWorkspace: (id: string) => void;
  renameSavedWorkspace: (id: string, name: string) => void;
  deleteSavedWorkspace: (id: string) => void;
}

/** Debounced persistence — a drag fires dozens of mutations, storage gets one. */
let saveTimer: ReturnType<typeof setTimeout> | null = null;
function persistSoon(get: () => WorkspaceState) {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const { layouts, saved } = get();
    const storage = getWorkspaceStorage();
    void storage.saveActive(layouts);
    void storage.saveSaved(saved);
  }, 350);
}

const initialLayouts = defaultLayouts();

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  ready: false,
  preset: "chart-chat",
  layouts: initialLayouts,
  saved: [],

  async hydrate() {
    const storage = getWorkspaceStorage();
    const [active, saved] = await Promise.all([storage.loadActive(), storage.loadSaved()]);
    const fresh = defaultLayouts();
    const layouts = { ...fresh };
    if (active) {
      for (const id of PRESET_ORDER) {
        const stored = active[id];
        // sanitizeLayout repairs/clamps and drops unknown widget types — a
        // layout saved by an older build degrades gracefully instead of crashing.
        layouts[id] = stored ? sanitizeLayout(stored, boundsFor) : fresh[id];
      }
    }
    set({ layouts, saved: saved ?? [], ready: true });
    persistSoon(get);
  },

  switchPreset(preset) {
    if (!PRESET_ORDER.includes(preset)) return;
    set({ preset });
    persistSoon(get);
  },

  addWidgetOfType(type) {
    const { preset, layouts } = get();
    const bounds = boundsFor(type);
    const instance = createWidgetInstance(type, bounds, layouts[preset].widgets, defaultSettingsFor(type));
    const next = addWidget(layouts[preset], instance);
    set({ layouts: { ...layouts, [preset]: next } });
    persistSoon(get);
  },

  removeWidgetById(id) {
    const { preset, layouts } = get();
    set({ layouts: { ...layouts, [preset]: removeWidget(layouts[preset], id) } });
    persistSoon(get);
  },

  hideWidget(id) {
    applyToCurrent(set, get, (l) => setWidgetVisible(l, id, false));
  },

  showWidget(id) {
    applyToCurrent(set, get, (l) => setWidgetVisible(l, id, true));
  },

  minimizeWidget(id, minimized) {
    applyToCurrent(set, get, (l) => setWidgetMinimized(l, id, minimized));
  },

  maximizeWidget(id, maximized) {
    applyToCurrent(set, get, (l) => setWidgetMaximized(l, id, maximized));
  },

  // Interactive drag/resize commits are verbatim (see commitMove/commitResize
  // in the engine): react-grid-layout owns collision resolution during a
  // gesture, so re-compacting here would fight it and snap widgets back.
  moveWidgetTo(id, x, y) {
    applyToCurrent(set, get, (l) => commitMove(l, id, x, y));
  },

  resizeWidgetTo(id, size) {
    applyToCurrent(set, get, (l) => commitResize(l, id, size));
  },

  patchWidgetSettings(id, patch) {
    applyToCurrent(set, get, (l) => updateWidgetSettings(l, id, patch));
  },

  /** Reset only the current workspace to its preset (spec §12). */
  resetCurrent() {
    const { preset, layouts } = get();
    const next = resetLayout(preset, () => PRESETS[preset].build());
    set({ layouts: { ...layouts, [preset]: next } });
    persistSoon(get);
  },

  /** Save the current configuration under a name (spec §14). */
  saveCurrentAs(name) {
    const { preset, layouts, saved } = get();
    const record: SavedWorkspace = {
      id: makeId("sw"),
      name: name.trim() || `${PRESETS[preset].name} copy`,
      layout: { ...layouts[preset] },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    set({ saved: upsertSaved(saved, record) });
    persistSoon(get);
    return record.id;
  },

  /** Load a saved workspace into the current slot (spec §14, §13). */
  loadSavedWorkspace(id) {
    const { saved, preset, layouts } = get();
    const record = saved.find((s) => s.id === id);
    if (!record) return;
    // Load into the current workspace slot, preserving the saved layout as its
    // own copy so later edits do not mutate the stored record.
    const copy: WorkspaceLayout = {
      ...record.layout,
      workspaceId: makeId("ws"),
      preset,
      widgets: record.layout.widgets.map((w) => ({ ...w, settings: { ...w.settings } })),
      updatedAt: new Date().toISOString(),
    };
    set({ layouts: { ...layouts, [preset]: sanitizeLayout(copy, boundsFor) } });
    persistSoon(get);
  },

  renameSavedWorkspace(id, name) {
    const { saved } = get();
    set({ saved: renameSaved(saved, id, name) });
    persistSoon(get);
  },

  deleteSavedWorkspace(id) {
    const { saved } = get();
    set({ saved: deleteSaved(saved, id) });
    persistSoon(get);
  },
}));

/** Apply a pure layout transform to the current preset and persist. */
function applyToCurrent(
  set: (partial: Partial<WorkspaceState>) => void,
  get: () => WorkspaceState,
  transform: (layout: WorkspaceLayout) => WorkspaceLayout
) {
  const { preset, layouts } = get();
  set({ layouts: { ...layouts, [preset]: transform(layouts[preset]) } });
  persistSoon(get);
}

/**
 * Widget-type-specific starting settings. Charts open on a liquid PSX name;
 * news/pulse widgets scope themselves at mount if unset.
 */
function defaultSettingsFor(type: WidgetType): Record<string, unknown> {
  switch (type) {
    case "NEW_CHART":
      return { symbol: "OGDC", timeframe: "6M" };
    case "CATALYSTS_NEWS":
      return { ticker: "" }; // "" = whole-market feed
    default:
      return {};
  }
}

/** Selector helper: the active layout object. */
export function useActiveLayout(): WorkspaceLayout {
  return useWorkspaceStore((s) => s.layouts[s.preset]);
}

export type { WidgetInstance };
