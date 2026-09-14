import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import IndexCarousel from "../components/IndexCarousel";
import IndexChart from "../components/IndexChart";
import IndexStats from "../components/IndexStats";
import IndexRangeBar from "../components/IndexRangeBar";
import MarketStatusBadge from "../components/MarketStatusBadge";
import BaseBadge from "../components/BaseBadge";
import BaseButton from "../components/BaseButton";
import EmptyState from "../components/EmptyState";
import type { IndexSnapshot, Timeframe } from "../lib/psxMarket";
import { fmtNum, getSnapshot, isTimeframe, listIndices } from "../lib/psxMarket";

/**
 * Index detail (`/index/:symbol`).
 *
 * Displays value, absolute/percent change, an interactive chart with all
 * timeframes (1D…5Y), and open/high/low/previous-close/volume/traded-value plus
 * day and 52-week ranges.
 *
 * HONESTY: PSX index levels are not available from the current free provider,
 * so this page is backed by the labelled deterministic demo dataset — the
 * `DEMO` badge and the status chip make that explicit. No value here is
 * presented as a live index print.
 */
export default function IndexPage() {
  const { symbol = "KSE100" } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const upper = symbol.toUpperCase();

  const [params, setParams] = useSearchParams();
  const tfParam = params.get("tf");
  const [timeframe, setTimeframe] = useState<Timeframe>(isTimeframe(tfParam) ? tfParam : "1M");

  const [rows, setRows] = useState<IndexSnapshot[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [snap, setSnap] = useState<IndexSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Keep the timeframe deep-linkable (?tf=1Y).
  useEffect(() => {
    const next = new URLSearchParams(params);
    if (next.get("tf") !== timeframe) {
      next.set("tf", timeframe);
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeframe]);

  useEffect(() => {
    let alive = true;
    setListLoading(true);
    listIndices()
      .then((r) => alive && setRows(r))
      .catch((e) => alive && setListError(e?.message || "Failed to load indices"))
      .finally(() => alive && setListLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setSnap(null);
    getSnapshot(upper)
      .then((s) => alive && setSnap(s))
      .catch((e) => alive && setError(e?.message || `Unknown index: ${upper}`))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [upper]);

  const up = snap ? snap.change >= 0 : true;

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>Index analysis</p>
          <h1>{snap?.name ?? upper}</h1>
        </div>
        <div className="index-head-badges">
          <BaseBadge variant="info">PSX Index</BaseBadge>
          {snap && <MarketStatusBadge status={snap.status} isMock />}
          <Link to="/market" className="ann-link">
            All indices →
          </Link>
        </div>
      </div>

      {/* index switcher */}
      <IndexCarousel
        snapshots={rows}
        selected={upper}
        onSelect={(s) => navigate(`/index/${s}?tf=${timeframe}`)}
        loading={listLoading}
        error={listError}
      />

      {/* quote header */}
      <section className="panel index-detail-head">
        {loading && <div className="skeleton" style={{ width: 280, height: 44 }} aria-busy="true" />}

        {!loading && error && (
          <div className="market-state market-state-error" role="alert">
            <strong>Index unavailable</strong>
            <span>{error}</span>
            <BaseButton variant="outline" size="sm" onClick={() => navigate("/market")}>
              Back to market
            </BaseButton>
          </div>
        )}

        {!loading && !error && snap && (
          <>
            <div className="index-detail-title">
              <h2>{snap.name}</h2>
              <span className="index-detail-ticker">{snap.symbol}</span>
            </div>
            <div className={`index-detail-quote ${up ? "up" : "down"}`}>
              <span className="index-detail-value">{fmtNum(snap.value)}</span>
              <span className={`index-detail-change ${up ? "pos" : "neg"}`}>
                <span aria-hidden>{up ? "▲ +" : "▼ "}</span>
                {fmtNum(snap.change)} ({up ? "+" : ""}
                {snap.changePct.toFixed(2)}%)
              </span>
            </div>
            <div className="index-detail-meta">
              <span>Last updated: {snap.lastUpdated}</span>
              <span className="index-detail-mock-note">DEMO data — not a live index print.</span>
            </div>
          </>
        )}
      </section>

      {/* interactive chart with timeframes */}
      {!loading && !error && snap && (
        <IndexChart
          symbol={snap.symbol}
          name={snap.name}
          prevClose={snap.prevClose}
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
        />
      )}

      {/* stats + ranges */}
      {!loading && !error && snap && (
        <div className="index-detail-grid">
          <section className="panel">
            <h2>Statistics</h2>
            <IndexStats snapshot={snap} />
          </section>

          <section className="panel">
            <h2>Day Range</h2>
            <IndexRangeBar label="Today's trading range" low={snap.dayLow} high={snap.dayHigh} current={snap.value} />
            <div className="index-range-spacer" />
            <h2>52-Week Range</h2>
            <IndexRangeBar label="52-week range" low={snap.week52Low} high={snap.week52High} current={snap.value} />
          </section>
        </div>
      )}

      {!loading && !error && !snap && (
        <EmptyState
          variant="search"
          title={`Unknown index: ${upper}`}
          description="Pick one of the supported PSX indices from the strip above, or open the Market page."
        />
      )}
    </main>
  );
}
