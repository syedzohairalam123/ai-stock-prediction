/**
 * Phase 12 — Market Movers widget (spec §3, §4 MARKET_MOVERS).
 *
 * The existing `MarketMovers` component (live-session ranked quotes) renders
 * as-is; the widget frame only supplies the scrollable body. The universe
 * tabs inside remain interactive — widgets keep their own state.
 */
import MarketMovers from "../../MarketMovers";

export default function MarketMoversWidget() {
  return (
    <div className="ws-widget-body ws-movers-widget">
      <MarketMovers />
    </div>
  );
}
