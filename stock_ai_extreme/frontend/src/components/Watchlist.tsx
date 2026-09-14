import { FormEvent, useState } from "react";
import { useWatchlist } from "../hooks/useMarketQueries";
import type { WatchlistQuote } from "../lib/services";

const fmtPrice = (v: number | null) =>
  v === null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Watchlist panel — saved tickers with a live price and % change.
 *
 * State/data come from `useWatchlist()` (React Query): the list is priced
 * server-side at read time and cached client-side, add/remove invalidate the
 * cache. A ticker the provider can't price shows "no quote" rather than a
 * fabricated number, and gain/loss uses a sign + arrow, not color alone.
 */
export default function Watchlist({ active, onSelect }: { active: string; onSelect: (t: string) => void }) {
  const [input, setInput] = useState("");
  const { data, isLoading, isError, error, refetch, add, remove } = useWatchlist();

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = input.trim();
    if (!t) return;
    add.mutate(t.toUpperCase(), { onSuccess: () => setInput("") });
  }

  const items: WatchlistQuote[] = data?.items ?? [];
  const mutationError = (add.error as Error | null) ?? (remove.error as Error | null);

  return (
    <aside className="panel watchlist" aria-label="Watchlist">
      <div className="watchlist-head">
        <h2>Watchlist</h2>
        {items.length > 0 && <span className="watchlist-count">{items.length}</span>}
      </div>

      <form onSubmit={submit} className="watchlist-add">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add ticker…"
          aria-label="Add to watchlist"
          autoComplete="off"
        />
        <button type="submit" disabled={add.isPending} aria-label="Add ticker">
          {add.isPending ? "…" : "+"}
        </button>
      </form>

      {mutationError && <small className="watchlist-error">{mutationError.message}</small>}

      {isLoading && (
        <ul className="watchlist-skeleton-list" aria-hidden>
          {[0, 1, 2].map((i) => (
            <li key={i} className="watchlist-skeleton">
              <span className="skeleton" style={{ width: 54, height: 14 }} />
              <span className="skeleton" style={{ width: 78, height: 14 }} />
            </li>
          ))}
        </ul>
      )}

      {isError && !isLoading && (
        <div className="watchlist-state" role="alert">
          <span>{(error as Error)?.message || "Could not load watchlist."}</span>
          <button className="watchlist-retry" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <p className="empty">No tickers saved yet — add one above.</p>
      )}

      {!isLoading && !isError && items.length > 0 && (
        <ul>
          {items.map((i) => {
            const priced = i.price !== null && i.change_percent !== null;
            const up = (i.change_percent ?? 0) >= 0;
            return (
              <li key={i.id} className={i.ticker === active ? "active" : ""}>
                <button
                  className="watchlist-ticker"
                  onClick={() => onSelect(i.ticker)}
                  aria-current={i.ticker === active ? "true" : undefined}
                >
                  {i.ticker}
                </button>
                {i.note && <span className="watchlist-note">{i.note}</span>}
                <div className="watchlist-quote">
                  <span className="watchlist-price">{fmtPrice(i.price)}</span>
                  {priced ? (
                    <span className={`watchlist-chg ${up ? "pos" : "neg"}`}>
                      <span aria-hidden>{up ? "▲ +" : "▼ "}</span>
                      {i.change_percent!.toFixed(2)}%
                    </span>
                  ) : (
                    <span className="watchlist-chg muted" title={`Provider status: ${i.status}`}>
                      no quote
                    </span>
                  )}
                </div>
                <button
                  className="watchlist-remove"
                  aria-label={`Remove ${i.ticker}`}
                  onClick={() => remove.mutate(i.ticker)}
                  disabled={remove.isPending}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <small className="watchlist-foot">
        <span className="data-source-indicator">Live quotes</span> · Prices are fetched from the market-data provider
        each time this panel loads; a ticker the provider cannot price shows “no quote” instead of a guess.
      </small>
    </aside>
  );
}
