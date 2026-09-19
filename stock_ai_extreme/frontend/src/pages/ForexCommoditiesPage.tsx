/**
 * Phase 7 — Advanced Forex & Commodities Market Data Center.
 *
 * Forex and commodities are two independent sections on purpose (spec P): each
 * owns its own request, loading state and error state, so a forex outage never
 * blanks the metals out and vice versa.
 *
 * Layout covers spec D (professional grid with bid/ask/spread), E (debounced
 * search), F (sorting on raw numbers), G (refresh + last updated + data mode),
 * K (metal cards with purity, unit, change, sparkline) and Q (responsive).
 *
 * Direction is never colour-only: every movement carries a sign, an arrow icon
 * and the word up/down, so it survives a colour-blind or monochrome screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CommodityService,
  ForexService,
  FOREX_SORT_LABELS,
  ageSeconds,
  commodityMatches,
  formatAge,
  formatPkr,
  formatRate,
  rateDigits,
  forexMatches,
  getDataFreshness,
  isDisplayable,
  refreshFreshness,
  rowsForMetal,
  safeNumber,
  sortForexQuotes,
  type CommodityResponse,
  type DataMode,
  type ForexQuote,
  type ForexResponse,
  type ForexSortKey,
  type Freshness,
  type FreshnessThresholds,
  DEFAULT_THRESHOLDS,
} from "../lib/forexCommodities";

const MODE_ICON: Record<DataMode, string> = { LIVE: "●", DELAYED: "◐", DEMO: "◌", UNAVAILABLE: "○" };
const MODE_TEXT: Record<DataMode, string> = {
  LIVE: "Live",
  DELAYED: "Delayed",
  DEMO: "Demo",
  UNAVAILABLE: "Unavailable",
};
const MODE_HELP: Record<DataMode, string> = {
  LIVE: "The source published this inside the live window.",
  DELAYED: "Real data, but the source's own timestamp is older than the live window (or it only publishes daily).",
  DEMO: "Synthetic demonstration data — not a real market rate.",
  UNAVAILABLE: "No source could price this. Nothing is being guessed.",
};

/** Data mode + source indicator, always with readable text. */
function ModePill({ mode, freshness, source, ageText }: { mode: DataMode; freshness?: Freshness; source?: string; ageText?: string }) {
  return (
    <span className={`fx-pill fx-mode-${mode.toLowerCase()}${freshness ? ` fx-fresh-${freshness.toLowerCase()}` : ""}`} title={MODE_HELP[mode]}>
      <span aria-hidden>{MODE_ICON[mode]}</span>
      {MODE_TEXT[mode]}
      {source ? ` · ${source}` : ""}
      {freshness && freshness !== "UNKNOWN" ? ` · ${freshness.toLowerCase()}` : ""}
      {ageText ? ` · ${ageText}` : ""}
    </span>
  );
}

/**
 * Movement magnitude with enough precision to stay informative: a 0.0039% move
 * must not render as a flat "+0.00%".
 */
function percentText(pct: number, digits?: number): string {
  const places = digits ?? (Math.abs(pct) > 0 && Math.abs(pct) < 0.01 ? 4 : 2);
  return `${Math.abs(pct).toFixed(places)}%`;
}

/** Same number, no invented trailing zeros (0.023 rather than 0.023000). */
function changeText(value: number): string {
  const digits = rateDigits(value);
  return Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** Sign + icon + word + colour. Never colour alone. */
function Movement({ percent, absolute, digits }: { percent: number | null; absolute?: number | null; digits?: number }) {
  const pct = safeNumber(percent);
  if (pct === null) {
    return <span className="chg mut" title="No comparable previous value from the source">— <span className="chg-word">n/a</span></span>;
  }
  const up = pct >= 0;
  const abs = safeNumber(absolute);
  return (
    <span className={`chg ${up ? "pos" : "neg"}`}>
      <span aria-hidden>{up ? "▲" : "▼"}</span>{" "}
      {abs !== null && (
        <>
          {up ? "+" : "−"}
          {changeText(abs)}{" "}
        </>
      )}
      {up ? "+" : "−"}
      {percentText(pct, digits)} <span className="chg-word">{up ? "up" : "down"}</span>
    </span>
  );
}

function Sparkline({ points, label }: { points: number[]; label: string }) {
  const series = points.filter((p) => Number.isFinite(p));
  if (series.length < 2) {
    return <div className="spark spark-empty" title="No comparable history available yet">no trend history</div>;
  }
  const min = Math.min(...series);
  const max = Math.max(...series);
  const span = max - min || 1;
  const width = 120;
  const height = 30;
  const path = series
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i / (series.length - 1)) * width},${height - ((v - min) / span) * height}`)
    .join(" ");
  const rising = series[series.length - 1] >= series[0];
  return (
    <svg className={`spark ${rising ? "pos" : "neg"}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <path d={path} fill="none" strokeWidth="2" />
    </svg>
  );
}

