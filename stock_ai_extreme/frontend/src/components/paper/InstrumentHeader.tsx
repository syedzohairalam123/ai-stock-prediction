/**
 * Phase 20 — `InstrumentHeader` (spec §3).
 *
 * Asset, symbol, current price (or probability), change %, data status and last
 * updated. For a forecast event the "price" slot is the current probability and
 * the wording changes with it — a probability is never labelled as a price.
 */
import { Activity, CalendarClock, TrendingDown, TrendingUp } from "lucide-react";
import {
  formatPaperNumber,
  formatPaperPercent,
  formatPaperTime,
  type PaperConfig,
  type PaperInstrument,
  type PaperQuote,
} from "../../lib/paperTrading";
import QuoteStatus from "./QuoteStatus";

interface InstrumentHeaderProps {
  instrument: PaperInstrument | null;
  quote: PaperQuote | null;
  config?: PaperConfig;
  loading?: boolean;
}

export default function InstrumentHeader({ instrument, quote, config, loading }: InstrumentHeaderProps) {
  const isForecast = quote?.quoteMode === "PROBABILITY" || instrument?.quoteMode === "PROBABILITY";

  if (loading && !instrument) {
    return (
      <header className="paper-head paper-head-loading" aria-busy="true">
        <div className="skeleton" style={{ height: 76 }} />
      </header>
    );
  }

  if (!instrument) {
    return (
      <header className="paper-head paper-head-empty">
        <p>No instrument selected.</p>
      </header>
    );
  }

  const probability = quote?.probabilityYes ?? null;
  const changePercent = quote?.changePercent ?? null;
  const rising = (changePercent ?? 0) >= 0;
  const primary = isForecast ? probability : (quote?.price ?? null);

  return (
    <header className="paper-head">
      <div className="paper-head-top">
        <div className="paper-head-id">
          <span className={`paper-kind paper-kind-${instrument.kind.toLowerCase()}`}>{instrument.kind}</span>
          <h2 title={instrument.displayName}>{instrument.displayName}</h2>
          <span className="paper-symbol">{instrument.symbol}</span>
        </div>
        <QuoteStatus quote={quote} config={config} compact />
      </div>

      <div className="paper-head-quote">
        <div className={`paper-price ${isForecast ? "probability" : rising ? "pos" : "neg"}`}>
          {primary === null ? (
            <span className="paper-price-none" title="No usable value available — nothing is claimed">
              —
            </span>
          ) : isForecast ? (
            <>
              {formatPaperNumber(primary, 1)}
              <small>%</small>
            </>
          ) : (
            formatPaperNumber(primary, 4)
          )}
        </div>

        <div className="paper-head-side">
          {isForecast ? (
            <span className="paper-change mut" title="Forecast probabilities do not have a day change">
              <Activity size={13} aria-hidden /> YES {formatPaperNumber(probability, 1)}% ·{" "}
              NO {formatPaperNumber(quote?.probabilityNo ?? null, 1)}%
            </span>
          ) : changePercent === null ? (
            <span className="paper-change mut" title="Day change is still loading">
              —
            </span>
          ) : (
            <span className={`paper-change ${rising ? "pos" : "neg"}`}>
              {rising ? <TrendingUp size={14} aria-hidden /> : <TrendingDown size={14} aria-hidden />}
              {formatPaperPercent(changePercent)}
            </span>
          )}
          <span className="paper-updated">
            <CalendarClock size={12} aria-hidden /> {formatPaperTime(quote?.timestamp ?? null)}
          </span>
        </div>
      </div>

      {isForecast && quote?.question && (
        <p className="paper-head-question" title={quote.question}>
          {quote.question}
        </p>
      )}
      {isForecast && quote?.closeTime && (
        <p className="paper-head-close">Closes {formatPaperTime(quote.closeTime)}</p>
      )}
    </header>
  );
}
