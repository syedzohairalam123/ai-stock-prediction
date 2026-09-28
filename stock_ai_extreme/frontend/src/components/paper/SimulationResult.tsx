/**
 * Phase 20 — `SimulationResult` (spec §13/§18).
 *
 * The outcome of a simulation: reference entry, reference exit, price
 * difference and hypothetical P&L. Every number here comes from a real observed
 * value; when there is none, the panel says "not enough data" rather than
 * showing a fabricated result.
 */
import { BarChart3, CircleSlash, TrendingDown, TrendingUp } from "lucide-react";
import {
  PAPER_STATUS_DESCRIPTION,
  formatPaperNumber,
  formatPaperTime,
  type PaperOrder,
  type PaperSimulationResult,
} from "../../lib/paperTrading";

interface SimulationResultProps {
  order: PaperOrder;
  result?: PaperSimulationResult | null;
  onEvaluate?: () => void;
  evaluating?: boolean;
  onCancel?: () => void;
  cancelling?: boolean;
}

export default function SimulationResultCard({
  order,
  result,
  onEvaluate,
  evaluating,
  onCancel,
  cancelling,
}: SimulationResultProps) {
  const isForecast = order.quoteMode === "PROBABILITY";
  const pnl = result?.pnl;
  const hypothetical = pnl ?? null;
  const hasPnl = order.pnl !== null && order.pnl !== undefined;
  const pnlValue = hypothetical?.hypotheticalPnl ?? (hasPnl ? order.pnl : null);
  const pnlUnit = hypothetical?.unit === "PERCENTAGE_POINTS" || isForecast ? "pp" : "";
  const up = (pnlValue ?? 0) >= 0;
  const openable = order.status === "SIMULATED";

  return (
    <section className="paper-result" aria-label="Paper simulation result">
      <header className="paper-result-head">
        <span className={`paper-result-status status-${order.status.toLowerCase()}`}>{order.statusLabel}</span>
        <span className="paper-result-time">{formatPaperTime(order.submittedAt)}</span>
      </header>

      <p className="paper-result-desc">{PAPER_STATUS_DESCRIPTION[order.status]}</p>

      <dl className="paper-result-grid">
        <div>
          <dt>Reference entry</dt>
          <dd>
            {order.referencePrice === null
              ? "—"
              : isForecast
                ? `${formatPaperNumber(order.referencePrice, 2)}%`
                : formatPaperNumber(order.referencePrice, 4)}
          </dd>
        </div>
        <div>
          <dt>Reference exit</dt>
          <dd>
            {order.exitReference === null
              ? "—"
              : isForecast
                ? `${formatPaperNumber(order.exitReference, 2)}%`
                : formatPaperNumber(order.exitReference, 4)}
          </dd>
        </div>
        <div>
          <dt>Price difference</dt>
          <dd>
            {hypothetical
              ? `${hypothetical.priceDifference >= 0 ? "+" : ""}${formatPaperNumber(hypothetical.priceDifference, 4)}`
              : "—"}
          </dd>
        </div>
        <div>
          <dt>Hypothetical P/L</dt>
          <dd className={pnlValue === null ? "mut" : up ? "pos" : "neg"}>
            {pnlValue === null ? (
              "Not enough data"
            ) : (
              <>
                {up ? <TrendingUp size={13} aria-hidden /> : <TrendingDown size={13} aria-hidden />}
                {up ? "+" : ""}
                {formatPaperNumber(pnlValue, 4)} {pnlUnit}
              </>
            )}
          </dd>
        </div>
        {hypothetical?.hypotheticalPnlPercent !== null && hypothetical !== null && (
          <div>
            <dt>Hypothetical P/L %</dt>
            <dd className={up ? "pos" : "neg"}>
              {up ? "+" : ""}
              {formatPaperNumber(hypothetical.hypotheticalPnlPercent, 4)}%
            </dd>
          </div>
        )}
        <div>
          <dt>Quantity</dt>
          <dd>{formatPaperNumber(order.quantity, 8)}</dd>
        </div>
        <div>
          <dt>Estimated notional</dt>
          <dd>{order.notional === null ? "—" : formatPaperNumber(order.notional, 2)}</dd>
        </div>
        {order.orderType === "LIMIT" && (
          <div>
            <dt>Limit condition</dt>
            <dd>
              {order.conditionMet === null
                ? "Not yet determinable"
                : order.conditionMet
                  ? "Reached by a real observation"
                  : "Not reached in the observations so far"}
            </dd>
          </div>
        )}
        <div>
          <dt>Observations checked</dt>
          <dd>{result ? result.observationsChecked : "—"}</dd>
        </div>
        <div>
          <dt>Data mode</dt>
          <dd className={`paper-mode paper-mode-${order.dataMode.toLowerCase()}`}>{order.dataMode}</dd>
        </div>
        <div>
          <dt>Data source</dt>
          <dd>{order.dataSource ?? "—"}</dd>
        </div>
      </dl>

      {result?.message && <p className="paper-result-message">{result.message}</p>}

      {(onEvaluate || onCancel) && (
        <div className="paper-result-actions">
          {onEvaluate && (
            <button type="button" className="paper-action" onClick={onEvaluate} disabled={!openable || evaluating}>
              <BarChart3 size={13} aria-hidden /> {evaluating ? "Evaluating…" : "Evaluate against real data"}
            </button>
          )}
          {onCancel && (
            <button type="button" className="paper-action ghost" onClick={onCancel} disabled={!openable || cancelling}>
              <CircleSlash size={13} aria-hidden /> {cancelling ? "Cancelling…" : "Cancel simulation"}
            </button>
          )}
        </div>
      )}

      <p className="paper-disclaimer">
        Hypothetical result computed from observed prices. Not a real trade, order, or payout — and past
        behaviour does not guarantee future results.
      </p>
    </section>
  );
}
