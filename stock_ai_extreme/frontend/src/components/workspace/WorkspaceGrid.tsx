/**
 * Phase 12 — WorkspaceGrid (spec §9, §10, §18).
 *
 * react-grid-layout owns drag/resize interactions; this component owns the
 * mapping between the store's `WidgetInstance`s and grid items, lazy widget
 * loading from the registry, and the workspace bar (presets, Add Widget,
 * hidden-widget restore, save/reset menus).
 *
 * Performance (§18): the grid re-renders only when the layout array or the
 * set of widget ids changes; widget bodies are `React.lazy` chunks; hidden
 * widgets render nothing; the drag handle is the widget header so a drag
 * never fights a chart's own pointer gestures.
 */
import { Suspense, lazy, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
// Required library stylesheets: without them the resize handles lose their
// absolute bottom-corner positioning, the drop placeholder has no styling and
// grid items lose their move/resize transitions.
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import {
  Copy,
  CopyPlus,
  Download,
  Eye,
  LayoutGrid,
  Plus,
  RotateCcw,
  Save,
  Upload,
  Loader2,
} from "lucide-react";
import { useContainerWidth } from "react-grid-layout";
import type { Layout, LayoutItem } from "react-grid-layout";
import { GridLayout } from "react-grid-layout";
import { boundsFor, canAdd, componentModuleFor, descriptorFor, WIDGET_ORDER } from "../../lib/workspace/registry";
import { GRID_COLS, GRID_GAP, ROW_HEIGHT } from "../../lib/workspace/engine";
import { PRESETS, PRESET_ORDER } from "../../lib/workspace/presets";
import { useWorkspaceStore } from "../../store/useWorkspaceStore";
import { buildWorkspaceShareLink, exportWorkspacesJSON, parseWorkspacesJSON } from "../../lib/workspace/storage";
import WidgetFrame from "./WidgetFrame";
import type { WidgetInstance, WidgetType } from "../../lib/workspace/types";

// ---------------------------------------------------------------------------
// Lazy widget bodies (spec §18)
// ---------------------------------------------------------------------------

const widgetCache = new Map<WidgetType, ReturnType<typeof lazy>>();

function lazyWidget(type: WidgetType) {
  let cached = widgetCache.get(type);
  if (!cached) {
    cached = lazy(() =>
      componentModuleFor(type).then((mod) => ({ default: mod.default }))
    );
    widgetCache.set(type, cached);
  }
  return cached;
}

function WidgetSkeleton({ name }: { name: string }) {
  return (
    <div className="ws-widget-loading" role="status" aria-label={`Loading ${name}`}>
      <Loader2 className="ws-spin" size={16} aria-hidden />
      <span>Loading {name}…</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

function WorkspaceGridInner() {
  const preset = useWorkspaceStore((s) => s.preset);
  const layout = useWorkspaceStore((s) => s.layouts[s.preset]);
  const widgets = layout.widgets;

  const switchPreset = useWorkspaceStore((s) => s.switchPreset);
  const addWidgetOfType = useWorkspaceStore((s) => s.addWidgetOfType);
  const removeWidgetById = useWorkspaceStore((s) => s.removeWidgetById);
  const moveWidgetTo = useWorkspaceStore((s) => s.moveWidgetTo);
  const resizeWidgetTo = useWorkspaceStore((s) => s.resizeWidgetTo);
  const showWidget = useWorkspaceStore((s) => s.showWidget);
  const resetCurrent = useWorkspaceStore((s) => s.resetCurrent);
  const saveCurrentAs = useWorkspaceStore((s) => s.saveCurrentAs);
  const saved = useWorkspaceStore((s) => s.saved);
  const loadSavedWorkspace = useWorkspaceStore((s) => s.loadSavedWorkspace);
  const renameSavedWorkspace = useWorkspaceStore((s) => s.renameSavedWorkspace);
  const deleteSavedWorkspace = useWorkspaceStore((s) => s.deleteSavedWorkspace);
  const duplicateSavedWorkspace = useWorkspaceStore((s) => s.duplicateSavedWorkspace);
  const importSavedWorkspaces = useWorkspaceStore((s) => s.importSavedWorkspaces);

  const { width, containerRef, mounted } = useContainerWidth();
  const [menu, setMenu] = useState<"add" | "save" | "load" | "hidden" | "data" | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const close = () => setMenu(null);
    if (!menu) return;
    document.body.addEventListener("pointerdown", close);
    return () => document.body.removeEventListener("pointerdown", close);
  }, [menu]);

  const maximizedId = useMemo(() => widgets.find((w) => w.maximized)?.id ?? null, [widgets]);
  const hidden = useMemo(() => widgets.filter((w) => !w.visible), [widgets]);

  // While one widget is maximized, only that widget stays in the grid — the
  // others unmount entirely (spec §11: maximize fills the workspace). Store
  // positions are untouched, so restore is exact.
  const gridWidgets = useMemo(
    () => (maximizedId ? widgets.filter((w) => w.id === maximizedId) : widgets.filter((w) => w.visible)),
    [widgets, maximizedId]
  );

  /** Store instances → grid layout (visible ones only; RGL owns compaction). */
  const gridLayout: Layout = useMemo(
    () =>
      gridWidgets
        .map((w) => {
          const bounds = boundsFor(w.type);
          const maximized = maximizedId === w.id;
          return {
            i: w.id,
            x: maximized ? 0 : w.x,
            y: maximized ? 0 : w.y,
            w: maximized ? GRID_COLS : w.width,
            // Keep the real size in the store while rendering a compact row.
            // onLayoutChange ignores this synthetic height, so restoring a
            // minimized widget returns it to its previous dimensions.
            h: maximized ? 24 : w.minimized ? 1 : w.height,
            minW: w.minimized || maximized ? 1 : bounds.minSize.w,
            minH: w.minimized || maximized ? 1 : bounds.minSize.h,
            // Maximized widgets are pinned; everything else stays editable.
            static: maximized || w.minimized || !descriptorFor(w.type).resizable,
          };
        }),
    [gridWidgets, maximizedId]
  );

  const onLayoutChange = useCallback(
    (next: Layout) => {
      // Diff against the store: only commit real moves/resizes. RGL fires this
      // after compaction too, so a naive write-back would loop.
      const byId = new Map(next.map((item: LayoutItem) => [item.i, item]));
      for (const w of widgets) {
        const item = byId.get(w.id);
        if (!item) continue;
        if (w.maximized || w.minimized) continue;
        if (w.x !== item.x || w.y !== item.y) moveWidgetTo(w.id, item.x, item.y);
        else if (w.width !== item.w || w.height !== item.h) resizeWidgetTo(w.id, { w: item.w, h: item.h });
      }
    },
    [widgets, moveWidgetTo, resizeWidgetTo]
  );

  const tryAdd = (type: WidgetType) => {
    if (canAdd(type, widgets)) addWidgetOfType(type);
    setMenu(null);
  };

  /**
   * Copy a self-contained share link for one saved workspace.
   *
   * The link embeds the layout, so it resolves on another machine too. The
   * Clipboard API can reject (insecure context, denied permission); rather than
   * failing silently the link is offered through a prompt for manual copying.
   */
  const copyShareLink = useCallback(
    async (id: string) => {
      const record = saved.find((entry) => entry.id === id);
      if (!record) return;
      const link = buildWorkspaceShareLink(record);
      try {
        await navigator.clipboard.writeText(link);
        setCopiedId(id);
        window.setTimeout(() => setCopiedId((current) => (current === id ? null : current)), 1800);
      } catch {
        window.prompt("Copy this workspace link", link);
      }
    },
    [saved]
  );

  /** Download every saved workspace as one JSON document. */
  const handleExport = useCallback(() => {
    if (saved.length === 0) return;
    const blob = new Blob([exportWorkspacesJSON(saved)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `neural-market-workspaces-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setShareError(null);
  }, [saved]);

  /** Read an exported file and merge its workspaces into the saved list. */
  const handleImportFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      try {
        const records = parseWorkspacesJSON(await file.text());
        importSavedWorkspaces(records);
        setShareError(null);
      } catch (error) {
        setShareError(error instanceof Error ? error.message : "That file could not be imported.");
      }
    },
    [importSavedWorkspaces]
  );

  return (
    <div className="ws-root">
      {/* ---------------- workspace bar ---------------- */}
      <div className="ws-bar">
        <div className="ws-bar-presets" role="tablist" aria-label="Workspace preset">
          {PRESET_ORDER.map((id) => (
            <button
              key={id}
              role="tab"
              aria-selected={preset === id}
              className={`ws-preset-btn${preset === id ? " on" : ""}`}
              onClick={() => switchPreset(id)}
              title={PRESETS[id].description}
            >
              {PRESETS[id].name}
            </button>
          ))}
        </div>

        <div className="ws-bar-actions" role="group" aria-label="Workspace actions">
          {/* Add Widget (spec §7) */}
          <div className="ws-pop-anchor" data-ws-menu>
            <button
              type="button"
              className={`ws-btn${menu === "add" ? " on" : ""}`}
              aria-haspopup="true"
              aria-expanded={menu === "add"}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === "add" ? null : "add");
              }}
            >
              <Plus size={14} aria-hidden /> Add widget
            </button>
            {menu === "add" && (
              <div className="ws-pop" role="menu" aria-label="Add widget">
                {WIDGET_ORDER.map((type) => {
                  const d = descriptorFor(type);
                  const allowed = canAdd(type, widgets);
                  const Icon = d.icon as React.ComponentType<{ size?: number; "aria-hidden"?: boolean }>;
                  return (
                    <button
                      key={type}
                      role="menuitem"
                      className="ws-pop-item"
                      onClick={() => tryAdd(type)}
                      disabled={!allowed}
                      title={allowed ? d.description : `Limit: at most ${d.maxInstances === Number.POSITIVE_INFINITY ? "∞" : d.maxInstances} of this widget`}
                    >
                      <Icon size={15} aria-hidden />
                      <span className="ws-pop-item-text">
                        <b>{d.name}</b>
                        <small>{d.description}</small>
                      </span>
                      <span className="ws-pop-add" aria-hidden>
                        +
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Save custom workspace (spec §14) */}
          <div className="ws-pop-anchor" data-ws-menu>
            <button
              type="button"
              className={`ws-btn${menu === "save" ? " on" : ""}`}
              aria-haspopup="true"
              aria-expanded={menu === "save"}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === "save" ? null : "save");
              }}
            >
              <Save size={14} aria-hidden /> Save
            </button>
            {menu === "save" && (
              <form
                className="ws-pop ws-pop-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const input = (e.currentTarget.elements.namedItem("name") as HTMLInputElement) ?? null;
                  if (input?.value.trim()) {
                    saveCurrentAs(input.value.trim());
                    setMenu(null);
                  }
                }}
              >
                <label>
                  Name
                  <input name="name" required placeholder="My trading desk" aria-label="Workspace name" />
                </label>
                <button type="submit" className="ws-btn pri sm">
                  Save layout
                </button>
              </form>
            )}
          </div>

          {/* Load / rename / delete saved workspaces (spec §14) */}
          <div className="ws-pop-anchor" data-ws-menu>
            <button
              type="button"
              className={`ws-btn${menu === "load" ? " on" : ""}`}
              aria-haspopup="true"
              aria-expanded={menu === "load"}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === "load" ? null : "load");
              }}
            >
              <LayoutGrid size={14} aria-hidden /> Load
              {saved.length > 0 && <span className="ws-badge">{saved.length}</span>}
            </button>
            {menu === "load" && (
              <div className="ws-pop" role="menu" aria-label="Saved workspaces">
                {saved.length === 0 && <p className="ws-pop-empty">No saved workspaces yet.</p>}
                {saved.map((s) => (
                  <div key={s.id} className="ws-pop-row">
                    <input
                      className="ws-rename"
                      defaultValue={s.name}
                      aria-label={`Rename ${s.name}`}
                      onBlur={(e) => {
                        const name = e.target.value.trim();
                        if (name && name !== s.name) renameSavedWorkspace(s.id, name);
                      }}
                    />
                    <button type="button" className="ws-btn pri sm" onClick={() => { loadSavedWorkspace(s.id); setMenu(null); }}>
                      Load
                    </button>
                    <button
                      type="button"
                      className="ws-ctl"
                      aria-label={`Duplicate ${s.name}`}
                      title="Duplicate — save this workspace under a new name"
                      onClick={() => duplicateSavedWorkspace(s.id)}
                    >
                      <CopyPlus size={13} aria-hidden />
                    </button>
                    <button
                      type="button"
                      className={`ws-ctl${copiedId === s.id ? " ok" : ""}`}
                      aria-label={`Copy share link for ${s.name}`}
                      title={copiedId === s.id ? "Link copied to clipboard" : "Copy a shareable link (layout included)"}
                      onClick={() => { void copyShareLink(s.id); }}
                    >
                      <Copy size={13} aria-hidden />
                    </button>
                    <button
                      type="button"
                      className="ws-ctl"
                      aria-label={`Delete ${s.name}`}
                      title="Delete"
                      onClick={() => deleteSavedWorkspace(s.id)}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Share / data portability (spec §14, §15) */}
          <div className="ws-pop-anchor" data-ws-menu>
            <button
              type="button"
              className={`ws-btn${menu === "data" ? " on" : ""}`}
              aria-haspopup="true"
              aria-expanded={menu === "data"}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === "data" ? null : "data");
              }}
            >
              <Download size={14} aria-hidden /> Share
            </button>
            {menu === "data" && (
              <div className="ws-pop ws-pop-form" role="menu" aria-label="Import and export workspaces">
                <button
                  type="button"
                  className="ws-btn sm"
                  onClick={handleExport}
                  disabled={saved.length === 0}
                  title={saved.length === 0 ? "Save a workspace first" : "Download every saved workspace as JSON"}
                >
                  <Download size={13} aria-hidden /> Export JSON ({saved.length})
                </button>
                <button type="button" className="ws-btn sm" onClick={() => fileInputRef.current?.click()}>
                  <Upload size={13} aria-hidden /> Import JSON
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/json,.json"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    void handleImportFile(file);
                    e.target.value = "";
                  }}
                  aria-label="Import workspaces from a JSON file"
                />
                {shareError && (
                  <p className="ws-pop-error" role="alert">
                    {shareError}
                  </p>
                )}
                <p className="ws-pop-note">
                  Exported files carry your saved workspaces. Use “Copy link” on a saved workspace to share a single
                  one as a URL.
                </p>
              </div>
            )}
          </div>

          {/* Hidden widgets restore (spec §11, hide keeps data) */}
          <div className="ws-pop-anchor" data-ws-menu>
            <button
              type="button"
              className={`ws-btn${menu === "hidden" ? " on" : ""}`}
              aria-haspopup="true"
              aria-expanded={menu === "hidden"}
              disabled={hidden.length === 0}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === "hidden" ? null : "hidden");
              }}
            >
              <Eye size={14} aria-hidden /> Hidden
              {hidden.length > 0 && <span className="ws-badge">{hidden.length}</span>}
            </button>
            {menu === "hidden" && (
              <div className="ws-pop" role="menu" aria-label="Hidden widgets">
                {hidden.map((w) => (
                  <button key={w.id} role="menuitem" className="ws-pop-item" onClick={() => { showWidget(w.id); setMenu(null); }}>
                    <Eye size={15} aria-hidden />
                    <span className="ws-pop-item-text">
                      <b>{descriptorFor(w.type).name}</b>
                      <small>Show again — its settings are untouched.</small>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Reset (spec §12) — current preset only */}
          <button
            type="button"
            className="ws-btn"
            onClick={() => {
              if (window.confirm(`Reset the ${PRESETS[preset].name} workspace to its default layout? Saved workspaces are not touched.`)) {
                resetCurrent();
              }
            }}
            title="Restore this preset's default layout"
          >
            <RotateCcw size={14} aria-hidden /> Reset
          </button>
        </div>
      </div>

      {/* ---------------- grid ---------------- */}
      <div className="ws-grid-wrap" ref={containerRef as React.RefObject<HTMLDivElement>}>
        {mounted && (
          // GridLayout (non-responsive variant): one 12-col definition, sized by
          // the measured container width. Mobile stacking is handled by the
          // engine's compaction + the frame's own scroll — see the CSS below.
          <GridLayout
            width={width}
            gridConfig={{ cols: GRID_COLS, rowHeight: ROW_HEIGHT, margin: [GRID_GAP, GRID_GAP], containerPadding: [GRID_GAP, GRID_GAP] }}
            layout={gridLayout}
            // Cancel must NOT include bare `button`: the drag handle itself is a
            // <button>, and react-draggable evaluates cancel *after* handle by
            // walking ancestors — a generic button rule would cancel our own
            // handle on every press.
            dragConfig={{ enabled: !maximizedId, handle: ".ws-widget-drag", cancel: ".ws-widget-controls, input, select, textarea", threshold: 4 }}
            resizeConfig={{ enabled: !maximizedId, handles: ["e", "s", "se"] }}
            onLayoutChange={onLayoutChange}
            className="ws-grid"
          >
            {gridWidgets.map((w) => {
              const Body = lazyWidget(w.type);
              const d = descriptorFor(w.type);
              return (
                <div key={w.id} className="ws-widget-slot" data-widget-id={w.id}>
                  <WidgetFrame widget={w}>
                    {(bodyVisible) =>
                      bodyVisible ? (
                        <Suspense fallback={<WidgetSkeleton name={d.name} />}>
                          <Body widgetId={w.id} settings={w.settings} onSettingsChange={(patch: Record<string, unknown>) => useWorkspaceStore.getState().patchWidgetSettings(w.id, patch)} />
                        </Suspense>
                      ) : null
                    }
                  </WidgetFrame>
                </div>
              );
            })}
          </GridLayout>
        )}
      </div>

      {widgets.length === 0 && (
        <div className="ws-empty" role="status">
          <b>Empty workspace</b>
          <span>Use “Add widget” to build this workspace — or Reset to restore the preset.</span>
        </div>
      )}
    </div>
  );
}

const WorkspaceGrid = memo(WorkspaceGridInner);
export default WorkspaceGrid;

/** Kept for typed consumers that want the instance type. */
export type { WidgetInstance };
