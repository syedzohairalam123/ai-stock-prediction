/**
 * Phase 12 — widget registry (spec §4, §8).
 *
 * THE single source of truth for what a widget is: name, description, icon,
 * default/min sizes, how many instances may exist, whether it can be resized
 * or removed. Duplicate rules (§8) live here and nowhere else — the Add Widget
 * menu and the layout engine both ask the registry, they never guess.
 *
 * Components are resolved through `componentFor()` instead of living in this
 * file so the registry stays importable from pure Node tests (no React).
 */
import {
  BarChart3,
  CandlestickChart,
  Flame,
  LayoutDashboard,
  MessagesSquare,
  Newspaper,
  Wallet,
} from "lucide-react";
import type { WidgetDescriptor, WidgetType } from "./types";

export const WIDGET_REGISTRY: Record<WidgetType, WidgetDescriptor> = {
  NEW_CHART: {
    type: "NEW_CHART",
    name: "Chart",
    description: "Phase-11 technical analysis chart with indicators, drawings and price levels.",
    icon: CandlestickChart,
    defaultSize: { w: 8, h: 10 },
    minSize: { w: 4, h: 6 },
    maxInstances: Number.POSITIVE_INFINITY,
    resizable: true,
    removable: true,
  },
  DATA: {
    type: "DATA",
    name: "Data",
    description: "Live watchlist quotes and the crypto / commodities / forex board.",
    icon: LayoutDashboard,
    defaultSize: { w: 4, h: 8 },
    minSize: { w: 3, h: 4 },
    maxInstances: Number.POSITIVE_INFINITY,
    resizable: true,
    removable: true,
  },
  MARKET_MOVERS: {
    type: "MARKET_MOVERS",
    name: "Market Movers",
    description: "Most active stocks, top gainers and losers across a chosen universe.",
    icon: Flame,
    defaultSize: { w: 4, h: 8 },
    minSize: { w: 3, h: 4 },
    maxInstances: Number.POSITIVE_INFINITY,
    resizable: true,
    removable: true,
  },
  CATALYSTS_NEWS: {
    type: "CATALYSTS_NEWS",
    name: "Catalysts & News",
    description: "Live headlines with lexicon sentiment for a ticker or the whole market.",
    icon: Newspaper,
    defaultSize: { w: 5, h: 9 },
    minSize: { w: 3, h: 5 },
    maxInstances: Number.POSITIVE_INFINITY,
    resizable: true,
    removable: true,
  },
  POSITIONS_TRADES: {
    type: "POSITIONS_TRADES",
    name: "Positions & Trades",
    description: "Live-marked portfolio positions with cost basis and P&L.",
    icon: Wallet,
    defaultSize: { w: 6, h: 8 },
    minSize: { w: 4, h: 4 },
    maxInstances: 1,
    resizable: true,
    removable: true,
  },
  MARKET_PULSE: {
    type: "MARKET_PULSE",
    name: "Market Pulse",
    description: "Fear/greed sentiment gauge plus macro stress read.",
    icon: BarChart3,
    defaultSize: { w: 4, h: 7 },
    minSize: { w: 3, h: 4 },
    maxInstances: 1,
    resizable: true,
    removable: true,
  },
  AI_ASSISTANT: {
    type: "AI_ASSISTANT",
    name: "AI Assistant",
    description: "Context-aware market assistant wired to the live backend (Phase 10).",
    icon: MessagesSquare,
    defaultSize: { w: 4, h: 12 },
    minSize: { w: 3, h: 6 },
    maxInstances: 1,
    resizable: true,
    removable: true,
  },
};

/** Order shown in the Add Widget menu. */
export const WIDGET_ORDER: WidgetType[] = [
  "NEW_CHART",
  "DATA",
  "MARKET_MOVERS",
  "CATALYSTS_NEWS",
  "POSITIONS_TRADES",
  "MARKET_PULSE",
  "AI_ASSISTANT",
];

export function descriptorFor(type: WidgetType): WidgetDescriptor {
  return WIDGET_REGISTRY[type];
}

/** Bounds shaped for the engine (`createWidgetInstance` / `resizeWidget`). */
export function boundsFor(type: WidgetType): { defaultSize: { w: number; h: number }; minSize: { w: number; h: number } } {
  const d = WIDGET_REGISTRY[type];
  return { defaultSize: d.defaultSize, minSize: d.minSize };
}

/** Can another instance of `type` be added given what is already placed? */
export function canAdd(type: WidgetType, widgets: readonly { type: WidgetType }[]): boolean {
  const count = widgets.filter((w) => w.type === type).length;
  return count < WIDGET_REGISTRY[type].maxInstances;
}

/** How many more instances of `type` the layout accepts (0 = none). */
export function remainingInstances(type: WidgetType, widgets: readonly { type: WidgetType }[]): number {
  const max = WIDGET_REGISTRY[type].maxInstances;
  if (!Number.isFinite(max)) return Number.POSITIVE_INFINITY;
  return Math.max(0, max - widgets.filter((w) => w.type === type).length);
}

/**
 * Resolve the React component for a widget type. Kept out of the descriptors
 * so this module stays React-free for engine tests; `WorkspaceGrid` lazy-loads
 * the module this returns (spec §18: lazy-load expensive widgets).
 *
 * The widened `any` props contract is deliberate: each widget declares its own
 * precise props internally; the grid passes the standard triple
 * (`widgetId`, `settings`, `onSettingsChange`) that every widget accepts.
 */
export function componentModuleFor(type: WidgetType): Promise<{ default: React.ComponentType<any> }> {
  switch (type) {
    case "NEW_CHART":
      return import("../../components/workspace/widgets/ChartWidget");
    case "DATA":
      return import("../../components/workspace/widgets/DataWidget");
    case "MARKET_MOVERS":
      return import("../../components/workspace/widgets/MarketMoversWidget");
    case "CATALYSTS_NEWS":
      return import("../../components/workspace/widgets/CatalystsNewsWidget");
    case "POSITIONS_TRADES":
      return import("../../components/workspace/widgets/PositionsTradesWidget");
    case "MARKET_PULSE":
      return import("../../components/workspace/widgets/MarketPulseWidget");
    case "AI_ASSISTANT":
      return import("../../components/workspace/widgets/AIAssistantWidget");
  }
}