function StateRow({ loading, error, empty, onRetry }: { loading: boolean; error: string | null; empty: boolean; onRetry: () => void }) {
  if (loading) {
    return (
      <p className="empty" role="status">
        Loading real rates…
      </p>
    );
  }
  if (error) {
    return (
      <div className="error-text" role="alert">
        <strong>Could not load data:</strong> {error}
        <button className="chip as-btn" style={{ marginLeft: 12 }} onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (empty) {
    return (
      <p className="empty" role="status">
        No rows to show for the current search.
      </p>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Forex
// ---------------------------------------------------------------------------

function ForexSection({ now }: { now: number }) {
  const [data, setData] = useState<ForexResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<ForexSortKey>("currency");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (force: boolean) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    force ? setRefreshing(true) : setLoading(true);
    setError(null);
    try {
      const payload = await ForexService.getForexQuotes({ refresh: force, signal: controller.signal });
      if (!controller.signal.aborted) setData(payload);
    } catch (err) {
      if (!controller.signal.aborted) setError((err as Error)?.message || "request failed");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    load(false);
    return () => abortRef.current?.abort();
  }, [load]);

  // Debounced search (spec E) — typing must not fire a request per keystroke.
  useEffect(() => {
    const id = window.setTimeout(() => setQuery(search), 300);
    return () => window.clearTimeout(id);
  }, [search]);

  // Optional scheduled refresh. Off by default; always torn down, so it can
  // never become an infinite loop (spec R).
  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => load(true), 60000);
    return () => window.clearInterval(id);
  }, [autoRefresh, load]);

  const thresholds: FreshnessThresholds = data?.thresholds ?? DEFAULT_THRESHOLDS;

  // Freshness decays while the page is open, so it is re-derived on every tick
  // against the same thresholds the server used.
  const quotes = useMemo(() => refreshFreshness<ForexQuote>(data?.quotes ?? [], thresholds, now), [data, thresholds, now]);

  const visible = useMemo(
    () => sortForexQuotes(quotes.filter((q) => forexMatches(q, query)), sortKey, sortDir),
    [quotes, query, sortKey, sortDir]
  );

  const priced = quotes.filter((q) => isDisplayable(q.mid, q.data_mode));
  const bestSpread: number | undefined = priced
    .map((q) => safeNumber(q.spread_percent))
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b)[0];

  function toggleSort(key: ForexSortKey) {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const lastUpdated = quotes.length ? Math.max(...quotes.map((q) => q.timestamp_epoch ?? 0)) || null : null;

  return (
    <section className="panel fx-panel" aria-labelledby="fx-heading">
      <div className="fx-section-head">
        <div>
          <h2 id="fx-heading">Forex — PKR pairs</h2>
          <p className="dim">
            {data?.label ?? "PKR-based data"} · every pair is quoted as &lt;CURRENCY&gt;/PKR with the source&apos;s own bid,
            ask, spread and timestamp.
          </p>
        </div>
        <div className="fx-head-actions">
          <label className="fx-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh 60s
          </label>
          <button className="chip as-btn fx-refresh" onClick={() => load(true)} disabled={refreshing || loading}>
            {refreshing ? "Refreshing…" : "Refresh rates"}
          </button>
        </div>
      </div>

      <div className="fx-meta-line">
        <span>
          <b>Last updated:</b> {lastUpdated ? `${formatAge(ageSeconds(lastUpdated, now))}` : "—"}
        </span>
        <span>
          <b>Pairs:</b> {priced.length}/{data?.count ?? 0} priced
        </span>
        {data?.sources?.length ? (
          <span>
            <b>Sources:</b> {data.sources.join(", ")}
          </span>
        ) : null}
        {bestSpread !== undefined && (
          <span>
            <b>Tightest spread:</b> {bestSpread.toFixed(3)}%
          </span>
        )}
        {data?.fallback_source && (
          <span title={data.fallback_error ?? undefined}>
            <b>Fallback in use:</b> {data.fallback_source}
            {data.fallback_error ? " (unavailable)" : ""}
          </span>
        )}
      </div>

      <div className="row-form fx-controls">
        <label>
          Search currency, name or pair
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="USD, US Dollar, USD/PKR…"
            aria-label="Search forex pairs"
            autoComplete="off"
          />
        </label>
        <span className="dim fx-search-hint">
          {query ? `${visible.length} match${visible.length === 1 ? "" : "es"} for “${query}”` : "matching currency code, name, pair or source"}
        </span>
      </div>

      <StateRow loading={loading} error={error} empty={!loading && !error && visible.length === 0} onRetry={() => load(false)} />

      {(data?.failed?.length ?? 0) > 0 && (
        <div className="warn-banner">
          No source could price: <b>{data!.failed.join(", ")}</b>. Those rows stay visible and marked unavailable rather than
          showing a guess.
        </div>
      )}
      {(data?.rejected_currencies?.length ?? 0) > 0 && (
        <div className="warn-banner">Unrecognised currency codes were ignored: {data!.rejected_currencies.join(", ")}</div>
      )}

      {visible.length > 0 && (
        <div className="fx-table-wrap">
          <table className="fx-table">
            <caption className="sr-only">Forex rates quoted against the Pakistani Rupee</caption>
            <thead>
              <tr>
                {(["currency", "pair", "bid", "ask", "spread"] as ForexSortKey[]).map((key) => (
                  <th key={key} scope="col" aria-sort={sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
                    <button className="fx-sort" onClick={() => toggleSort(key)} title={`Sort by ${FOREX_SORT_LABELS[key]} (raw values)`}>
                      {FOREX_SORT_LABELS[key]}
                      <span aria-hidden>{sortKey === key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}</span>
                    </button>
                  </th>
                ))}
                {/* Absolute change sits beside the percentage so neither is implied */}
                <th scope="col">Change</th>
                <th scope="col" aria-sort={sortKey === "change_percent" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
                  <button className="fx-sort" onClick={() => toggleSort("change_percent")} title="Sort by change % (raw values)">
                    {FOREX_SORT_LABELS.change_percent}
                    <span aria-hidden>{sortKey === "change_percent" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}</span>
                  </button>
                </th>
                <th scope="col" aria-sort={sortKey === "timestamp" ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
                  <button className="fx-sort" onClick={() => toggleSort("timestamp")} title="Sort by source timestamp (raw values)">
                    {FOREX_SORT_LABELS.timestamp}
                    <span aria-hidden>{sortKey === "timestamp" ? (sortDir === "asc" ? " ▲" : " ▼") : ""}</span>
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((q) => {
                const age = ageSeconds(q.timestamp_epoch, now);
                return (
                  <tr key={q.symbol} className={q.data_mode === "UNAVAILABLE" ? "fx-row-unavailable" : undefined}>
                    <td>
                      <b>{q.base_currency}</b> <span className="dim">{q.name}</span>
                    </td>
                    <td>
                      <b>{q.symbol}</b>
                    </td>
                    <td>{formatRate(q.bid)}</td>
                    <td>{formatRate(q.ask)}</td>
                    <td title={q.bid_ask_note ?? undefined}>
                      {formatRate(q.spread)}
                      {q.spread_percent !== null && <span className="dim"> ({q.spread_percent.toFixed(3)}%)</span>}
                    </td>
                    <td className={q.change === null ? "mut" : q.change >= 0 ? "pos" : "neg"}>
                      {q.change === null ? "—" : `${q.change >= 0 ? "+" : "−"}${changeText(q.change)}`}
                    </td>
                    <td>
                      <Movement percent={q.change_percent} />
                    </td>
                    <td>
                      {age === null ? (
                        <span className="mut" title="The source published no timestamp for this rate">
                          unknown
                        </span>
                      ) : (
                        <span title={q.timestamp ?? undefined}>
                          {formatAge(age)}{" "}
                          <span className={`fx-fresh-text fx-fresh-${q.freshness.toLowerCase()}`}>{q.freshness.toLowerCase()}</span>
                        </span>
                      )}
                      {/* market-state + data-source indicator, always visible (never colour alone) */}
                      <div className="fx-row-pill">
                        <ModePill mode={q.data_mode} source={q.source} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="fx-note">
        {visible.some((q) => q.data_mode === "DELAYED") && (
          <>
            <b>Delayed rates:</b> real data whose source timestamp is older than the live window — labelled Delayed rather than
            Live.{" "}
          </>
        )}
        {data?.disclaimer}
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Commodities
// ---------------------------------------------------------------------------

function CommoditySection({ now }: { now: number }) {
  const [data, setData] = useState<CommodityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async (force: boolean) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    force ? setRefreshing(true) : setLoading(true);
    setError(null);
    try {
      const payload = await CommodityService.getCommodityQuotes({ refresh: force, signal: controller.signal });
      if (!controller.signal.aborted) setData(payload);
    } catch (err) {
      if (!controller.signal.aborted) setError((err as Error)?.message || "request failed");
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    load(false);
    return () => abortRef.current?.abort();
  }, [load]);

  useEffect(() => {
    const id = window.setTimeout(() => setQuery(search), 300);
    return () => window.clearTimeout(id);
  }, [search]);

  const thresholds: FreshnessThresholds = data?.thresholds ?? DEFAULT_THRESHOLDS;
  const items = useMemo(
    () => refreshFreshness(data?.items ?? [], thresholds, now),
    [data, thresholds, now]
  );

  const groups = (data?.by_metal ?? []).filter((g) => {
    const rows = items.filter((i) => i.symbol === g.symbol);
    return !query || rows.some((r) => commodityMatches(r, query)) || g.name.toLowerCase().includes(query.toLowerCase());
  });

  const inputs = data?.inputs ?? {};
  const usdpkr = inputs?.usdpkr ?? {};

  return (
    <section className="panel fx-panel" aria-labelledby="commodity-heading">
      <div className="fx-section-head">
        <div>
          <h2 id="commodity-heading">Commodities — PKR per unit</h2>
          <p className="dim">
            {data?.label ?? "PKR-based data"} Units are never mixed: per gram, per 10 gram and per tola are shown as separate,
            explicitly labelled values.
          </p>
        </div>
        <div className="fx-head-actions">
          <button className="chip as-btn fx-refresh" onClick={() => load(true)} disabled={refreshing || loading}>
            {refreshing ? "Refreshing…" : "Refresh metals"}
          </button>
        </div>
      </div>

      <div className="fx-meta-line">
        <span>
          <b>Metals priced:</b> {data?.priced_count ?? 0}/{data?.count ?? 0} rows
        </span>
        <span>
          <b>USD/PKR used:</b> {formatRate(usdpkr.rate)} {usdpkr.source ? `(${usdpkr.source})` : ""}
        </span>
        <span>
          <b>Last updated:</b> {usdpkr.timestamp ? formatAge(ageSeconds(usdpkr.timestamp, now)) : "—"}
        </span>
      </div>

      <div className="row-form fx-controls">
        <label>
          Search metal, purity or unit
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="gold, 22K, tola…"
            aria-label="Search commodities"
            autoComplete="off"
          />
        </label>
      </div>

      <StateRow loading={loading} error={error} empty={!loading && !error && groups.length === 0} onRetry={() => load(false)} />

      {(data?.unavailable?.length ?? 0) > 0 && (
        <div className="warn-banner">
          Rows without a usable price: <b>{data!.unavailable.join(", ")}</b> — left blank and explained rather than filled in.
        </div>
      )}

      {groups.length > 0 && (
        <div className="fx-cards">
          {groups.map((group) => {
            const rows = rowsForMetal(items, group.symbol);
            const primary = rows[0];
            if (!primary) return null;
            const others = rows.filter((r) => r !== primary);
            const age = ageSeconds(primary.timestamp_epoch, now);
            const priced = primary.price !== null && primary.data_mode !== "UNAVAILABLE";
            return (
              <article className="card metal-card" key={group.symbol}>
                <div className="card-h">
                  <h3>
                    {group.name} <span className="metal-purity">{group.purity}</span>
                  </h3>
                  <ModePill mode={primary.data_mode} source={primary.source} />
                </div>
                <div className="card-b">
                  <div className={`v metal-price ${primary.change_percent !== null ? (primary.change_percent >= 0 ? "pos" : "neg") : ""}`}>
                    {priced ? `₨ ${formatPkr(primary.price, 2)}` : "—"}
                  </div>
                  <div className="s">
                    <b>{primary.unit}</b>
                    {group.fineness ? ` · fineness ${group.fineness}` : ""}
                  </div>
                  <div className="metal-change">
                    <Movement percent={primary.change_percent} absolute={primary.change} digits={2} />
                  </div>
                  <div className="metal-meta">
                    <span className={`fx-fresh-text fx-fresh-${primary.freshness.toLowerCase()}`}>
                      {primary.freshness.toLowerCase()}
                    </span>
                    <span className="dim"> · updated {age === null ? "unknown" : formatAge(age)}</span>
                  </div>
                  <Sparkline points={primary.sparkline_pkr} label={`${group.name} trend, 30 recorded sessions`} />
                  {others.length > 0 && (
                    <ul className="metal-units">
                      {others.map((row) => (
                        <li key={row.id}>
                          <span className="dim">{row.unit}</span>
                          <b>{row.price === null ? "—" : `₨ ${formatPkr(row.price, 2)}`}</b>
                        </li>
                      ))}
                    </ul>
                  )}
                  {primary.error && <p className="metal-error">{primary.error}</p>}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {data && (
        <details className="derivation">
          <summary>How these PKR values are derived (and what they are not)</summary>
          <div className="derivation-body">
            <p>
              <b>Formula:</b> {data.derivation}
            </p>
            <p className="dim">{data.units.definition}</p>
            <table>
              <thead>
                <tr>
                  <th scope="col">Source series</th>
                  <th scope="col">USD / troy oz</th>
                  <th scope="col">Previous close</th>
                  <th scope="col">Bid</th>
                  <th scope="col">Ask</th>
                </tr>
              </thead>
              <tbody>
                {["XAU", "XAG", "XPT"].map((series) => {
                  const row = inputs[series];
                  if (!row) return null;
                  return (
                    <tr key={series}>
                      <td>
                        {series} <span className="dim">{row.contract}</span>
                      </td>
                      <td>{formatRate(row.usd_per_troy_ounce)}</td>
                      <td>{formatRate(row.previous_close_usd_per_troy_ounce)}</td>
                      <td>{formatRate(row.bid)}</td>
                      <td>{formatRate(row.ask)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="dim">
              USD/PKR leg: {formatRate(usdpkr.rate)} from {usdpkr.source ?? "unknown"} ({usdpkr.status ?? "unknown"}
              {usdpkr.timestamp ? `, ${usdpkr.timestamp}` : ""})
            </p>
            <p className="fx-note">{data.disclaimer}</p>
          </div>
        </details>
      )}

    </section>
  );
}

// ---------------------------------------------------------------------------

export default function ForexCommoditiesPage() {
  // A single clock drives freshness re-evaluation for both sections. It only
  // re-renders — it never issues a request, so it cannot become a refresh loop.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <main>
      <header className="page-head">
        <div>
          <p>Advanced forex &amp; commodities market data center</p>
          <h1>Forex &amp; Commodities</h1>
        </div>
        <span className="fx-badge-pkr" title="Every rate on this page is quoted or converted against the Pakistani Rupee">
          PKR-based data
        </span>
      </header>

      <p className="dim fx-intro">
        Live, keyless sources: exchange-rate and metals quotes come from Yahoo Finance, with the daily ExchangeRate-API feed as a
        labelled fallback when a pair cannot be priced. Bullion values are international-parity conversions of the COMEX
        front-month price at the live USD/PKR rate, not the local retail board.
      </p>

      {/* Independent sections: neither can blank out the other. */}
      <ForexSection now={now} />
      <CommoditySection now={now} />
    </main>
  );
}
