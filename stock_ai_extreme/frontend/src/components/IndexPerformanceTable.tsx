import { useEffect, useMemo, useState } from "react";
import type { IndexSnapshot, PerfSortKey } from "../lib/psxMarket";
import {
  fmtCompact,
  fmtNum,
  fmtPct,
  fmtPkr,
  fmtSigned,
  getIndexPerformance,
  isShariahIndex,
  sortIndexRows,
} from "../lib/psxMarket";
import { downloadCSV } from "../utils/csv";
import BaseButton from "./BaseButton";
import { LoadingSkeletonTable } from "./MarketSkeletons";

type SortDir = "asc" | "desc";

interface ColumnDef {
  key: PerfSortKey;
  label: string;
  numeric: boolean;
  render: (row: IndexSnapshot) => string;
  cellClass?: (row: IndexSnapshot) => string;
}

const COLUMNS: ColumnDef[] = [
  { key: "name", label: "Index Name", numeric: false, render: (r) => r.name },
  { key: "value", label: "Current Value", numeric: true, render: (r) => fmtNum(r.value) },
  {
    key: "change",
    label: "Change",
    numeric: true,
    render: (r) => fmtSigned(r.change),
    cellClass: (r) => (r.change >= 0 ? "pos" : "neg"),
  },
  {
    key: "changePct",
    label: "Change %",
    numeric: true,
    render: (r) => fmtPct(r.changePct),
    cellClass: (r) => (r.changePct >= 0 ? "pos" : "neg"),
  },
  { key: "totalVolume", label: "Volume", numeric: true, render: (r) => fmtCompact(r.totalVolume) },
  {
    key: "tradedValue",
    label: "Traded Value",
    numeric: true,
    render: (r) => `${fmtPkr(r.tradedValue / 1e6, 1)}M`,
  },
  { key: "open", label: "Open", numeric: true, render: (r) => fmtNum(r.open) },
  { key: "dayHigh", label: "High", numeric: true, render: (r) => fmtNum(r.dayHigh) },
  { key: "dayLow", label: "Low", numeric: true, render: (r) => fmtNum(r.dayLow) },
];

export default function IndexPerformanceTable() {
  const [rows, setRows] = useState<IndexSnapshot[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<PerfSortKey>("changePct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [reloadKey, setReloadKey] = useState(0);
  const retry = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getIndexPerformance()
      .then((r) => alive && setRows(r))
      .catch((e) => alive && setError(e?.message || "Failed to load index performance"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [reloadKey]);

  const sorted = useMemo(
    () => (rows ? sortIndexRows(rows, sortKey, sortDir) : []),
    [rows, sortKey, sortDir]
  );

  const toggleSort = (key: PerfSortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      // Sensible initial direction per column: A→Z for names, best-first for numbers.
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  };

  const lastUpdated = rows?.length
    ? rows.reduce((acc, r) => (r.lastUpdated > acc ? r.lastUpdated : acc), rows[0].lastUpdated)
    : null;

  /** Export the full (unsorted-view-independent) dataset as CSV — reuses utils/csv. */
  const exportCSV = () => {
    if (!rows) return;
    downloadCSV(
      `psx-index-performance.csv`,
      rows.map((r) => ({
        Symbol: r.symbol,
        Index: r.name,
        Shariah: isShariahIndex(r.symbol) ? "Yes" : "No",
        Value: r.value.toFixed(2),
        Change: r.change.toFixed(2),
        ChangePct: r.changePct.toFixed(2),
        Volume: Math.round(r.totalVolume),
        TradedValue: Math.round(r.tradedValue),
        Open: r.open.toFixed(2),
        High: r.dayHigh.toFixed(2),
        Low: r.dayLow.toFixed(2),
        Updated: r.lastUpdated,
      }))
    );
  };

  return (
    <section className="perf-table-section">
      <div className="perf-table-head">
        <div>
          <h2>PSX Index Performance</h2>
          <span className="perf-table-sub">All listed indices · sortable · mock feed</span>
        </div>
        {rows && (
          <div className="perf-table-actions">
            <span className="perf-table-count">
              {rows.length} indices{lastUpdated ? ` · ${lastUpdated}` : ""}
            </span>
            <BaseButton variant="outline" size="sm" onClick={exportCSV}>
              ⬇ CSV
            </BaseButton>
          </div>
        )}
      </div>

      {loading && <LoadingSkeletonTable rows={6} cols={COLUMNS.length} />}

      {!loading && error && (
        <div className="market-state market-state-error">
          <strong>Performance table unavailable</strong>
          <span>{error} — reload the page to retry.</span>
          <BaseButton variant="outline" size="sm" onClick={retry}>Retry</BaseButton>
        </div>
      )}

      {!loading && !error && rows && rows.length === 0 && (
        <div className="market-state">
          <strong>No indices to show</strong>
          <span>The index universe is empty right now.</span>
        </div>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div className="table-scroll" role="region" aria-label="PSX index performance table" tabIndex={0}>
          <table className="perf-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={
                      sortKey === c.key ? (sortDir === "asc" ? "ascending" : "descending") : "none"
                    }
                    className={c.numeric ? "num" : ""}
                  >
                    <button className="perf-sort-btn" onClick={() => toggleSort(c.key)}>
                      {c.label}
                      <span className={`perf-sort-ind${sortKey === c.key ? " on" : ""}`}>
                        {sortKey === c.key ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.symbol} className={r.changePct >= 0 ? "row-up" : "row-down"}>
                  <td>
                    <div className="perf-index-name">
                      <span>{r.name}</span>
                      <span className="perf-index-symbol">{r.symbol}</span>
                      {isShariahIndex(r.symbol) && <span className="shariah-chip">SHARIAH</span>}
                    </div>
                  </td>
                  {COLUMNS.slice(1).map((c) => (
                    <td key={c.key} className={`num ${c.cellClass?.(r) ?? ""}`}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
