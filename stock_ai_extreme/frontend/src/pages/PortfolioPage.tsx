import { Link } from "react-router-dom";
import PortfolioPanel from "../components/PortfolioPanel";
import BaseCard from "../components/BaseCard";

export default function PortfolioPage() {
  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>Your positions, live P&L</p>
          <h1>Portfolio</h1>
        </div>
        <Link to="/portfolio/transactions" className="psx-btn psx-btn-primary">
          Open Portfolio Engine →
        </Link>
      </div>
      <PortfolioPanel />
      <BaseCard padding="md" className="portfolio-hint">
        <p className="empty">
          Position data is stored server-side and priced fresh at read time through the provider
          layer — nothing goes stale. For BUY/SELL transaction tracking with average cost,
          realized/unrealized P&L and full history, open the{" "}
          <Link to="/portfolio/transactions">Portfolio Engine</Link>.
        </p>
      </BaseCard>
    </main>
  );
}