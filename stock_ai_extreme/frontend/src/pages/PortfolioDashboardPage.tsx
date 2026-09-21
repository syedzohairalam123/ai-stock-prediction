/**
 * Phase 9 — Portfolio Dashboard (spec K/L/M/R/S).
 *
 * Summary cards, holdings table and a full filterable transaction history,
 * all computed from real transactions and live prices through the provider
 * layer. Positions without a live price show "PRICE UNAVAILABLE" — never a
 * stale or fabricated value — and stay excluded from value/P&L totals.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  usePortfolioData,
  useTransactionFilter,
  usePortfolioPerformance,
  type HoldingRow,
  type PerformancePoint,
} from "../hooks/usePortfolioQueries";
import AddTransactionModal from "../components/AddTransactionModal";
import { formatPkr, formatPct, formatQtyDisplay } from "../lib/finance";
import { downloadCSV } from "../utils/csv";

function PnlValue({ amount, percent }: { amount: number | null; percent: number | null }) {
  if (amount === null) {
    return <span className="pnl-unavailable">—</span>;
  }
  const cls = amount > 0 ? "pnl-pos" : amount < 0 ? "pnl-neg" : "pnl-flat";
  return (
    <span className={cls}>
      <span aria-hidden>{amount > 0 ? "▲ +" : amount < 0 ? "▼ " : ""}</span>
      {formatPkr(amount)}{" "}
      <small>({formatPct(percent)})</small>
    </span>
  );
}

/** Holdings table sorting (ext): click a column header to toggle asc/desc. */
type SortKey =
  | "symbol"
  | "quantity"
  | "averageCost"
  | "currentPrice"
  | "marketValue"
  | "unrealized"
  | "totalReturn"
  | "allocation";

/** Sort key extraction; unpriced values sink to the bottom in either direction. */
function sortValue(row: HoldingRow, key: SortKey): number | string {
  switch (key) {
    case "symbol":
      return row.position.symbol;
    case "quantity":
      return row.position.quantity;
    case "averageCost":
      return row.position.averageCost;
    case "currentPrice":
      return row.currentPrice ?? Number.NEGATIVE_INFINITY;
    case "marketValue":
      return row.marketValue ?? Number.NEGATIVE_INFINITY;
    case "unrealized":
      return row.unrealized.amount ?? Number.NEGATIVE_INFINITY;
    case "totalReturn":
      return row.totalReturn.amount ?? Number.NEGATIVE_INFINITY;
    case "allocation":
      return row.allocationPct ?? Number.NEGATIVE_INFINITY;
  }
}

/** Sortable column header with aria-sort. */
function ThSort({
  label,
  k,
  sortKey,
  sortDir,
  onToggle,
  alignRight,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: 1 | -1;
  onToggle: (k: SortKey) => void;
  alignRight?: boolean;
}) {
  const active = sortKey === k;
  return (
    <th
      scope="col"
      className={alignRight ? "text-right" : undefined}
      aria-sort={active ? (sortDir === 1 ? "ascending" : "descending") : undefined}
    >
      <button
        className={`th-sort ${active ? (sortDir === 1 ? "asc" : "desc") : ""}`}
        onClick={() => onToggle(k)}
      >
        {label}
        <span className="th-sort-arrow" aria-hidden>
          {active ? (sortDir === 1 ? " ↑" : " ↓") : ""}
        </span>
      </button>
    </th>
  );
}

