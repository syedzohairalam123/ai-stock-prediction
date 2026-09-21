import { create } from "zustand";
import { persist } from "zustand/middleware";
import { createTabSync } from "../lib/tabSync";

export type SearchEntityKind = "stock" | "index" | "sector";

export interface RecentSearch {
  symbol: string;
  entityType: SearchEntityKind;
  timestamp: string;
  /** Phase 13 — a pinned entry survives new searches and is not auto-evicted. */
  pinned?: boolean;
}

interface SearchSidebarState {
  open: boolean;
  width: number;
  recent: RecentSearch[];
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setWidth: (width: number) => void;
  addRecent: (item: Omit<RecentSearch, "timestamp">) => void;
  removeRecent: (symbol: string, entityType: SearchEntityKind) => void;
  togglePinRecent: (symbol: string, entityType: SearchEntityKind) => void;
  clearRecent: () => void;
}

const MAX_RECENT = 12;
const MIN_WIDTH = 280;
const MAX_WIDTH = 420;

/** Trim the list without dropping more than one pinned entry per type. */
function trimRecent(entries: RecentSearch[]): RecentSearch[] {
  return entries
    .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)))
    .slice(0, MAX_RECENT);
}

export const useSearchSidebarStore = create<SearchSidebarState>()(
  persist(
    (set) => ({
      open: true,
      width: 320,
      recent: [],
      setOpen: (open) => set({ open }),
      toggle: () => set((state) => ({ open: !state.open })),
      setWidth: (width) => set({ width: Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width))) }),
      addRecent: (item) =>
        set((state) => {
          const symbol = item.symbol.toUpperCase();
          const existing = state.recent.find((entry) => entry.symbol === symbol && entry.entityType === item.entityType);
          const next: RecentSearch = {
            ...item,
            symbol,
            timestamp: new Date().toISOString(),
            ...(existing?.pinned ? { pinned: true } : {}),
          };
          return {
            recent: trimRecent([
              next,
              ...state.recent.filter((entry) => !(entry.symbol === symbol && entry.entityType === item.entityType)),
            ]),
          };
        }),
      removeRecent: (symbol, entityType) =>
        set((state) => ({
          recent: state.recent.filter((entry) => !(entry.symbol === symbol.toUpperCase() && entry.entityType === entityType)),
        })),
      togglePinRecent: (symbol, entityType) =>
        set((state) => ({
          recent: trimRecent(
            state.recent.map((entry) =>
              entry.symbol === symbol.toUpperCase() && entry.entityType === entityType
                ? { ...entry, pinned: !entry.pinned }
                : entry
            )
          ),
        })),
      clearRecent: () => set({ recent: [] }),
    }),
    {
      name: "neural-market-search-sidebar-v1",
      partialize: (state) => ({ open: state.open, width: state.width, recent: state.recent }),
    }
  )
);

// Phase 13 — recents follow the user between tabs (idempotent wholesale sync).
let applyingRemoteRecent = false;
const recentSync = createTabSync<{ type: "recent/set"; recent?: RecentSearch[] }>("search-recent", (message) => {
  if (message.type !== "recent/set" || !Array.isArray(message.recent)) return;
  applyingRemoteRecent = true;
  try {
    useSearchSidebarStore.setState({ recent: message.recent });
  } finally {
    applyingRemoteRecent = false;
  }
});
useSearchSidebarStore.subscribe((state, previous) => {
  if (applyingRemoteRecent) return;
  if (state.recent !== previous.recent) {
    recentSync.publish({ type: "recent/set", recent: state.recent });
  }
});
