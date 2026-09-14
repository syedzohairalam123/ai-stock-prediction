import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { MoversData, MoversUniverse } from "../lib/psxMarket";
import { MOVERS_UNIVERSES, getMovers, isMoversUniverse } from "../lib/psxMarket";
import MoverCard from "./MoverCard";
import BaseButton from "./BaseButton";
import { LoadingSkeletonMover } from "./MarketSkeletons";

interface ColumnProps {
  title: string;
  subtitle: string;
  quotes: MoversData["mostActive"];
  tone: "active" | "gain" | "lose";
}

function MoverColumn({ title, subtitle, quotes, tone }: ColumnProps) {
  return (
    <section className={`mover-col mover-col-${tone}`}>
      <div className="mover-col-head">
        <h3>{title}</h3>
        <span className="mover-col-sub">{subtitle}</span>
      </div>
      <div className="mover-col-list">
        {quotes.map((q, i) => (
          <MoverCard key={q.symbol} rank={i + 1} quote={q} />
        ))}
      </div>
    </section>
  );
}

export default function MarketMovers() {
  const [params, setParams] = useSearchParams();
  const universeParam = params.get("universe");
  const [universe, setUniverse] = useState<MoversUniverse>(
    isMoversUniverse(universeParam) ? universeParam : "KSE100"
  );
  const [data, setData] = useState<MoversData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const retry = () => setReloadKey((k) => k + 1);

  // Keep the filter shareable/reloadable via ?universe=.
  useEffect(() => {
    if (params.get("universe") !== universe) {
      const next = new URLSearchParams(params);
      next.set("universe", universe);
      setParams(next, { replace: true });
    }
  }, [universe, params, setParams]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setData(null);
    getMovers(universe)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || "Failed to load market movers"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [universe, reloadKey]);

  const empty = !loading && !error && data && !data.mostActive.length && !data.gainers.length && !data.losers.length;

  return (
    <section className="movers-section">
      <div className="movers-head">
        <div>
          <h2>Market Movers</h2>
          <span className="movers-sub">
            Ranked by live-session volume and price change · mock feed
            {data && !loading ? ` · ${data.universeSize} stocks` : ""}
          </span>
        </div>
        <div className="movers-tabs" role="tablist" aria-label="Stock universe">
          {MOVERS_UNIVERSES.map((u) => (
            <button
              key={u.id}
              role="tab"
              aria-selected={u.id === universe}
              className={u.id === universe ? "active" : ""}
              onClick={() => setUniverse(u.id)}
            >
              {u.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="movers-grid">
          {(["active", "gain", "lose"] as const).map((tone) => (
            <section className="mover-col" key={tone}>
              <div className="mover-col-head">
                <div className="skeleton" style={{ width: 120, height: 16 }} />
                <div className="skeleton" style={{ width: 150, height: 11 }} />
              </div>
              <div className="mover-col-list">
                {Array.from({ length: 5 }).map((_, i) => (
                  <LoadingSkeletonMover key={i} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="market-state market-state-error">
          <strong>Movers unavailable</strong>
          <span>{error} — switch the universe filter and try again.</span>
          <BaseButton variant="outline" size="sm" onClick={retry}>Retry</BaseButton>
        </div>
      )}

      {!loading && !error && empty && (
        <div className="market-state">
          <strong>No movers in this universe</strong>
          <span>Try another filter — KSE 100, All Stocks or All Islamic.</span>
        </div>
      )}

      {!loading && !error && data && !empty && (
        <div className="movers-grid">
          <MoverColumn
            title="Most Active"
            subtitle="Highest traded volume today"
            quotes={data.mostActive}
            tone="active"
          />
          <MoverColumn
            title="Top Gainers"
            subtitle="Biggest percentage gains"
            quotes={data.gainers}
            tone="gain"
          />
          <MoverColumn
            title="Top Losers"
            subtitle="Biggest percentage losses"
            quotes={data.losers}
            tone="lose"
          />
        </div>
      )}
    </section>
  );
}
