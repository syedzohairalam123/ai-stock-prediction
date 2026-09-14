import type { MarketStatus } from "../lib/psxMarket";
import { MARKET_STATUS_LABEL } from "../lib/psxMarket";

export default function MarketStatusBadge({ status, isMock = true }: { status: MarketStatus; isMock?: boolean }) {
  const cls = status.toLowerCase();
  return (
    <span className={`market-status market-status-${cls}`}>
      <span className="market-status-dot" />
      {MARKET_STATUS_LABEL[status]}
      {isMock && <span className="market-status-mock">MOCK FEED</span>}
    </span>
  );
}