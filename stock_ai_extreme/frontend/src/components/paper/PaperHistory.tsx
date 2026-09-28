/**
 * Phase 20 — `PaperHistory` (spec §18/§19).
 *
 * Recent simulations: symbol, direction, reference price, current/exit
 * reference, result and timestamp. Explicitly labelled as separate from the real
 * portfolio, because it is a different table in a different store and must never
 * be read as a position.
 */
import { History, Inbox } from "lucide-react";
import {
  formatPaperNumber,
  formatPaperTime,
  type PaperHistoryResponse,
  type PaperOrder,
} from "../../lib/paperTrading";

interface PaperHistoryProps {
  data: PaperHistoryResponse | undefined;
  loading?: boolean;
  error?: string | null;
  activeSymbol?: string | null;
  /** §54: increments whenever a live backend event arrives — a quiet "live" cue. */
  livePulse?: number;
  onSelect?: (order: PaperOrder) => void;
  limit?: number;
}

export default function PaperHistory({
  data,
  loading,
  error,
  activeSymbol,
  livePulse = 0,
  onSelect,
  limit = 8,
}: PaperHistoryProps) {
  const orders = (data?.orders ?? []).slice(0, limit);
  const summary = data?.summary;

  return (
    <section className="paper-history" aria-label="Recent paper simulations">
      <header className="paper-history-head">
        <h3>
          <History size={14} aria-hidden /> Recent simulations
        </h3>
        <span className="paper-history-badge" title={livePulse > 0 ? `Live updates received (${livePulse})` : undefined}>
          {livePulse > 0 ? `live · ${livePulse} update${livePulse === 1 ? "" : "s"}` : "separate from portfolio"}
        </span>
      </header>

      {summary && summary.total > 0 && (
        <p className="paper-history-summary">
          {summary.total} recorded · {summary.simulated} open · {summary.wins} hypothetical wins ·{" "}
          {summary.losses} hypothetical losses
          {summary.hypotheticalTotalPnl !== 0 && (
            <>
              {" "}
              · net{" "}
              <span className={summary.hypotheticalTotalPnl >= 0 ? "pos" : "neg"}>
                {summary.hypotheticalTotalPnl >= 0 ? "+" : ""}
                {formatPaperNumber(summary.hypotheticalTotalPnl, 4)}
              </span>
            </>
          )}
        </p>
      )}

      {loading && <div className="skeleton" style={{ height: 96 }} aria-busy="true" />}

      {!loading && error && (
        <p className="paper-error" role="alert">
          {error}
        </p>
      )}

      {!loading && !error && orders.length === 0 && (
        <p className="paper-history-empty">
          <Inbox size={14} aria-hidden /> No simulations recorded yet. Your first paper scenario will appear
          here.
        </p>
      )}

      {!loading && !error && orders.length > 0 && (
        <div className="paper-history-table-wrap">
          <table className="paper-history-table">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col">Direction</th>
                <th scope="col">Reference</th>
                <th scope="col">Exit / current</th>
                <th scope="col">Result</th>
                <th scope="col">Status</th>
                <th scope="col">Time</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => {
                const isForecast = order.quoteMode === "PROBABILITY";
                const pnl = order.pnl;
                const exit = order.exitReference ?? order.probabilityCurrent ?? null;
                return (
                  <tr
                    key={order.id}
                    className={activeSymbol && order.symbol === activeSymbol ? "active" : ""}
                    onClick={() => onSelect?.(order)}
                    tabIndex={onSelect ? 0 : undefined}
                    onKeyDown={(event) => {
                      if (onSelect && (event.key === "Enter" || event.key === " ")) {
                        event.preventDefault();
                        onSelect(order);
                      }
                    }}
                  >
                    <td className="mono">{order.symbol}</td>
                    <td className={order.side === "SELL" || order.side === "NO" ? "neg" : "pos"}>
                      {isForecast ? order.side : `PAPER ${order.side}`}
                    </td>
                    <td className="mono">
                      {order.referencePrice === null ? "—" : formatPaperNumber(order.referencePrice, 4)}
                    </td>
                    <td className="mono">
                      {exit === null ? "—" : `${formatPaperNumber(exit, 4)}${isForecast && order.exitReference === null ? "" : ""}`}
                    </td>
                    <td className={pnl === null ? "mut" : pnl >= 0 ? "pos" : "neg"}>
                      {pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}${formatPaperNumber(pnl, 4)}`}
                    </td>
                    <td>
                      <span className={`paper-status status-${order.status.toLowerCase()}`}>{order.status}</span>
                    </td>
                    <td className="mut">{formatPaperTime(order.submittedAt)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="paper-disclaimer">
        {data?.disclaimer ??
          "Recent simulations are stored separately from the portfolio tracker. Nothing here is a real position."}
      </p>
    </section>
  );
}
