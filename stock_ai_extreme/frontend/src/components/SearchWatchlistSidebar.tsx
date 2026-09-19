import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Clock3,
  Eye,
  Loader2,
  Plus,
  Search,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useWatchlist } from "../hooks/useMarketQueries";
import { searchGlobal, type SearchEntityType, type SearchResult } from "../lib/searchService";
import { useChartStore } from "../store/useChartStore";
import { useSearchSidebarStore } from "../store/useSearchSidebarStore";
import { useTickerStore } from "../store/useStore";

const fmtPrice = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtChange = (value: number | null | undefined) => {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
};

const entityLabel: Record<SearchEntityType, string> = {
  stock: "Stock",
  index: "Index",
  sector: "Sector",
};

function resultRoute(result: SearchResult): string {
  if (result.type === "index") return `/index/${result.symbol}`;
  if (result.type === "sector") return `/market?sector=${encodeURIComponent(result.symbol)}`;
  return `/stock/${result.symbol}`;
}

export default function SearchWatchlistSidebar() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);

  const open = useSearchSidebarStore((state) => state.open);
  const width = useSearchSidebarStore((state) => state.width);
  const recent = useSearchSidebarStore((state) => state.recent);
  const setOpen = useSearchSidebarStore((state) => state.setOpen);
  const toggle = useSearchSidebarStore((state) => state.toggle);
  const addRecent = useSearchSidebarStore((state) => state.addRecent);
  const clearRecent = useSearchSidebarStore((state) => state.clearRecent);

  const currentTicker = useTickerStore((state) => state.currentTicker);
  const setCurrentTicker = useTickerStore((state) => state.setCurrentTicker);
  const activeChartId = useChartStore((state) => state.activeId);
  const setSymbol = useChartStore((state) => state.setSymbol);
  const setEntityType = useChartStore((state) => state.setEntityType);
  const { data, isLoading, isError, error, add, remove } = useWatchlist();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  const results = useMemo(() => {
    try {
      return searchGlobal(debouncedQuery, 48);
    } catch {
      return [];
    }
  }, [debouncedQuery]);

  const quotes = useMemo(() => new Map((data?.items ?? []).map((item) => [item.ticker.toUpperCase(), item])), [data]);
  const grouped = useMemo(
    () => ({
      stock: results.filter((result) => result.type === "stock"),
      index: results.filter((result) => result.type === "index"),
      sector: results.filter((result) => result.type === "sector"),
    }),
    [results]
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [debouncedQuery]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable;
      if (event.key === "/" && !editing) {
        event.preventDefault();
        setOpen(true);
        setMobileOpen(true);
        window.setTimeout(() => inputRef.current?.focus(), 0);
      }
      if (event.key === "Escape" && (query || mobileOpen)) {
        setQuery("");
        setMobileOpen(false);
        inputRef.current?.blur();
      }
    };
    document.addEventListener("keydown", onShortcut);
    return () => document.removeEventListener("keydown", onShortcut);
  }, [mobileOpen, query, setOpen]);

  const flatResults = [grouped.stock, grouped.index, grouped.sector].flat();

  const openResult = (result: SearchResult) => {
    addRecent({ symbol: result.symbol, entityType: result.type });
    if (result.type === "stock" || result.type === "index") {
      const symbol = result.symbol.toUpperCase();
      setCurrentTicker(symbol);
      setSymbol(activeChartId, symbol);
      setEntityType(activeChartId, result.type === "index" ? "INDEX" : "STOCK");
    }
    setQuery("");
    setMobileOpen(false);
    navigate(resultRoute(result));
  };

  const openRecent = (symbol: string, type: SearchEntityType) => {
    const result = searchGlobal(symbol, 48).find((item) => item.symbol === symbol && item.type === type);
    if (result) openResult(result);
  };

  const toggleWatchlist = (event: React.MouseEvent, symbol: string) => {
    event.stopPropagation();
    const upper = symbol.toUpperCase();
    if (quotes.has(upper)) remove.mutate(upper);
    else add.mutate(upper);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, Math.max(0, flatResults.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && flatResults[activeIndex]) {
      event.preventDefault();
      openResult(flatResults[activeIndex]);
    }
  };

  const content = (
    <aside
      className={`search-sidebar${open ? " open" : " collapsed"}${mobileOpen ? " mobile-open" : ""}`}
      style={open ? { width } : undefined}
      aria-label="Search and quick watchlist"
    >
      <div className="search-sidebar-head">
        {open && <span className="search-sidebar-brand">MARKET ACCESS</span>}
        <button className="search-sidebar-toggle" type="button" onClick={() => { toggle(); setMobileOpen(false); }} aria-label={open ? "Collapse search sidebar" : "Expand search sidebar"} title={open ? "Collapse sidebar" : "Expand sidebar"}>
          {open ? <ChevronLeft size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        </button>
      </div>

      {open && (
        <div className="search-sidebar-body">
          <div className="search-sidebar-search">
            <Search size={15} aria-hidden />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Search ticker, company, sector..."
              aria-label="Search stocks, indices and sectors"
              aria-autocomplete="list"
              aria-controls="sidebar-search-results"
              role="combobox"
              aria-expanded={Boolean(query)}
              spellCheck={false}
            />
            {query && <button type="button" onClick={() => setQuery("")} aria-label="Clear search"><X size={14} aria-hidden /></button>}
          </div>

          {query && (
            <div className="search-sidebar-results" id="sidebar-search-results" role="listbox" aria-label="Search results">
              {flatResults.length === 0 && <p className="search-sidebar-state">No matching stocks, indices or sectors.</p>}
              {(["stock", "index", "sector"] as SearchEntityType[]).map((type) => grouped[type].length > 0 && (
                <div key={type} className="search-sidebar-group">
                  <h3>{type === "stock" ? "STOCKS" : type === "index" ? "INDICES" : "SECTORS"}</h3>
                  {grouped[type].map((result) => {
                    const resultIndex = flatResults.indexOf(result);
                    const quote = quotes.get(result.symbol);
                    const watched = quotes.has(result.symbol);
                    return (
                      <div key={result.id} className={`search-sidebar-result${activeIndex === resultIndex ? " selected" : ""}`} role="option" aria-selected={activeIndex === resultIndex}>
                        <button type="button" className="search-sidebar-result-main" onClick={() => openResult(result)}>
                          <strong>{result.symbol}</strong>
                          <span>{result.name}</span>
                          <small>{entityLabel[result.type]}{result.sector ? ` · ${result.sector}` : ""}{quote?.price != null ? ` · ${fmtPrice(quote.price)}` : ""}</small>
                        </button>
                        {result.type === "stock" && <button type="button" className="search-sidebar-watch" onClick={(event) => toggleWatchlist(event, result.symbol)} aria-label={watched ? `Remove ${result.symbol} from watchlist` : `Add ${result.symbol} to watchlist`} title={watched ? "Remove from watchlist" : "Add to watchlist"}>
                          {watched ? <Star size={14} fill="currentColor" aria-hidden /> : <Plus size={14} aria-hidden />}
                        </button>}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          )}

          {!query && recent.length > 0 && <section className="search-sidebar-section"><div className="search-sidebar-section-head"><h2><Clock3 size={14} aria-hidden /> Recent searches</h2><button type="button" onClick={clearRecent}>Clear</button></div><div className="search-sidebar-recent">{recent.map((item) => <button type="button" key={`${item.entityType}-${item.symbol}-${item.timestamp}`} onClick={() => openRecent(item.symbol, item.entityType)}><span>{item.symbol}</span><small>{entityLabel[item.entityType]}</small></button>)}</div></section>}

          <section className="search-sidebar-section"><div className="search-sidebar-section-head"><h2><Star size={14} aria-hidden /> My watchlist</h2><span>{data?.items?.length ?? 0}</span></div>
            {isLoading && <div className="search-sidebar-state"><Loader2 size={14} className="search-sidebar-spin" aria-hidden /> Loading quotes...</div>}
            {isError && <div className="search-sidebar-state" role="alert">{(error as Error)?.message || "Watchlist unavailable."}</div>}
            {!isLoading && !isError && (data?.items?.length ?? 0) === 0 && <p className="search-sidebar-state">Your watchlist is empty.</p>}
            <div className="search-sidebar-watchlist">{(data?.items ?? []).map((item) => { const active = item.ticker === currentTicker; const up = (item.change_percent ?? 0) >= 0; return <div key={item.id} className={`search-sidebar-watch-row${active ? " active" : ""}`}><button type="button" onClick={() => openResult({ id: `stock-${item.ticker}`, type: "stock", symbol: item.ticker, name: item.ticker })} className="search-sidebar-watch-main" aria-current={active ? "true" : undefined}><strong>{item.ticker}</strong><span>{fmtPrice(item.price)}</span><small className={item.change_percent == null ? "muted" : up ? "positive" : "negative"}>{fmtChange(item.change_percent)}</small></button><button type="button" onClick={(event) => toggleWatchlist(event, item.ticker)} className="search-sidebar-remove" aria-label={`Remove ${item.ticker} from watchlist`} title="Remove from watchlist"><Trash2 size={13} aria-hidden /></button></div>; })}</div>
          </section>
        </div>
      )}
    </aside>
  );

  return <>{content}<button type="button" className="search-sidebar-mobile-trigger" onClick={() => { setOpen(true); setMobileOpen(true); }} aria-label="Open search and watchlist sidebar"><Eye size={17} aria-hidden /></button>{mobileOpen && <button type="button" className="search-sidebar-mobile-backdrop" onClick={() => setMobileOpen(false)} aria-label="Close sidebar" />}</>;
}
