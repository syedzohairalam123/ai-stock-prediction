import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface TickerState {
  currentTicker: string;
  setCurrentTicker: (ticker: string) => void;
}

interface WatchlistState {
  watchlist: string[];
  addToWatchlist: (ticker: string) => void;
  removeFromWatchlist: (ticker: string) => void;
}

interface SettingsState {
  theme: 'light' | 'dark';
  autoRefresh: boolean;
  refreshInterval: number;
  setTheme: (theme: 'light' | 'dark') => void;
  setAutoRefresh: (enabled: boolean) => void;
  setRefreshInterval: (interval: number) => void;
}

interface UIState {
  sidebarOpen: boolean;
  loading: boolean;
  error: string | null;
  setSidebarOpen: (open: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

// Ticker Store
export const useTickerStore = create<TickerState>((set) => ({
  currentTicker: 'AAPL',
  setCurrentTicker: (ticker) => set({ currentTicker: ticker.toUpperCase() }),
}));

// Watchlist Store with persistence
export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set) => ({
      watchlist: ['AAPL', 'MSFT', 'GOOGL', 'TSLA'],
      addToWatchlist: (ticker) =>
        set((state) => ({
          watchlist: state.watchlist.includes(ticker.toUpperCase())
            ? state.watchlist
            : [...state.watchlist, ticker.toUpperCase()],
        })),
      removeFromWatchlist: (ticker) =>
        set((state) => ({
          watchlist: state.watchlist.filter((t) => t !== ticker.toUpperCase()),
        })),
    }),
    {
      name: 'neural-market-watchlist',
    }
  )
);

// Settings Store with persistence
export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      theme: 'dark',
      autoRefresh: true,
      refreshInterval: 20000,
      setTheme: (theme) => set({ theme }),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
      setRefreshInterval: (refreshInterval) => set({ refreshInterval }),
    }),
    {
      name: 'neural-market-settings',
    }
  )
);

// UI Store
export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  loading: false,
  error: null,
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));