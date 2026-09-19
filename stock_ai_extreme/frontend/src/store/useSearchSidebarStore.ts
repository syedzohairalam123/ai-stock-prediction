import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface RecentSearch {
  symbol: string;
  entityType: "stock" | "index" | "sector";
  timestamp: string;
}

interface SearchSidebarState {
  open: boolean;
  width: number;
  recent: RecentSearch[];
  setOpen: (open: boolean) => void;
  toggle: () => void;
  setWidth: (width: number) => void;
  addRecent: (item: Omit<RecentSearch, "timestamp">) => void;
  clearRecent: () => void;
}

const MAX_RECENT = 12;
const MIN_WIDTH = 280;
const MAX_WIDTH = 420;

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
        set((state) => ({
          recent: [
            { ...item, symbol: item.symbol.toUpperCase(), timestamp: new Date().toISOString() },
            ...state.recent.filter((entry) => !(entry.symbol === item.symbol && entry.entityType === item.entityType)),
          ].slice(0, MAX_RECENT),
        })),
      clearRecent: () => set({ recent: [] }),
    }),
    {
      name: "neural-market-search-sidebar-v1",
      partialize: (state) => ({ open: state.open, width: state.width, recent: state.recent }),
    }
  )
);
