import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { AnnouncementFilters, AnnouncementsPage, AnnSource } from "../lib/announcements";
import { ANN_EVENTS, AnnouncementService, EVENT_META, fmtFetchedAt } from "../lib/announcements";
import AnnouncementCard from "../components/AnnouncementCard";
import BaseButton from "../components/BaseButton";
import { LoadingSkeletonTable } from "../components/MarketSkeletons";

const PAGE_SIZE = 12;
const REFRESH_MS = 5 * 60 * 1000;

/** Read initial filter state from the URL (deep-linkable views). */
function readParams(p: URLSearchParams): AnnouncementFilters & { q: string } {
  const src = p.get("source");
  return {
    source: src === "simulated" ? "simulated" : "company",
    event: p.get("event") || "ALL",
    sentiment: p.get("sentiment") || "ALL",
    ticker: p.get("ticker") || "",
    company: p.get("company") || "",
    search: p.get("q") || "",
    q: p.get("q") || "",
    dateFrom: p.get("from") || "",
    dateTo: p.get("to") || "",
    page: Math.max(1, Number(p.get("page") || 1)),
    pageSize: PAGE_SIZE,
  };
}

/** 7-slot pagination window: 1 … p-1 p p+1 … last */
function pageWindow(page: number, total: number): number[] {
  const out = new Set<number>([1, total, page - 1, page, page + 1]);
  for (let i = 2; i <= Math.min(3, total); i++) out.add(i);
  return [...out].filter((n) => n >= 1 && n <= total).sort((a, b) => a - b);
}

