/**
 * Phase 12 — preset definitions (spec §2, §3).
 *
 * A preset is a *real configuration object* — widget types plus grid placement
 * built through the registry's own size bounds — not hardcoded CSS. `build()`
 * returns a fresh layout each call so a reset never aliases a shared instance.
 */
import { GRID_COLS, LAYOUT_VERSION, makeId } from "./engine";
import { boundsFor } from "./registry";
import type { PresetDefinition, PresetId, WidgetInstance, WidgetType, WorkspaceLayout } from "./types";

function now(): string {
  return new Date().toISOString();
}

/** Place a preset widget with registry-clamped geometry. */
function w(
  type: WidgetType,
  x: number,
  y: number,
  width: number,
  height: number,
  settings: Record<string, unknown> = {}
): WidgetInstance {
  const bounds = boundsFor(type);
  return {
    id: makeId(type.toLowerCase()),
    type,
    x: Math.max(0, Math.min(GRID_COLS - width, x)),
    y,
    width,
    height,
    visible: true,
    minimized: false,
    maximized: false,
    settings,
  };
}

function layout(preset: PresetId, widgets: WidgetInstance[]): WorkspaceLayout {
  return {
    workspaceId: makeId("ws"),
    preset,
    widgets,
    version: LAYOUT_VERSION,
    updatedAt: now(),
  };
}

export const PRESETS: Record<PresetId, PresetDefinition> = {
  "chart-chat": {
    id: "chart-chat",
    name: "Chart + Chat",
    description: "Primary chart with the AI assistant beside it; market data and pulse underneath.",
    build: () =>
      layout("chart-chat", [
        // Primary
        w("NEW_CHART", 0, 0, 8, 14, { symbol: "OGDC", timeframe: "6M" }),
        w("AI_ASSISTANT", 8, 0, 4, 14),
        // Secondary
        w("DATA", 0, 14, 6, 9),
        w("MARKET_PULSE", 6, 14, 6, 9),
      ]),
  },
  trading: {
    id: "trading",
    name: "Trading",
    description: "Chart, live movers and your positions — execution-focused.",
    build: () =>
      layout("trading", [
        // Primary
        w("NEW_CHART", 0, 0, 8, 14, { symbol: "OGDC", timeframe: "1M" }),
        w("MARKET_MOVERS", 8, 0, 4, 10),
        w("POSITIONS_TRADES", 8, 10, 4, 8),
        // Secondary
        w("MARKET_PULSE", 0, 14, 4, 8),
        w("DATA", 4, 14, 8, 8),
      ]),
  },
  research: {
    id: "research",
    name: "Research",
    description: "Chart with catalysts, news and data — reading-first.",
    build: () =>
      layout("research", [
        // Primary
        w("NEW_CHART", 0, 0, 7, 14, { symbol: "OGDC", timeframe: "1Y" }),
        w("CATALYSTS_NEWS", 7, 0, 5, 10),
        w("DATA", 7, 10, 5, 8),
        // Secondary
        w("MARKET_PULSE", 0, 14, 4, 8),
        w("MARKET_MOVERS", 4, 14, 8, 8),
      ]),
  },
};

export const PRESET_ORDER: PresetId[] = ["chart-chat", "trading", "research"];

/** Fresh default layouts for every preset (first-visit state). */
export function defaultLayouts(): Record<PresetId, WorkspaceLayout> {
  const out = {} as Record<PresetId, WorkspaceLayout>;
  for (const id of PRESET_ORDER) out[id] = PRESETS[id].build();
  return out;
}

/** Preset geometry lookup used by the engine's sanitize pass. */
export function boundsLookup(type: WidgetType) {
  return boundsFor(type);
}
