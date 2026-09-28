/**
 * Phase 20 — `RiskInfoPanel` (spec §20).
 *
 * Data source, timestamp, data mode, historical volatility and spread for every
 * simulation. The closing statement is deliberate and always shown: a historical
 * simulation does not guarantee future results.
 */
import { Activity, CircleDollarSign, Info, ShieldAlert } from "lucide-react";
import {
  PAPER_DISCLAIMER,
  formatPaperNumber,
  formatPaperTime,
  type PaperConfig,
  type PaperQuote,
} from "../../lib/paperTrading";

interface RiskInfoPanelProps {
  quote: PaperQuote | null | undefined;
  config?: PaperConfig;
  /** The snapshot captured when the ticket was opened (spec §9/§15). */
  snapshot?: {
    capturedAt: string;
    observedPrice: number | null;
    observedTimestamp: string | null;
    source: string | null;
    dataMode: string | null;
    probabilityYes?: number | null;
    probabilityNo?: number | null;
  } | null;
  /** Opening reading of the *selected* outcome (percentage points). */
  openingProbability?: number | null;
  currentProbability?: number | null;
}

export default function RiskInfoPanel({
  quote,
  config,
  snapshot,
  openingProbability = null,
  currentProbability = null,
}: RiskInfoPanelProps) {
  const isForecast = quote?.quoteMode === "PROBABILITY";
  const delta =
    isForecast && openingProbability !== null && currentProbability !== null
      ? currentProbability - openingProbability
      : null;

  return (
    <section className="paper-risk" aria-label="Simulation information">
      <header className="paper-risk-head">
        <h3>
          <Info size={14} aria-hidden /> Simulation information
        </h3>
      </header>

      <dl className="paper-risk-grid">
        <div>
          <dt>Data source</dt>
          <dd>{quote?.source ?? "—"}</dd>
        </div>
        <div>
          <dt>Timestamp</dt>
          <dd>{formatPaperTime(quote?.timestamp ?? null)}</dd>
        </div>
        <div>
          <dt>Data mode</dt>
          <dd className={`paper-mode paper-mode-${(quote?.dataMode ?? "unavailable").toLowerCase()}`}>
            {quote?.dataMode ?? "UNAVAILABLE"}
          </dd>
        </div>
        <div>
          <dt>Spread</dt>
          <dd>
            {quote?.spread === null || quote?.spread === undefined ? (
              <span title="This source does not publish a bid/ask book">—</span>
            ) : (
              <>
                <CircleDollarSign size={12} aria-hidden /> {formatPaperNumber(quote.spread, 4)}
                {quote.spreadPercent !== null && quote.spreadPercent !== undefined && (
                  <small> ({formatPaperNumber(quote.spreadPercent, 3)}%)</small>
                )}
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Historical volatility</dt>
          <dd>
            {quote?.volatilityPercent === null || quote?.volatilityPercent === undefined ? (
              <span title="Not enough real observations to estimate volatility">Not available</span>
            ) : (
              <>
                <Activity size={12} aria-hidden /> {formatPaperNumber(quote.volatilityPercent, 2)}% annualised
                <small> · {quote.volatilityLookback ?? config?.volatilityLookbackDays ?? 60}d lookback</small>
              </>
            )}
          </dd>
        </div>
        {snapshot && (
          <>
            <div>
              <dt>Ticket opened</dt>
              <dd>{formatPaperTime(snapshot.capturedAt)}</dd>
            </div>
            <div>
              <dt>{isForecast ? "Opening probability" : "Opening observation"}</dt>
              <dd>
                {(() => {
                  const opening = isForecast ? openingProbability ?? snapshot.observedPrice : snapshot.observedPrice;
                  if (opening === null || opening === undefined) return "—";
                  return isForecast ? `${formatPaperNumber(opening, 2)}%` : formatPaperNumber(opening, 4);
                })()}
                {snapshot.source && <small> · {snapshot.source}</small>}
              </dd>
            </div>
            {isForecast && (
              <div>
                <dt>Change since opening</dt>
                <dd className={delta === null ? "mut" : delta >= 0 ? "pos" : "neg"}>
                  {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${formatPaperNumber(delta, 2)} pp`}
                </dd>
              </div>
            )}
          </>
        )}
      </dl>

      {isForecast && (
        <p className="paper-risk-note">
          Probabilities are modelled or aggregated signals from a public forecast source. They are not
          certainty, advice, prices or wagers, and no monetary outcome is attached to them anywhere in this
          terminal.
        </p>
      )}

      <p className="paper-risk-warning" role="note">
        <ShieldAlert size={13} aria-hidden /> {PAPER_DISCLAIMER}
      </p>
    </section>
  );
}