export default function AnnouncementsPage() {
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState(() => readParams(params));
  const [data, setData] = useState<AnnouncementsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Mirror filter state into the URL (replace: no history spam) — shareable views.
  useEffect(() => {
    const next = new URLSearchParams(params);
    const put = (k: string, v: string) => {
      if (v) next.set(k, v);
      else next.delete(k);
    };
    put("source", filters.source === "simulated" ? "simulated" : "");
    put("event", filters.event && filters.event !== "ALL" ? filters.event : "");
    put("sentiment", filters.sentiment && filters.sentiment !== "ALL" ? filters.sentiment : "");
    put("ticker", filters.ticker?.trim() || "");
    put("company", filters.company?.trim() || "");
    put("q", filters.q?.trim() || "");
    put("from", filters.dateFrom || "");
    put("to", filters.dateTo || "");
    put("page", String(filters.page ?? 1));
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  // Fetch page whenever filters change (or a manual retry is requested).
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    AnnouncementService.fetchPage(filters)
      .then((d) => {
        if (!alive) return;
        setData(d);
        // Keep the local page in sync with server-side clamping.
        if (d.page !== filters.page) setFilters((f) => ({ ...f, page: d.page }));
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load announcements");
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [filters, reloadKey]);

  // Background auto-refresh: silently re-fetch when new filings land.
  useEffect(() => {
    if (filters.source !== "company") return;
    const t = setInterval(() => setReloadKey((k) => k + 1), REFRESH_MS);
    return () => clearInterval(t);
  }, [filters.source]);

  const setFilter = <K extends keyof AnnouncementFilters>(key: K, value: AnnouncementFilters[K]) =>
    setFilters((f) => ({ ...f, [key]: value, page: 1 }));

  const onSearchInput = (v: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setFilter("search", v), 300);
  };

  const retry = () => setReloadKey((k) => k + 1);

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>PSX filings & corporate events · AI intelligence</p>
          <h1>Announcements</h1>
        </div>
        <span className={`ann-live-chip ann-live-${(data?.source_status ?? "LIVE").toLowerCase()}`} role="status">
          {data?.source_status === "LIVE" && "● LIVE PSX feed"}
          {data?.source_status === "STALE" && "◐ Cached feed"}
          {data?.source_status === "SIMULATED" && "◇ DEMO data"}
          {data?.source_status === "UNAVAILABLE" && "○ Unavailable"}
        </span>
      </div>

      {/* ---- filter bar ---- */}
      <section className="ann-filters" aria-label="Announcement filters">
        <input
          className="ann-search"
          type="search"
          placeholder="Search company, ticker, title, event…"
          defaultValue={filters.q}
          onChange={(e) => onSearchInput(e.target.value)}
          aria-label="Search announcements"
        />
        <select
          value={filters.source}
          onChange={(e) => setFilter("source", e.target.value as AnnSource)}
          aria-label="Data source"
        >
          <option value="company">Real PSX feed</option>
          <option value="simulated">Demo dataset</option>
        </select>
        <select value={filters.event} onChange={(e) => setFilter("event", e.target.value)} aria-label="Event category">
          <option value="ALL">All event types</option>
          {ANN_EVENTS.map((e) => (
            <option key={e} value={e}>
              {EVENT_META[e].label}
            </option>
          ))}
        </select>
        <select
          value={filters.sentiment}
          onChange={(e) => setFilter("sentiment", e.target.value)}
          aria-label="Sentiment"
        >
          <option value="ALL">Any sentiment</option>
          <option value="POSITIVE">Positive only</option>
          <option value="NEGATIVE">Negative only</option>
          <option value="MIXED">Mixed only</option>
          <option value="NEUTRAL">Neutral only</option>
        </select>
        <input
          className="ann-ticker-input"
          placeholder="Ticker e.g. OGDC"
          value={filters.ticker ?? ""}
          onChange={(e) => setFilter("ticker", e.target.value.toUpperCase())}
          aria-label="Filter by ticker"
          size={10}
        />
        <input
          className="ann-company-input"
          placeholder="Company name"
          value={filters.company ?? ""}
          onChange={(e) => setFilter("company", e.target.value)}
          aria-label="Filter by company"
          size={16}
        />
        <input
          type="date"
          value={filters.dateFrom ?? ""}
          onChange={(e) => setFilter("dateFrom", e.target.value)}
          aria-label="From date"
        />
        <input
          type="date"
          value={filters.dateTo ?? ""}
          onChange={(e) => setFilter("dateTo", e.target.value)}
          aria-label="To date"
        />
      </section>

      <p className="ann-disclaimers">
        {data?.source_disclaimer} {data?.ai_disclaimer}
      </p>

      {/* ---- states ---- */}
      {loading && (
        <div className="ann-list" aria-busy="true">
          <LoadingSkeletonTable rows={4} cols={1} />
          <LoadingSkeletonTable rows={4} cols={1} />
        </div>
      )}

      {!loading && error && (
        <div className="market-state market-state-error">
          <strong>Announcements unavailable</strong>
          <span>{error}</span>
          <BaseButton variant="outline" size="sm" onClick={retry}>
            Retry
          </BaseButton>
        </div>
      )}

      {!loading && !error && data && data.total === 0 && (
        <div className="market-state">
          <strong>No announcements match</strong>
          <span>Widen the filters or clear the search to see more filings.</span>
        </div>
      )}

      {!loading && !error && data && data.total > 0 && (
        <>
          <div className="ann-meta-row">
            <span className="ann-count">
              {data.total} announcements{data.total_pages > 1 ? ` · page ${data.page}/${data.total_pages}` : ""}
            </span>
            {data.fetched_at && <span className="ann-fetched">Updated {fmtFetchedAt(data.fetched_at)}</span>}
          </div>
          <div className="ann-list">
            {data.items.map((a) => (
              <AnnouncementCard key={a.id} ann={a} />
            ))}
          </div>

          {/* ---- pagination ---- */}
          {data.total_pages > 1 && (
            <nav className="ann-pager" aria-label="Announcements pagination">
              <BaseButton
                variant="secondary"
                size="sm"
                disabled={!data.prev_page}
                onClick={() => setFilter("page", data.prev_page ?? 1)}
              >
                ← Prev
              </BaseButton>
              {pageWindow(data.page, data.total_pages).map((p) => (
                <button
                  key={p}
                  className={`ann-page-btn${p === data.page ? " active" : ""}`}
                  onClick={() => setFilter("page", p)}
                  aria-current={p === data.page ? "page" : undefined}
                >
                  {p}
                </button>
              ))}
              <BaseButton
                variant="secondary"
                size="sm"
                disabled={!data.next_page}
                onClick={() => setFilter("page", data.next_page ?? 1)}
              >
                Next →
              </BaseButton>
            </nav>
          )}
        </>
      )}
    </main>
  );
}
