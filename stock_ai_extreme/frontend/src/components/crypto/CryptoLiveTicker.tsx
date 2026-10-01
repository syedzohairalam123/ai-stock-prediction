/**
 * Phase 22A — live quote ticker.
 *
 * Merges the REST quote (which carries the rolling 24h statistics) with the
 * WebSocket tick (which carries the freshest price between REST polls). Every
 * number is labelled with where it came from; a missing value renders `N/A`
 * rather than a fabricated zero (spec §2/§99).
 */
import type { QuotePayload } from "../../lib/crypto";
import type { LiveTick } from "../../store/useCryptoStore";
import {
  formatCompact,
  formatPercent,
  formatPrice,
  NA,
  originLabel,
  relTime,
  statusTone,
  toneClass,
} from "../../lib/cryptoFormat";

export interface CryptoLiveTickerProps {
  symbol: string;
  name: string;
  displaySymbol: string;
  quote: QuotePayload | undefined;
  liveTick: LiveTick | undefined;
  loading: boolean;
  error: string | null;
}

export function CryptoLiveTicker({
  symbol,
  name,
  displaySymbol,
  quote,
  liveTick,
  loading,
  error,
}: CryptoLiveTickerProps) {
  // The socket price is the newest observation; fall back to the REST quote.
  const price = liveTick?.price ?? quote?.price ?? null;
  const changePct = quote?.change_percent_24h ?? null;
  const status = liveTick?.dataStatus ?? quote?.status ?? "UNAVAILABLE";
  const source = quote?.source ?? liveTick?.source ?? null;
  const sourceTime = liveTick?.sourceTimestamp ?? quote?.timestamp ?? null;
  const spread =
    quote?.bid != null && quote?.ask != null && quote.ask >= quote.bid
      ? quote.ask - quote.bid
      : null;

  return (
    <section className="crypto-ticker" aria-label={`${name} live quote`}>
      <header className="crypto-ticker-head">
        <div className="crypto-ticker-id">
          <h1>{name}</h1>
          <div className="crypto-ticker-sub">
            <span className="crypto-ticker-symbol">{symbol}</span>
            <span className="crypto-ticker-pair">{displaySymbol}</span>
            <span className={statusTone(status) === "live" ? "crypto-chip live" : "crypto-chip"}>
              {status}
            </span>
            {source && <span className="crypto-chip">{source}</span>}
          </div>
        </div>

        <div className="crypto-ticker-price">
          <div className={`crypto-price ${toneClass(changePct)}`}>
            {loading && price === null ? "…" : formatPrice(price)}
          </div>
          <div className={`crypto-change ${toneClass(changePct)}`}>
            {changePct == null ? (
              <span title="24h change not published">{NA}</span>
            ) : (
              <>
                <span aria-hidden>{changePct >= 0 ? "▲ " : "▼ "}</span>
                {formatPercent(changePct)} <span className="crypto-change-window">24h</span>
              </>
            )}
          </div>
          <div className="crypto-ticker-meta">
            {sourceTime && <span title="Source timestamp (local time)">src {relTime(sourceTime)}</span>}
            {quote?.age_ms != null && <span>age {Math.round(quote.age_ms)} ms</span>}
          </div>
        </div>
      </header>

      {error && (
        <div className="warn-banner" role="alert">
          Live quote unavailable — {error}
        </div>
      )}

      <div className="crypto-stat-grid">
        <Stat label="24h open" value={formatPrice(quote?.open_24h ?? null)} origin={quote?.origin_by_field?.price} />
        <Stat label="24h high" value={formatPrice(quote?.high_24h ?? null)} />
        <Stat label="24h low" value={formatPrice(quote?.low_24h ?? null)} />
        <Stat label="24h volume (base)" value={formatCompact(quote?.volume_24h ?? liveTick?.volume ?? null)} />
        <Stat label="24h volume (quote)" value={formatCompact(quote?.quote_volume_24h ?? null)} />
        <Stat label="Bid" value={formatPrice(quote?.bid ?? null)} />
        <Stat label="Ask" value={formatPrice(quote?.ask ?? null)} />
        <Stat
          label="Spread"
          value={spread == null ? NA : formatPrice(spread)}
          sub={spread == null || !quote?.price ? undefined : `${((spread / quote.price) * 100).toFixed(4)}%`}
        />
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  sub,
  origin,
}: {
  label: string;
  value: string;
  sub?: string;
  origin?: string;
}) {
  return (
    <div className="crypto-stat">
      <span className="crypto-stat-k">{label}</span>
      <span className="crypto-stat-v">{value}</span>
      {(sub || origin) && (
        <span className="crypto-stat-s">
          {sub}
          {origin ? `${sub ? " · " : ""}${originLabel(origin)}` : ""}
        </span>
      )}
    </div>
  );
}
