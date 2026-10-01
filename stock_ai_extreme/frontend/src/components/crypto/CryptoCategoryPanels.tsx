/**
 * Phase 22C — subcategory views (spec §15/§16/§18).
 *
 * PRE-MARKET    — honest about crypto being continuous: real 24/7 session
 *                 boundaries and upcoming catalysts; never a fake stock open.
 * INSTITUTIONS  — publicly disclosed holdings with source/date/coverage, or
 *                 `NO VERIFIED DATA`.
 * INDUSTRY      — the documented internal taxonomy plus the provider's real
 *                 category snapshot; nothing is invented.
 */
import type {
  IndustryResponse,
  InstitutionsResponse,
  PreSessionResponse,
  SourceCategory,
} from "../../lib/crypto";
import { formatDuration, NA } from "../../lib/cryptoFormat";
import {
  CryptoEmpty,
  CryptoPanel,
  CryptoSkeleton,
  CryptoStat,
  CryptoWidgetError,
} from "./CryptoStates";

// ---------------------------------------------------------------------------
// PRE-MARKET
// ---------------------------------------------------------------------------
export function CryptoPreMarketView({
  data,
  loading,
  error,
  onRetry,
}: {
  data: PreSessionResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <CryptoPanel
      title="Pre-market · continuous session"
      badge={data ? <span className="crypto-chip">{data.label}</span> : undefined}
      className="crypto-premarket-view"
    >
      {loading && !data && <CryptoSkeleton height={220} label="Loading session data" />}
      {error && <CryptoWidgetError title="SESSION DATA UNAVAILABLE" message={error} onRetry={onRetry} />}
      {!loading && !error && !data && <CryptoEmpty reason="No session information was returned." />}

      {data && (
        <>
          <div className="crypto-premarket-note">
            <strong>{data.market_structure.is_24_7 ? "24/7 MARKET" : "SCHEDULED MARKET"}</strong>
            <span>{data.market_structure.statement}</span>
          </div>

          <h3 className="crypto-subhead">Session boundaries</h3>
          <div className="crypto-table-wrap">
            <table className="crypto-table">
              <caption className="sr-only">Upcoming session boundaries for a continuous market</caption>
              <thead>
                <tr>
                  <th scope="col">Period</th>
                  <th scope="col">Current period started</th>
                  <th scope="col">Next boundary</th>
                  <th scope="col">Time remaining</th>
                  <th scope="col">Basis</th>
                </tr>
              </thead>
              <tbody>
                {data.session_boundaries.map((row) => (
                  <tr key={row.period}>
                    <td>{row.period}</td>
                    <td>{new Date(row.current_period_start).toLocaleString()}</td>
                    <td>{new Date(row.next_boundary).toLocaleString()}</td>
                    <td>{formatDuration(row.seconds_to_boundary)}</td>
                    <td className="dim">{row.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="crypto-subhead">Upcoming catalysts</h3>
          {data.market_events ? (
            <p className="crypto-note">See event feed.</p>
          ) : (
            <CryptoEmpty
              title="NO VERIFIED DATA"
              reason={data.event_source_note || "No event source is configured for crypto catalysts."}
            />
          )}

          <h3 className="crypto-subhead">Trending (observed interest)</h3>
          {data.trending && data.trending.length > 0 ? (
            <ul className="crypto-chip-list">
              {data.trending.slice(0, 12).map((coin) => (
                <li key={coin.id} className="crypto-chip">
                  {coin.name} <span className="dim">{coin.symbol}</span>
                  {coin.market_cap_rank != null && <span className="dim"> #{coin.market_cap_rank}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <CryptoEmpty
              title={data.trending_status === "UNAVAILABLE" ? "NO DATA AVAILABLE" : "NO DATA AVAILABLE"}
              reason={data.trending_note || "The trending source returned no entries."}
            />
          )}
        </>
      )}
    </CryptoPanel>
  );
}

// ---------------------------------------------------------------------------
// INSTITUTIONS
// ---------------------------------------------------------------------------
export function CryptoInstitutionsView({
  symbol,
  data,
  loading,
  error,
  onRetry,
}: {
  symbol: string;
  data: InstitutionsResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const holdings = data?.disclosed_holdings ?? null;

  return (
    <CryptoPanel
      title={`Institutions · ${symbol}`}
      badge={
        data ? (
          <span className={`crypto-chip ${data.status === "LIVE" ? "live" : "warn"}`}>{data.status}</span>
        ) : undefined
      }
      className="crypto-institutions-view"
    >
      {loading && !data && <CryptoSkeleton height={200} label="Loading institutional data" />}
      {error && <CryptoWidgetError title="INSTITUTIONAL DATA UNAVAILABLE" message={error} onRetry={onRetry} />}
      {!loading && !error && !data && <CryptoEmpty reason="No institutional data was returned." />}

      {data && (
        <>
          <h3 className="crypto-subhead">Publicly disclosed holdings</h3>
          {holdings ? (
            <>
              <div className="crypto-stat-grid compact">
                <CryptoStat label="Source" value={holdings.source ?? NA} />
                <CryptoStat label="Asset" value={holdings.asset ?? symbol} />
                <CryptoStat label="Total holdings" value={fmtNum(holdings.total_holdings)} />
                <CryptoStat label="Value (USD)" value={fmtMoney(holdings.total_value_usd)} />
                <CryptoStat
                  label="Market-cap share"
                  value={
                    holdings.market_cap_dominance_percent != null
                      ? `${holdings.market_cap_dominance_percent.toFixed(2)}%`
                      : NA
                  }
                />
                <CryptoStat
                  label="Companies reporting"
                  value={holdings.company_count != null ? String(holdings.company_count) : NA}
                />
                <CryptoStat label="Coverage" value={holdings.coverage ?? NA} />
              </div>
              {holdings.limitations && holdings.limitations.length > 0 && (
                <ul className="crypto-limitations">
                  {holdings.limitations.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <CryptoEmpty
              title="NO VERIFIED DATA"
              reason={data.reason ?? "No publicly disclosed holdings were found for this asset."}
            />
          )}

          <h3 className="crypto-subhead">ETF / vehicle flows</h3>
          <CryptoEmpty title="NO VERIFIED DATA" reason={data.etf_flows_note} />

          <h3 className="crypto-subhead">On-chain large holders</h3>
          <CryptoEmpty title="NO VERIFIED DATA" reason={data.onchain_note} />
        </>
      )}
    </CryptoPanel>
  );
}

// ---------------------------------------------------------------------------
// INDUSTRY
// ---------------------------------------------------------------------------
export function CryptoIndustryView({
  data,
  loading,
  error,
  onRetry,
}: {
  data: IndustryResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <CryptoPanel
      title="Industry taxonomy"
      badge={data ? <span className="crypto-chip">{data.taxonomy.type}</span> : undefined}
      className="crypto-industry-view"
    >
      {loading && !data && <CryptoSkeleton height={240} label="Loading industry taxonomy" />}
      {error && <CryptoWidgetError title="INDUSTRY DATA UNAVAILABLE" message={error} onRetry={onRetry} />}
      {!loading && !error && !data && <CryptoEmpty reason="No industry taxonomy was returned." />}

      {data && (
        <>
          <p className="crypto-note">{data.taxonomy.basis}</p>

          <div className="crypto-industry-grid">
            {data.taxonomy.industries.map((industry) => (
              <div key={industry.id} className="crypto-industry-card">
                <header>
                  <strong>{industry.label}</strong>
                  <span className="crypto-chip">{industry.count}</span>
                </header>
                <p>{industry.definition}</p>
                <div className="crypto-chip-list">
                  {industry.symbols.map((symbol) => (
                    <span key={symbol} className="crypto-chip">
                      {symbol}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <h3 className="crypto-subhead">Provider market categories</h3>
          {data.source_categories && data.source_categories.length > 0 ? (
            <div className="crypto-table-wrap">
              <table className="crypto-table">
                <caption className="sr-only">Real market categories published by the provider</caption>
                <thead>
                  <tr>
                    <th scope="col">Category</th>
                    <th scope="col">Market cap</th>
                    <th scope="col">24h change</th>
                  </tr>
                </thead>
                <tbody>
                  {data.source_categories.map((category: SourceCategory) => (
                    <tr key={category.id ?? category.name ?? "unknown"}>
                      <td>{category.name ?? category.id ?? NA}</td>
                      <td>{fmtMoney(category.market_cap)}</td>
                      <td
                        className={
                          (category.market_cap_change_24h ?? 0) >= 0 ? "pos" : "neg"
                        }
                      >
                        {category.market_cap_change_24h != null
                          ? `${category.market_cap_change_24h.toFixed(2)}%`
                          : NA}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <CryptoEmpty
              title="NO DATA AVAILABLE"
              reason={data.source_categories_note || "The provider returned no category snapshot."}
            />
          )}
        </>
      )}
    </CryptoPanel>
  );
}

function fmtNum(value: number | null | undefined): string {
  return value == null ? NA : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function fmtMoney(value: number | null | undefined): string {
  if (value == null) return NA;
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
