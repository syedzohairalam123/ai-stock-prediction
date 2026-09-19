/**
 * Phase 12 — Data widget (spec §3 "Data", §4 DATA).
 *
 * Reuses the existing live infrastructure — the Phase-5 `Watchlist` panel
 * (server-priced quotes via React Query) and the Phase-13 `MarketsOverview`
 * board (crypto / commodities / forex from the backend provider layer). No
 * new data plumbing: both children already degrade honestly when a source is
 * unavailable.
 */
import { useNavigate } from "react-router-dom";
import MarketsOverview from "../../MarketsOverview";
import Watchlist from "../../Watchlist";

export default function DataWidget() {
  const navigate = useNavigate();
  return (
    <div className="ws-widget-body ws-data-widget">
      <Watchlist active="" onSelect={(t) => navigate(`/stock/${t}`)} />
      <MarketsOverview />
    </div>
  );
}