/** Real-data equity curve — dependency-free SVG area chart (no chart lib). */
function PerformanceChart({ points }: { points: PerformancePoint[] }) {
  const W = 800;
  const H = 180;
  const PAD = 6;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const coords = points.map((p, i) => [
    PAD + (i / (points.length - 1)) * (W - 2 * PAD),
    H - PAD - ((p.value - min) / range) * (H - 2 * PAD),
  ]);
  const line = coords.map(([x, y]) => `${x},${y}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  const stroke = up ? "var(--green)" : "var(--red)";
  const areaFill = up ? "var(--green-s)" : "var(--red-s)";
  const first = points[0];
  const last = points[points.length - 1];
  return (
    <div className="performance-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="performance-chart-svg"
        role="img"
        aria-label={`Portfolio value from ${first.date} to ${last.date}`}
        preserveAspectRatio="none"
      >
        <polygon points={`0,${H} ${line} ${W},${H}`} fill={areaFill} stroke="none" />
        <polyline
          points={line}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="performance-chart-axis">
        <span>{first.date}</span>
        <span className={up ? "pnl-pos" : "pnl-neg"}>{formatPkr(last.value)}</span>
        <span>{last.date}</span>
      </div>
    </div>
  );
}

export default function PortfolioDashboardPage() {
  const navigate = useNavigate();
  const {
    transactions,
    holdings,
    summary,
    loading,
    error,
    offline,
    availableQty,
    addTransaction,
    removeTransaction,
    reload,
  } = usePortfolioData();

  const filters = useTransactionFilter(transactions);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalSymbol, setModalSymbol] = useState("");
  const [modalSide, setModalSide] = useState<"BUY" | "SELL">("BUY");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const openModal = (symbol = "", side: "BUY" | "SELL" = "BUY") => {
    setModalSymbol(symbol);
    setModalSide(side);
    setModalOpen(true);
  };

  const heldSymbols = holdings.map((h) => h.position.symbol);

  const totalUnpriced = summary.positions - summary.pricedPositions;

  // ---- performance curve + risk metrics (backend engine, real closes) ----
  const performance = usePortfolioPerformance(180);

  // ---- holdings table sorting ----
  const [sortKey, setSortKey] = useState<SortKey>("marketValue");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 1 ? -1 : 1));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? 1 : -1);
    }
  };

  const sortedHoldings = useMemo(() => {
    const rows = [...holdings];
    rows.sort((a, b) => {
      const va = sortValue(a, sortKey);
      const vb = sortValue(b, sortKey);
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * sortDir;
      }
      return (va - vb) * sortDir;
    });
    return rows;
  }, [holdings, sortKey, sortDir]);

  // ---- CSV exports (real computed data, client-side) ----
  const exportHoldingsCsv = () => {
    downloadCSV(
      "holdings.csv",
      sortedHoldings.map((h) => ({
        Symbol: h.position.symbol,
        Quantity: h.position.quantity,
        "Average Cost (PKR)": h.position.averageCost.toFixed(2),
        "Current Price (PKR)": h.currentPrice ?? "PRICE UNAVAILABLE",
        "Market Value (PKR)": h.marketValue?.toFixed(2) ?? "",
        "Unrealized P&L (PKR)": h.unrealized.amount?.toFixed(2) ?? "",
        "Return %": h.totalReturn.percent?.toFixed(2) ?? "",
        "Allocation %": h.allocationPct?.toFixed(2) ?? "",
      }))
    );
  };

  const exportTransactionsCsv = () => {
    downloadCSV(
      "transactions.csv",
      filters.filtered.map((tx) => ({
        Date: tx.date.slice(0, 10),
        Symbol: tx.symbol,
        Side: tx.side,
        Quantity: tx.quantity,
        "Price (PKR)": tx.price.toFixed(2),
        "Fees (PKR)": tx.fees.toFixed(2),
        "Total Value (PKR)": (
          tx.side === "BUY" ? tx.quantity * tx.price + tx.fees : tx.quantity * tx.price - tx.fees
        ).toFixed(2),
      }))
    );
  };

  return (
    <main className="portfolio-page">
      <div className="psx-page-head">
        <div>
          <p>Transactions · Positions · P&amp;L</p>
          <h1>My Portfolio</h1>
        </div>
        <div className="portfolio-actions">
          <button onClick={reload} disabled={loading} className="portfolio-refresh-btn">
            <svg className={`portfolio-refresh-icon ${loading ? "spinning" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
          <button onClick={() => openModal()} className="portfolio-add-btn">
            + Add Transaction
          </button>
        </div>
      </div>

      {offline && (
        <div className="portfolio-offline-banner" role="status">
          Backend unreachable — changes are saved in this browser and will not sync.
        </div>
      )}

      {error && (
        <div className="portfolio-error" role="alert">
          <p>{error}</p>
          <button onClick={reload}>Try again</button>
        </div>
      )}

      {/* ---------- Summary cards (spec K) ---------- */}
      <section className="portfolio-summary-cards" aria-label="Portfolio summary">
        <div className="portfolio-summary-card">
          <p className="portfolio-summary-card-label">Total Invested</p>
          <p className="portfolio-summary-card-value">{formatPkr(summary.totalInvested)}</p>
        </div>
        <div className="portfolio-summary-card">
          <p className="portfolio-summary-card-label">Current Value</p>
          <p className="portfolio-summary-card-value">
            {summary.pricedPositions < summary.positions && summary.currentValue === 0
              ? "—"
              : formatPkr(summary.currentValue)}
            {totalUnpriced > 0 && (
              <small className="summary-card-note">
                {totalUnpriced} position{totalUnpriced > 1 ? "s" : ""} unpriced
              </small>
            )}
          </p>
        </div>
        <div className="portfolio-summary-card">
          <p className="portfolio-summary-card-label">Unrealized P&amp;L</p>
          <p className="portfolio-summary-card-value">
            <PnlValue amount={summary.unrealizedPnl} percent={summary.unrealizedPnl === null ? null : summary.totalInvested > 0 ? (summary.unrealizedPnl / summary.totalInvested) * 100 : null} />
          </p>
        </div>
        <div className="portfolio-summary-card">
          <p className="portfolio-summary-card-label">Realized P&amp;L</p>
          <p className="portfolio-summary-card-value">
            <PnlValue amount={summary.realizedPnl} percent={null} />
          </p>
        </div>
        <div className="portfolio-summary-card">
          <p className="portfolio-summary-card-label">Total Return</p>
          <p className="portfolio-summary-card-value">
            <PnlValue amount={summary.totalPnl} percent={summary.totalReturnPct} />
          </p>
        </div>
      </section>

      {/* ---------- Performance — equity curve + risk metrics (ext) ---------- */}
      <section className="performance-section" aria-label="Portfolio performance">
        <div className="performance-head">
          <h2 className="section-title">Performance</h2>
          {performance.data && performance.data.points.length > 1 && (
            <span className="performance-window">equity curve · real daily closes · 180d</span>
          )}
        </div>

        {performance.loading && <div className="skeleton" style={{ height: 160 }} aria-busy="true" />}

        {performance.error && (
          <p className="empty" role="status">Performance unavailable — {performance.error}</p>
        )}

        {performance.data?.message && !performance.error && (
          <p className="empty" role="status">{performance.data.message}</p>
        )}

        {performance.data && performance.data.points.length > 1 && (
          <PerformanceChart points={performance.data.points} />
        )}

        {performance.data?.metrics && (
          <div className="performance-metrics">
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Current Value</p>
              <p className="portfolio-summary-card-value">{formatPkr(performance.data.metrics.current_value)}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Net P&amp;L</p>
              <p className="portfolio-summary-card-value">
                <PnlValue amount={performance.data.metrics.net_pnl} percent={performance.data.metrics.net_return_pct} />
              </p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">IRR (annualized)</p>
              <p className="portfolio-summary-card-value">{formatPct(performance.data.metrics.irr_pct)}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">CAGR</p>
              <p className="portfolio-summary-card-value">{formatPct(performance.data.metrics.cagr_pct)}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Volatility (ann.)</p>
              <p className="portfolio-summary-card-value">{formatPct(performance.data.metrics.volatility_pct, false)}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Sharpe Ratio</p>
              <p className="portfolio-summary-card-value">{performance.data.metrics.sharpe_ratio?.toFixed(2) ?? "—"}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Sortino Ratio</p>
              <p className="portfolio-summary-card-value">{performance.data.metrics.sortino_ratio?.toFixed(2) ?? "—"}</p>
            </div>
            <div className="performance-metric">
              <p className="portfolio-summary-card-label">Max Drawdown</p>
              <p className="portfolio-summary-card-value pnl-neg">
                {performance.data.metrics.max_drawdown_pct == null
                  ? "—"
                  : `−${performance.data.metrics.max_drawdown_pct.toFixed(2)}%`}
              </p>
            </div>
          </div>
        )}
      </section>

      {/* ---------- Holdings table (spec L) ---------- */}
      <section className="holdings-section">
        <div className="section-head">
          <h2 className="section-title">Holdings</h2>
          {holdings.length > 0 && (
            <button className="portfolio-refresh-btn" onClick={exportHoldingsCsv}>
              Export CSV
            </button>
          )}
        </div>
        {loading && <div className="skeleton" style={{ height: 180 }} aria-busy="true" />}

        {!loading && holdings.length === 0 && (
          <div className="portfolio-empty">
            <p>No open positions</p>
            <small>Add your first BUY transaction to start tracking P&amp;L.</small>
            <button onClick={() => openModal()} className="portfolio-empty-btn">
              Add Transaction
            </button>
          </div>
        )}

        {!loading && holdings.length > 0 && (
          <div className="holdings-table" role="region" aria-label="Holdings" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <ThSort label="Stock" k="symbol" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} />
                  <ThSort label="Quantity" k="quantity" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Average Cost" k="averageCost" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Current Price" k="currentPrice" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Market Value" k="marketValue" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Unrealized P&L" k="unrealized" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Return %" k="totalReturn" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <ThSort label="Allocation" k="allocation" sortKey={sortKey} sortDir={sortDir} onToggle={toggleSort} alignRight />
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {sortedHoldings.map((h) => {
                  const sym = h.position.symbol;
                  const unpriced = h.currentPrice === null;
                  return (
                    <tr key={sym} className="holdings-row">
                      <td>
                        <button className="holdings-symbol holdings-symbol-link" onClick={() => navigate(`/stock/${sym}`)}>
                          {sym}
                        </button>
                      </td>
                      <td className="text-right">{formatQtyDisplay(h.position.quantity)}</td>
                      <td className="text-right">{formatPkr(h.position.averageCost)}</td>
                      <td className={`text-right ${unpriced ? "price-unavailable" : ""}`}>
                        {unpriced ? "PRICE UNAVAILABLE" : formatPkr(h.currentPrice)}
                      </td>
                      <td className={`text-right ${unpriced ? "price-unavailable" : ""}`}>
                        {h.marketValue === null ? "PRICE UNAVAILABLE" : formatPkr(h.marketValue)}
                      </td>
                      <td className="text-right">
                        {h.unrealized.amount === null ? (
                          <span className="price-unavailable">PRICE UNAVAILABLE</span>
                        ) : (
                          <PnlValue amount={h.unrealized.amount} percent={h.unrealized.percent} />
                        )}
                      </td>
                      <td className={`text-right ${h.totalReturn.amount !== null && h.totalReturn.amount < 0 ? "pnl-neg" : h.totalReturn.amount !== null && h.totalReturn.amount > 0 ? "pnl-pos" : ""}`}>
                        {formatPct(h.totalReturn.percent)}
                      </td>
                      <td className="text-right">{h.allocationPct === null ? "—" : `${h.allocationPct.toFixed(1)}%`}</td>
                      <td>
                        <div className="holdings-row-actions">
                          <button
                            className="holdings-action-btn"
                            onClick={() => openModal(sym, "BUY")}
                            aria-label={`Buy more ${sym}`}
                            title={`Buy more ${sym}`}
                          >
                            Buy
                          </button>
                          <button
                            className="holdings-action-btn"
                            onClick={() => openModal(sym, "SELL")}
                            aria-label={`Sell ${sym}`}
                            title={`Sell ${sym}`}
                          >
                            Sell
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---------- Transaction history (spec M) ---------- */}
      <section className="transactions-section">
        <div className="transactions-header">
          <h2 className="section-title">Transaction History</h2>
          {filters.filtered.length > 0 && (
            <button className="portfolio-refresh-btn" onClick={exportTransactionsCsv}>
              Export CSV
            </button>
          )}
        </div>

        <div className="tx-filters" role="group" aria-label="Transaction filters">
          <div className="tx-filter-group" role="radiogroup" aria-label="Filter by side">
            {(["ALL", "BUY", "SELL"] as const).map((s) => (
              <button
                key={s}
                className={`tx-filter-btn ${filters.side === s ? "active" : ""}`}
                onClick={() => filters.setSide(s)}
                aria-pressed={filters.side === s}
              >
                {s}
              </button>
            ))}
          </div>
          <input
            className="tx-filter-input"
            list="tx-filter-symbols"
            placeholder="Symbol…"
            value={filters.symbol}
            onChange={(e) => filters.setSymbol(e.target.value)}
            aria-label="Filter by symbol"
          />
          <datalist id="tx-filter-symbols">
            {filters.symbols.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <label className="tx-filter-date">
            From
            <input type="date" value={filters.dateFrom} onChange={(e) => filters.setDateFrom(e.target.value)} aria-label="Filter from date" />
          </label>
          <label className="tx-filter-date">
            To
            <input type="date" value={filters.dateTo} onChange={(e) => filters.setDateTo(e.target.value)} aria-label="Filter to date" />
          </label>
          {(filters.side !== "ALL" || filters.symbol || filters.dateFrom || filters.dateTo) && (
            <button
              className="tx-filter-clear"
              onClick={() => {
                filters.setSide("ALL");
                filters.setSymbol("");
                filters.setDateFrom("");
                filters.setDateTo("");
              }}
            >
              Clear
            </button>
          )}
        </div>

        {loading && <div className="skeleton" style={{ height: 120 }} aria-busy="true" />}

        {!loading && filters.filtered.length === 0 && (
          <p className="empty">
            {transactions.length === 0
              ? "No transactions yet."
              : "No transactions match the current filters."}
          </p>
        )}

        {!loading && filters.filtered.length > 0 && (
          <div className="tx-table-wrap" role="region" aria-label="Transactions" tabIndex={0}>
            <table className="tx-table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Stock</th>
                  <th scope="col">Side</th>
                  <th scope="col" className="text-right">Quantity</th>
                  <th scope="col" className="text-right">Price</th>
                  <th scope="col" className="text-right">Fees</th>
                  <th scope="col" className="text-right">Total Value</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filters.filtered.map((tx) => {
                  const total =
                    tx.side === "BUY"
                      ? tx.quantity * tx.price + tx.fees
                      : tx.quantity * tx.price - tx.fees;
                  return (
                    <tr key={tx.id}>
                      <td>{new Date(tx.date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</td>
                      <td>
                        <button className="holdings-symbol holdings-symbol-link" onClick={() => navigate(`/stock/${tx.symbol}`)}>
                          {tx.symbol}
                        </button>
                      </td>
                      <td>
                        <span className={`tx-side-badge ${tx.side === "BUY" ? "buy" : "sell"}`}>{tx.side}</span>
                      </td>
                      <td className="text-right">{formatQtyDisplay(tx.quantity)}</td>
                      <td className="text-right">{formatPkr(tx.price)}</td>
                      <td className="text-right">{formatPkr(tx.fees)}</td>
                      <td className="text-right">{formatPkr(total)}</td>
                      <td>
                        {confirmDeleteId === tx.id ? (
                          <span className="tx-confirm">
                            Delete?
                            <button className="tx-confirm-yes" onClick={() => { void removeTransaction(tx.id); setConfirmDeleteId(null); }}>
                              Yes
                            </button>
                            <button className="tx-confirm-no" onClick={() => setConfirmDeleteId(null)}>
                              No
                            </button>
                          </span>
                        ) : (
                          <button
                            className="transaction-delete-btn"
                            onClick={() => setConfirmDeleteId(tx.id)}
                            aria-label={`Delete ${tx.side} of ${tx.symbol}`}
                            title="Delete transaction"
                          >
                            🗑
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <AddTransactionModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        availableQuantity={modalSymbol ? availableQty(modalSymbol) : 0}
        heldSymbols={heldSymbols}
        initialSymbol={modalSymbol}
        initialType={modalSide}
        submit={addTransaction}
      />
    </main>
  );
}
