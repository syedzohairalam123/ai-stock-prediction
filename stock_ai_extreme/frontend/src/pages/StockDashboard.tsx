import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import Plot from "react-plotly.js";
import { useStockWebSocket } from "../hooks/useStockWebSocket";
import { useStockSnapshot, useStockHistory } from "../hooks/useMarketQueries";
import Watchlist from "../components/Watchlist";
import BacktestPanel from "../components/BacktestPanel";
import IndicatorPanels from "../components/IndicatorPanels";
import CrossAssetPanel from "../components/CrossAssetPanel";
import AlertsPanel from "../components/AlertsPanel";
import BriefingPanel from "../components/BriefingPanel";
import DriftIndicator from "../components/DriftIndicator";
import NewsPanel from "../components/NewsPanel";
import RelatedNews from "../components/RelatedNews";
import ShariahBadge from "../components/ShariahBadge";
import MarketStatusBadge from "../components/MarketStatusBadge";
import BaseButton from "../components/BaseButton";
import EmptyState from "../components/EmptyState";
import { StatCard } from "../lib/api";
import { STOCK_RANGES, isStockRange, rangeWindow, type StockRange } from "../lib/timeframes";
import { MARKET_STATUS_LABEL, fmtCompact, getMarketStatus, getStockMeta, sectorLabel } from "../lib/psxMarket";
import type { DataMeta } from "../lib/services";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
const iso = (d: Date) => d.toISOString().slice(0, 10);

const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

/** Honest data-freshness chip (LIVE / RECENT / CACHED / STALE / UNAVAILABLE). */
function FreshnessChip({ meta }: { meta?: DataMeta }) {
  if (!meta?.status) return null;
  return (
    <span className={`freshness ${meta.status.toLowerCase()}`} title="How fresh this data actually is">
      {meta.status}
      {meta.source ? ` · ${meta.source}` : ""}
    </span>
  );
}

