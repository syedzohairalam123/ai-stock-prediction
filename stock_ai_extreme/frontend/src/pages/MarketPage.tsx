import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import MarketsOverview from "../components/MarketsOverview";
import MarketMovers from "../components/MarketMovers";
import IndexPerformanceTable from "../components/IndexPerformanceTable";
import IndexCarousel from "../components/IndexCarousel";
import IndexChart from "../components/IndexChart";
import IndexStats from "../components/IndexStats";
import IndexRangeBar from "../components/IndexRangeBar";
import MarketStatusBadge from "../components/MarketStatusBadge";
import BaseBadge from "../components/BaseBadge";
import type { IndexSnapshot, Timeframe } from "../lib/psxMarket";
import { fmtNum, getSnapshot, isTimeframe, listIndices } from "../lib/psxMarket";

export default function MarketPage() {
  const [params, setParams] = useSearchParams();
  const sector = params.get("sector") || null;

  const [snapshots, setSnapshots] = useState<IndexSnapshot[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  // Selected index + timeframe are deep-linkable via ?index=KSE30&tf=1Y.
  const indexParam = params.get("index");
  const tfParam = params.get("tf");
  const [selected, setSelected] = useState(indexParam ?? "KSE100");
  const [timeframe, setTimeframe] = useState<Timeframe>(isTimeframe(tfParam) ? tfParam : "1M");
  const [snapshot, setSnapshot] = useState<IndexSnapshot | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Keep URL in sync (replace: no history spam) so any view is shareable/reloadable.
  useEffect(() => {
    const next = new URLSearchParams(params);
    let changed = false;
    if (next.get("index") !== selected) {
      next.set("index", selected);
      changed = true;
    }
    if (next.get("tf") !== timeframe) {
      next.set("tf", timeframe);
      changed = true;
    }
    if (changed) setParams(next, { replace: true });
  }, [selected, timeframe, params, setParams]);

  // Load the index strip once.
  useEffect(() => {
    let alive = true;
    setListLoading(true);
    listIndices()
      .then((rows) => alive && setSnapshots(rows))
      .catch((e) => alive && setListError(e?.message || "Failed to load indices"))
      .finally(() => alive && setListLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // Load the selected index detail.
  useEffect(() => {
    let alive = true;
    setDetailLoading(true);
    setDetailError(null);
    getSnapshot(selected)
      .then((s) => alive && setSnapshot(s))
      .catch((e) => alive && setDetailError(e?.message || "Failed to load index"))
      .finally(() => alive && setDetailLoading(false));
    return () => {
      alive = false;
    };
  }, [selected]);

  const up = snapshot ? snapshot.change >= 0 : true;

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>PSX indices & interactive charting</p>
          <h1>Market</h1>
        </div>
        {sector && <BaseBadge variant="info">{sector} sector</BaseBadge>}
      </div>

      {/* 1. Index carousel */}
      <IndexCarousel
        snapshots={snapshots}
        selected={selected}
        onSelect={setSelected}
        loading={listLoading}
        error={listError}
      />

      {/* 2. Selected index header */}
      <section className="panel index-detail-head">
        {detailLoading && (
          <div className="skeleton" style={{ width: 260, height: 18, marginBottom: 10 }} />
        )}
        {!detailLoading && snapshot && (
          <>
            <div className="index-detail-title">
              <h2>{snapshot.name}</h2>
              <MarketStatusBadge status={snapshot.status} isMock />
            </div>
            <div className={`index-detail-quote ${up ? "up" : "down"}`}>
              <span className="index-detail-value">{fmtNum(snapshot.value)}</span>
              <span className={`index-detail-change ${up ? "pos" : "neg"}`}>
                {up ? "▲ +" : "▼ "}
                {fmtNum(snapshot.change)} ({up ? "+" : ""}
                {snapshot.changePct.toFixed(2)}%)
              </span>
            </div>
            <div className="index-detail-meta">
              <span>Last updated: {snapshot.lastUpdated}</span>
              <span className="index-detail-mock-note">
                Mock data — not live. Live feed lands with the real API phase.
              </span>
            </div>
          </>
        )}
        {!detailLoading && detailError && (
          <div className="market-state market-state-error">
            <strong>Index unavailable</strong>
            <span>{detailError}</span>
          </div>
        )}
      </section>

      {/* 3. Interactive chart */}
      <IndexChart
        symbol={selected}
        name={snapshot?.name ?? selected}
        prevClose={snapshot?.prevClose}
        timeframe={timeframe}
        onTimeframeChange={setTimeframe}
      />

      {/* 4 + 5 + 6. Stats, day range, 52-week range */}
      <div className="index-detail-grid">
        <section className="panel">
          <h2>Statistics</h2>
          {detailLoading && (
            <div className="skeleton" style={{ height: 180 }} />
          )}
          {!detailLoading && snapshot && <IndexStats snapshot={snapshot} />}
          {!detailLoading && detailError && (
            <div className="market-state market-state-error">{detailError}</div>
          )}
        </section>

        <section className="panel">
          <h2>Day Range</h2>
          {detailLoading && (
            <div className="skeleton" style={{ height: 84 }} />
          )}
          {!detailLoading && snapshot && (
            <IndexRangeBar
              label="Today's trading range"
              low={snapshot.dayLow}
              high={snapshot.dayHigh}
              current={snapshot.value}
            />
          )}
          {!detailLoading && detailError && (
            <div className="market-state market-state-error">{detailError}</div>
          )}

          <div className="index-range-spacer" />

          <h2>52-Week Range</h2>
          {detailLoading && (
            <div className="skeleton" style={{ height: 84 }} />
          )}
          {!detailLoading && snapshot && (
            <IndexRangeBar
              label="52-week range"
              low={snapshot.week52Low}
              high={snapshot.week52High}
              current={snapshot.value}
            />
          )}
          {!detailLoading && detailError && (
            <div className="market-state market-state-error">{detailError}</div>
          )}
        </section>
      </div>

      {/* Phase 3: Market movers + PSX index performance table */}
      <MarketMovers />
      <IndexPerformanceTable />

      {/* Existing Phase-1 real-data markets grid — preserved */}
      <MarketsOverview />
    </main>
  );
}