/**
 * Phase 12 — Positions & Trades widget (spec §3, §4 POSITIONS_TRADES).
 *
 * The existing `PortfolioPanel` (server-backed holdings, live-marked P&L)
 * renders as-is. It already shows honest per-row states when the provider
 * cannot price a holding.
 */
import PortfolioPanel from "../../PortfolioPanel";

export default function PositionsTradesWidget() {
  return (
    <div className="ws-widget-body ws-positions-widget">
      <PortfolioPanel />
    </div>
  );
}