export default function StockDashboard() {
  const { ticker = "" } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const upperTicker = ticker.toUpperCase();

  // --- Phase 5: consolidated snapshot (header + stats) via services/hooks ---
  const snapQ = useStockSnapshot(upperTicker);
  const snap = snapQ.data;

  // --- deep-linkable timeframe (?range=1Y) ---
  const [params, setParams] = useSearchParams();
  const paramRange = params.get("range");
  const [range, setRange] = useState<StockRange>(isStockRange(paramRange) ? paramRange : "1Y");
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (next.get("range") !== range) {
      next.set("range", range);
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range]);

  const histQ = useStockHistory(upperTicker, range);
  const chartRows = histQ.data ?? [];
  const win = useMemo(() => rangeWindow(range), [range]);

  // --- existing forecast / indicator pipeline (unchanged behaviour) ---
  const [history, setHistory] = useState<any[]>([]);
  const [historyMeta, setHistoryMeta] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState("rf");
  const [busy, setBusy] = useState(false);
  const [overlays, setOverlays] = useState<Record<string, boolean>>({ sma: true, ema: false, bb: false });
  const { quote, state } = useStockWebSocket(upperTicker);

  useEffect(() => {
    if (!upperTicker) return;
    const end = iso(new Date());
    const start = iso(new Date(Date.now() - 730 * 86400000));
    setBusy(true);
    setError(null);
    Promise.all([
      fetch(`${API}/api/stocks/${upperTicker}/history`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, end }),
      }).then((r) => r.json()),
      fetch(`${API}/api/stocks/${upperTicker}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, end, horizon: 7, model, lstm_epochs: 20 }),
      }).then((r) => r.json()),
    ])
      .then(([h, p]) => {
        setHistory(Array.isArray(h?.rows) ? h.rows : []);
        setHistoryMeta(h?.meta || null);
        setResult(p);
        const msg = [h?.detail, p?.detail].find((d: any) => typeof d === "string" && d.length > 0);
        if (msg) setError(msg);
      })
      .finally(() => setBusy(false));
  }, [upperTicker, model]);

  function toggleOverlay(key: string) {
    setOverlays((o) => ({ ...o, [key]: !o[key] }));
  }

  const pred: any[] = result?.predictions || [];
  const psxMeta = getStockMeta(upperTicker);
  const sector = sectorLabel(upperTicker, snap?.sector ?? null);
  const session = useMemo(() => getMarketStatus(), []);

  // Prefer the live socket price, then the snapshot, then the last close.
  const price = quote?.price ?? snap?.price ?? history.at(-1)?.Close ?? null;
  const change = snap?.change ?? null;
  const changePct = snap?.change_percent ?? null;
  const up = (changePct ?? change ?? 0) >= 0;
  // The live socket can deliver a price before the snapshot (which carries the
  // day's change) arrives. Showing a green "▲ +— (—%)" in that window asserts a
  // gain that isn't known yet, so render a neutral dash until change data exists.
  const hasChange = change !== null || changePct !== null;

  // --- chart traces (memoized: they'd otherwise rebuild on every render) ---
  const overlayTraces = useMemo(() => {
    const rows = chartRows;
    const dates = rows.map((r) => r.date);
    const col = (k: string) => rows.map((r) => (r as any)[k]);
    return [
      overlays.sma && { x: dates, y: col("sma_10"), type: "scatter", mode: "lines", name: "SMA 10", line: { color: "#facc15", width: 1 } },
      overlays.sma && { x: dates, y: col("sma_30"), type: "scatter", mode: "lines", name: "SMA 30", line: { color: "#fb923c", width: 1 } },
      overlays.ema && { x: dates, y: col("ema_10"), type: "scatter", mode: "lines", name: "EMA 10", line: { color: "#a78bfa", width: 1 } },
      overlays.ema && { x: dates, y: col("ema_26"), type: "scatter", mode: "lines", name: "EMA 26", line: { color: "#818cf8", width: 1 } },
      overlays.bb && { x: dates, y: col("bb_upper"), type: "scatter", mode: "lines", name: "BB Upper", line: { color: "#64748b", width: 1, dash: "dash" } },
      overlays.bb && { x: dates, y: col("bb_lower"), type: "scatter", mode: "lines", name: "BB Lower", line: { color: "#64748b", width: 1, dash: "dash" } },
    ].filter(Boolean) as any[];
  }, [chartRows, overlays]);

  const chartTraces = useMemo(() => {
    const dates = chartRows.map((r) => r.date);
    const base: any[] = [
      {
        x: dates,
        y: chartRows.map((r) => r.Close),
        type: "scatter",
        mode: "lines",
        name: "Historical",
        line: { color: "#2dd4bf", width: 2 },
      },
      ...overlayTraces,
    ];
    // A daily model forecast can't overlay intraday bars — only show it on a
    // daily timeframe.
    if (!win.intraday && pred.length > 0) {
      base.push(
        {
          x: pred.map((x) => x.date),
          y: pred.map((x) => x.price),
          type: "scatter",
          mode: "lines+markers",
          name: "AI forecast",
          line: { color: "#f472b6", dash: "dot", width: 3 },
        },
        {
          x: [...pred.map((x) => x.date), ...pred.map((x) => x.date).reverse()],
          y: [...pred.map((x) => x.upper), ...pred.map((x) => x.lower).reverse()],
          type: "scatter",
          fill: "toself",
          fillcolor: "rgba(244,114,182,.14)",
          line: { color: "transparent" },
          name: "Forecast interval",
        }
      );
    }
    return base;
  }, [chartRows, overlayTraces, pred, win.intraday]);

  if (!upperTicker) {
    return (
      <main>
        <EmptyState variant="search" title="No ticker selected" description="Use the search box above to pick a stock." />
      </main>
    );
  }

  return (
    <main>
      {/* ================= header ================= */}
      <header className="stock-head">
        <div className="stock-head-main">
          <div className="stock-head-id">
            <h1>{snap?.name || upperTicker}</h1>
            <div className="stock-head-sub">
              <span className="stock-ticker">{upperTicker}</span>
              {sector && <span className="stock-sector">{sector}</span>}
              {snap?.exchange && <span className="stock-sector">{snap.exchange}</span>}
              <ShariahBadge symbol={upperTicker} />
            </div>
          </div>

          <div className="stock-quote-block">
            <div className={`stock-price ${up ? "pos" : "neg"}`}>{num(price)}</div>
            <div className={`stock-change ${hasChange ? (up ? "pos" : "neg") : "mut"}`}>
              {hasChange ? (
                <>
                  <span aria-hidden>{up ? "▲ +" : "▼ "}</span>
                  {num(change)} ({num(changePct)}%)
                </>
              ) : (
                <span title="Day change is still loading">—</span>
              )}
            </div>
            <div className="stock-quote-meta">
              {psxMeta && <MarketStatusBadge status={session} isMock={false} />}
              <FreshnessChip meta={snap?.data_meta ?? historyMeta} />
              {quote && (
                <span className={`freshness ${(quote.status || "").toLowerCase()}`} title="Live socket quote">
                  socket {quote.status}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="controls">
          <label>
            Forecast model{" "}
            <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Forecast model">
              <option value="rf">Random Forest</option>
              <option value="ridge">Ridge Regression</option>
              <option value="lstm">TensorFlow LSTM</option>
              <option value="gru">TensorFlow GRU</option>
              <option value="ensemble">Ensemble (all models)</option>
            </select>
          </label>
          <div className="stock-links">
            <Link to={`/company?ticker=${encodeURIComponent(upperTicker)}`}>Fundamentals &amp; dividends →</Link>
            <Link to="/macro">Macro →</Link>
          </div>
        </div>
      </header>

      {/* ================= stat strip ================= */}
      <section className="stock-stats" aria-label="Price statistics">
        <StatCard label="Day high" value={num(snap?.day_high)} />
        <StatCard label="Day low" value={num(snap?.day_low)} />
        <StatCard label="Previous close" value={num(snap?.previous_close)} sub={psxMeta ? MARKET_STATUS_LABEL[session] : undefined} />
        <StatCard label="Open" value={num(snap?.open)} />
        <StatCard label="Volume" value={snap?.volume != null ? fmtCompact(snap.volume) : "—"} />
        <StatCard label="Traded value" value={snap?.traded_value != null ? `₨ ${fmtCompact(snap.traded_value)}` : "—"} />
        <StatCard label="52-week high" value={num(snap?.week52_high)} />
        <StatCard label="52-week low" value={num(snap?.week52_low)} />
      </section>

      {(snapQ.isError || (error && history.length === 0)) && (
        <section className="panel warn-banner" role="alert">
          <h2>No data available for {upperTicker}</h2>
          <p>{snapQ.isError ? (snapQ.error as Error)?.message : error}</p>
          <p className="empty">
            The data provider has no data for this symbol. Check the ticker — PSX symbols (OGDC, LUCK, MEBL…) and US
            symbols (AAPL, MSFT) both resolve automatically.
          </p>
        </section>
      )}

      {snap?.summary && (
        <section className="panel profile">
          <div className="profile-head">
            <h2>{snap.name || upperTicker}</h2>
            <span>{[snap.sector, snap.industry, snap.country].filter(Boolean).join(" · ")}</span>
            {snap.website && (
              <a href={snap.website} target="_blank" rel="noreferrer">
                {snap.website}
              </a>
            )}
          </div>
          <p className="summary">{snap.summary}</p>
        </section>
      )}

      <Watchlist active={upperTicker} onSelect={(t) => navigate(`/stock/${t}`)} />
      <AlertsPanel ticker={upperTicker} />

      {/* ================= chart ================= */}
      <section className="panel chart">
        <div className="chart-head">
          <h2>Interactive price chart</h2>
          <div className="stock-range-tabs" role="tablist" aria-label="Chart timeframe">
            {STOCK_RANGES.map((r) => (
              <button
                key={r}
                role="tab"
                aria-selected={r === range}
                className={r === range ? "active" : ""}
                onClick={() => setRange(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div className="overlay-toggles">
          <label>
            <input type="checkbox" checked={!!overlays.sma} onChange={() => toggleOverlay("sma")} /> SMA 10/30
          </label>
          <label>
            <input type="checkbox" checked={!!overlays.ema} onChange={() => toggleOverlay("ema")} /> EMA 10/26
          </label>
          <label>
            <input type="checkbox" checked={!!overlays.bb} onChange={() => toggleOverlay("bb")} /> Bollinger Bands
          </label>
          <span className="chart-note">
            {range} · {win.intraday ? `${win.interval} intraday bars` : "daily bars"} · state: {state}
          </span>
        </div>

        {histQ.isLoading && <div className="skeleton" style={{ height: 480 }} aria-busy="true" />}

        {!histQ.isLoading && histQ.isError && (
          <div className="market-state market-state-error" role="alert">
            <strong>Chart unavailable</strong>
            <span>{(histQ.error as Error)?.message}</span>
            <BaseButton variant="outline" size="sm" onClick={() => histQ.refetch()}>
              Retry
            </BaseButton>
          </div>
        )}

        {!histQ.isLoading && !histQ.isError && chartRows.length === 0 && (
          <EmptyState
            variant="search"
            title={`No data for ${range}`}
            description="This symbol has no bars for the selected timeframe. Try a longer range."
          />
        )}

        {!histQ.isLoading && !histQ.isError && chartRows.length > 0 && (
          <Plot
            data={chartTraces as any}
            layout={
              {
                uirevision: `${upperTicker}:${range}`,
                title: `${snap?.name || upperTicker} · ${range}`,
                paper_bgcolor: "#10172bbd",
                plot_bgcolor: "#10172bbd",
                font: { color: "#e6edf7" },
                margin: { t: 50, l: 52, r: 20, b: 42 },
                xaxis: { gridcolor: "#263458" },
                yaxis: { gridcolor: "#263458" },
              } as any
            }
            config={{ responsive: true, displaylogo: false }}
            style={{ width: "100%", height: 510 }}
            useResizeHandler
          />
        )}
      </section>

      {/* ================= prediction engine ================= */}
      <section className="panel">
        <h2>Prediction Engine</h2>
        <p>{busy ? "Generating model output…" : `Model: ${result?.model_metrics?.model || model}`}</p>
        <div className="metric">
          <span>Risk</span>
          <strong>{result?.insights?.risk_level || "—"}</strong>
        </div>
        <div className="metric">
          <span>MAE</span>
          <strong>{result?.model_metrics?.mae ?? "—"}</strong>
        </div>
        <div className="metric">
          <span>RMSE</span>
          <strong>{result?.model_metrics?.rmse ?? "—"}</strong>
        </div>
        {result?.baseline_comparison && (
          <div className={`baseline-badge ${result.beats_naive_baseline ? "beats" : "loses"}`}>
            {result.beats_naive_baseline ? "✓ Beats" : "✗ Does not beat"} naive baseline (MAE{" "}
            {result.baseline_comparison.naive_persistence.mae})
          </div>
        )}
        <DriftIndicator ticker={upperTicker} model={model} />
        <h2>Agent Insights</h2>
        {result?.insights?.insights?.map((x: string, i: number) => (
          <p className="insight" key={i}>
            {x}
          </p>
        ))}
        <small>{result?.disclaimer}</small>
      </section>

      <IndicatorPanels rows={history} />
      <CrossAssetPanel ticker={upperTicker} />

      <section className="panel table">
        <h2>Forecast Output</h2>
        <table>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Forecast</th>
              <th scope="col">Lower</th>
              <th scope="col">Upper</th>
            </tr>
          </thead>
          <tbody>
            {pred.map((x: any) => (
              <tr key={x.date}>
                <td>{x.date}</td>
                <td>{x.price}</td>
                <td>{x.lower}</td>
                <td>{x.upper}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <NewsPanel ticker={upperTicker} />
      {/* Phase 8 spec I: news scoped to this ticker. The backend falls back to a
          live publisher query when the stored corpus has nothing for it yet. */}
      <RelatedNews symbol={upperTicker} limit={6} />
      <BacktestPanel ticker={upperTicker} />
      <BriefingPanel ticker={upperTicker} />
    </main>
  );
}
