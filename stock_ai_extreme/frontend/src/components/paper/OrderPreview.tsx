/**
 * Phase 20 — `OrderPreview` (spec §10).
 *
 * Instrument, direction, order type, reference price, quantity/amount, estimated
 * notional, timestamp and data mode — under a banner that cannot be missed:
 * "PAPER SIMULATION — NOT A REAL ORDER".
 */
import { AlertOctagon, ShieldAlert } from "lucide-react";
import {
  PAPER_BANNER,
  formatPaperNumber,
  formatPaperTime,
  type PaperOrderPreview,
} from "../../lib/paperTrading";

interface OrderPreviewProps {
  preview: PaperOrderPreview;
}

export default function OrderPreview({ preview }: OrderPreviewProps) {
  const isForecast = preview.quoteMode === "PROBABILITY";

  return (
    <section className="paper-preview" aria-label="Paper simulation preview">
      <p className="paper-banner" role="note">
        <AlertOctagon size={14} aria-hidden /> {preview.banner || PAPER_BANNER}
      </p>

      <dl className="paper-preview-grid">
        <div>
          <dt>Instrument</dt>
          <dd>
            {preview.displayName} <span className="mut">({preview.instrument})</span>
          </dd>
        </div>
        <div>
          <dt>Direction</dt>
          <dd className={`paper-direction ${preview.direction === "SELL" || preview.direction === "NO" ? "short" : "long"}`}>
            {preview.directionLabel}
          </dd>
        </div>
        <div>
          <dt>Order type</dt>
          <dd>{preview.orderType}</dd>
        </div>
        <div>
          <dt>{preview.referenceLabel || (isForecast ? "Probability" : "Reference price")}</dt>
          <dd>{preview.referencePrice === null ? "—" : isForecast ? `${formatPaperNumber(preview.referencePrice, 2)}%` : formatPaperNumber(preview.referencePrice, 4)}</dd>
        </div>
        {preview.orderType === "LIMIT" && (
          <div>
            <dt>{isForecast ? "Probability limit" : "Limit price"}</dt>
            <dd>{preview.limitPrice === null ? "—" : formatPaperNumber(preview.limitPrice, 4)}</dd>
          </div>
        )}
        <div>
          <dt>{preview.amountMode === "NOTIONAL" ? "Simulated value" : "Quantity"}</dt>
          <dd>
            {preview.amountMode === "NOTIONAL"
              ? `${formatPaperNumber(preview.amount, 2)} ${preview.currency ?? ""}`.trim()
              : formatPaperNumber(preview.amount, 8)}
          </dd>
        </div>
        <div>
          <dt>Quantity / Amount</dt>
          <dd>{formatPaperNumber(preview.quantity, 8)}</dd>
        </div>
        <div>
          <dt>Estimated notional</dt>
          <dd>{preview.estimatedNotional === null ? "—" : formatPaperNumber(preview.estimatedNotional, 2)}</dd>
        </div>
        <div>
          <dt>Timestamp</dt>
          <dd>{formatPaperTime(preview.timestamp)}</dd>
        </div>
        <div>
          <dt>Data mode</dt>
          <dd className={`paper-mode paper-mode-${preview.dataMode.toLowerCase()}`}>{preview.dataMode}</dd>
        </div>
        <div>
          <dt>Data source</dt>
          <dd>{preview.dataSource ?? "—"}</dd>
        </div>
        {preview.quoteTimestamp && (
          <div>
            <dt>Quote timestamp</dt>
            <dd>{formatPaperTime(preview.quoteTimestamp)}</dd>
          </div>
        )}
      </dl>

      <p className="paper-explanation">
        <ShieldAlert size={13} aria-hidden /> {preview.orderTypeExplanation}
      </p>

      {preview.warnings.length > 0 && (
        <ul className="paper-warnings" role="alert">
          {preview.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <p className="paper-disclaimer">{preview.disclaimer}</p>
    </section>
  );
}
