/**
 * Phase 12 — public surface of the workspace engine.
 *
 * UI code imports from `lib/workspace` only; the individual modules stay free
 * to reorganize without breaking call sites (the same pattern the Phase-11
 * charting engine uses).
 */
export * from "./types";
export {
  GRID_COLS,
  GRID_GAP,
  ROW_HEIGHT,
  LAYOUT_VERSION,
  addWidget,
  bottommost,
  clampRect,
  collides,
  compact,
  createWidgetInstance,
  deleteSaved,
  firstFreeSpot,
  makeId,
  moveWidget,
  removeWidget,
  renameSaved,
  resetLayout,
  resizeWidget,
  sanitizeLayout,
  setWidgetMaximized,
  setWidgetMinimized,
  setWidgetVisible,
  updateWidgetSettings,
  upsertSaved,
} from "./engine";
export {
  WIDGET_REGISTRY,
  WIDGET_ORDER,
  boundsFor,
  canAdd,
  componentModuleFor,
  descriptorFor,
  remainingInstances,
} from "./registry";
export { PRESETS, PRESET_ORDER, boundsLookup, defaultLayouts } from "./presets";
export {
  createBackendStorage,
  getWorkspaceStorage,
  localStorageWorkspaceStorage,
} from "./storage";
