/**
 * Phase 20 — `QuoteStatus`.
 *
 * The honesty readout for the ticket: which source the number came from, how
 * old it is, and whether it is stale. A stale quote is labelled in words as well
 * as colour (never colour alone) and never presented as "the current price".
 */
import { AlertTriangle, Clock, Database, Wifi } from "lucide-react";
import {
  PAPER_DATA_MODE_LABEL,
  formatPaperAge,
  formatPaperTime,
  type PaperConfig,
  type PaperQuote,
} from "../../lib/paperTrading";

interface QuoteStatusProps {
  quote: PaperQuote | null | undefined;
  config?: PaperConfig;
  /** Compact chip-only rendering for the header. */
  compact?: boolean;
}

const MODE_CLASS: Record<string, string> = {
  LIVE: "live",
  DELAYED: "delayed",
  STALE: "stale",
  SIMULATED: "simulated",
  UNAVAILABLE: "unavailable",
};

export default function QuoteStatus({ quote, config, compact = false }: QuoteStatusProps) {
  if (!quote) {
    return (
      <span className="paper-chip paper-chip-unavailable" role="status">
        <Database size={11} aria-hidden /> NO QUOTE
      </span>
    );
  }

  const mode = quote.dataMode;
  const label = PAPER_DATA_MODE_LABEL[mode] ?? mode;
  const stale = quote.stale || mode === "STALE" || mode === "UNAVAILABLE";
  const overAge =
    quote.ageSeconds !== null && config ? quote.ageSeconds > config.staleAfterSeconds : false;

  return (
    <div className={`paper-quote-status${compact ? " compact" : ""}`}>
      <div className="paper-quote-chips">
        <span
          className={`paper-chip paper-chip-${MODE_CLASS[mode] ?? "unavailable"}`}
          role="status"
          aria-label={`Data mode ${label}`}
        >
          {mode === "LIVE" ? <Wifi size={11} aria-hidden /> : <Database size={11} aria-hidden />}
          <span aria-hidden>{mode === "LIVE" ? "●" : "◆"}</span> {label}
        </span>
        {quote.source && (
          <span className="paper-chip paper-chip-source" title="Where this value came from">
            <Database size={11} aria-hidden /> {quote.source}
          </span>
        )}
        {quote.ageSeconds !== null && (
          <span className="paper-chip paper-chip-age" title={formatPaperTime(quote.timestamp)}>
            <Clock size={11} aria-hidden /> {formatPaperAge(quote.ageSeconds)}
          </span>
        )}
      </div>

      {!compact && (
        <dl className="paper-meta-grid">
          <div>
            <dt>Last updated</dt>
            <dd>{formatPaperTime(quote.timestamp)}</dd>
          </div>
          <div>
            <dt>Provider status</dt>
            <dd>{quote.status}</dd>
          </div>
        </dl>
      )}

      {stale && (
        <p className="paper-stale-warning" role="alert">
          <AlertTriangle size={14} aria-hidden />
          <span>
            <strong>STALE DATA</strong> —{" "}
            {quote.staleReason || (overAge ? "This reading is older than the freshness window." : "No current price is claimed.")}{" "}
            The ticket will not present this as a current price.
          </span>
        </p>
      )}
    </div>
  );
}
