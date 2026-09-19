/**
 * Phase 9 — Watchlist page (spec C/D/E/O/R/S).
 *
 * Full watchlist engine surface: search, notes, manual reorder (up/down —
 * keyboard-accessible and mobile-friendly), priced rows through the provider
 * layer, immediate UI updates after every change, and honest degradation when
 * a symbol can't be priced. Clicking a row opens the stock page (spec O);
 * action buttons never trigger navigation.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWatchlistItems, fetchQuote } from "../hooks/usePortfolioQueries";
import { formatPct } from "../lib/finance";

function QuoteCell({ item }: { item: { price?: number | null; changePercent?: number | null; status?: string } }) {
  const priced = typeof item.price === "number" && Number.isFinite(item.price);
  if (!priced) {
    return (
      <span className="price-unavailable" title={`Provider status: ${item.status ?? "UNAVAILABLE"}`}>
        PRICE UNAVAILABLE
      </span>
    );
  }
  const up = (item.changePercent ?? 0) >= 0;
  return (
    <span className="watchlist-quote-block">
      <span className="watchlist-price">
        {(item.price as number).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </span>
      <span className={`watchlist-chg ${up ? "pos" : "neg"}`}>
        <span aria-hidden>{up ? "▲ +" : "▼ "}</span>
        {formatPct(item.changePercent ?? null)}
      </span>
    </span>
  );
}

export default function WatchlistPage() {
  const navigate = useNavigate();
  const { items, loading, error, offline, reload, add, remove, setNotes, reorder } =
    useWatchlistItems();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [busySymbol, setBusySymbol] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editingNotes, setEditingNotes] = useState<string | null>(null);
  const [notesDraft, setNotesDraft] = useState("");

  /** Search over symbol + notes (spec D). */
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (i) => i.symbol.toLowerCase().includes(q) || (i.notes ?? "").toLowerCase().includes(q)
    );
  }, [items, search]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setBusySymbol(sym);
    setActionError(null);
    try {
      await add(sym);
      setInput("");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Could not add ${sym}`);
    } finally {
      setBusySymbol(null);
    }
  }

  async function handleRemove(symbol: string) {
    setBusySymbol(symbol);
    setActionError(null);
    try {
      await remove(symbol);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Could not remove ${symbol}`);
    } finally {
      setBusySymbol(null);
    }
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= visible.length) return;
    // reorder in the *display* list, then persist by id
    const next = [...visible];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    void reorder(next.map((i) => i.id));
  }

  async function refreshQuote(symbol: string) {
    setBusySymbol(symbol);
    try {
      await fetchQuote(symbol); // warms the server-side quote cache
      await reload();
    } finally {
      setBusySymbol(null);
    }
  }

  function saveNotes(symbol: string) {
    void setNotes(symbol, notesDraft.trim() || null);
    setEditingNotes(null);
  }

  return (
    <main className="watchlist-page">
      <div className="psx-page-head">
        <div>
          <p>Track · Organize · Revisit</p>
          <h1>Watchlist</h1>
        </div>
        <div className="portfolio-actions">
          <button onClick={reload} disabled={loading} className="portfolio-refresh-btn">
            <svg className={`portfolio-refresh-icon ${loading ? "spinning" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {offline && (
        <div className="portfolio-offline-banner" role="status">
          Backend unreachable — watchlist changes are saved in this browser only.
        </div>
      )}

      <form onSubmit={handleAdd} className="watchlist-add watchlist-add-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="Add symbol… e.g. OGDC, HBL, SYS"
          aria-label="Add to watchlist"
          autoComplete="off"
          disabled={busySymbol !== null}
        />
        <button type="submit" disabled={!input.trim() || busySymbol !== null} aria-label="Add symbol">
          {busySymbol ? "…" : "+ Add"}
        </button>
      </form>

      {actionError && (
        <div className="form-error-banner" role="alert">
          {actionError}
        </div>
      )}

      {error && (
        <div className="portfolio-error" role="alert">
          <p>{error}</p>
          <button onClick={reload}>Try again</button>
        </div>
      )}

      {items.length > 0 && (
        <input
          className="tx-filter-input watchlist-search"
          placeholder="Search watchlist…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search watchlist"
        />
      )}

      {loading && (
        <div className="skeleton" style={{ height: 160 }} aria-busy="true" />
      )}

      {!loading && items.length === 0 && (
        <div className="portfolio-empty">
          <p>Your watchlist is empty</p>
          <small>
            Add symbols above, or star stocks from the{" "}
            <button className="link-btn" onClick={() => navigate("/popular")}>
              Popular Stocks
            </button>{" "}
            page.
          </small>
        </div>
      )}

      {!loading && items.length > 0 && visible.length === 0 && (
        <p className="empty">No watchlist items match “{search}”.</p>
      )}

      {!loading && visible.length > 0 && (
        <ul className="watchlist-manager" aria-label="Watchlist items">
          {visible.map((item, idx) => (
            <li key={String(item.id)} className="watchlist-manager-row">
              <div className="watchlist-reorder">
                <button
                  className="watchlist-move-btn"
                  onClick={() => move(idx, -1)}
                  disabled={idx === 0}
                  aria-label={`Move ${item.symbol} up`}
                >
                  ↑
                </button>
                <button
                  className="watchlist-move-btn"
                  onClick={() => move(idx, 1)}
                  disabled={idx === visible.length - 1}
                  aria-label={`Move ${item.symbol} down`}
                >
                  ↓
                </button>
              </div>

              <button
                className="watchlist-symbol-link"
                onClick={() => navigate(`/stock/${item.symbol}`)}
                title={`Open ${item.symbol}`}
              >
                {item.symbol}
              </button>

              <QuoteCell item={item} />

              <div className="watchlist-notes">
                {editingNotes === item.symbol ? (
                  <span className="watchlist-notes-edit">
                    <input
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveNotes(item.symbol);
                        if (e.key === "Escape") setEditingNotes(null);
                      }}
                      placeholder="Note…"
                      aria-label={`Note for ${item.symbol}`}
                      autoFocus
                    />
                    <button className="watchlist-move-btn" onClick={() => saveNotes(item.symbol)} aria-label="Save note">✓</button>
                  </span>
                ) : (
                  <button
                    className="watchlist-notes-view"
                    onClick={() => {
                      setEditingNotes(item.symbol);
                      setNotesDraft(item.notes ?? "");
                    }}
                    title="Edit note"
                  >
                    {item.notes || <em className="muted">add note</em>}
                  </button>
                )}
              </div>

              <div className="watchlist-row-actions">
                <button
                  className="watchlist-move-btn"
                  onClick={() => void refreshQuote(item.symbol)}
                  disabled={busySymbol === item.symbol}
                  aria-label={`Refresh ${item.symbol} quote`}
                  title="Refresh quote"
                >
                  ⟳
                </button>
                <button
                  className="transaction-delete-btn"
                  onClick={() => void handleRemove(item.symbol)}
                  disabled={busySymbol === item.symbol}
                  aria-label={`Remove ${item.symbol} from watchlist`}
                  title="Remove from watchlist"
                >
                  ✕
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <footer className="watchlist-manager-foot">
        {items.length} symbol{items.length === 1 ? "" : "s"} · prices are fetched live through the
        market-data provider each time this page loads; a symbol the provider cannot price shows
        “PRICE UNAVAILABLE” instead of a guess.
      </footer>
    </main>
  );
}
