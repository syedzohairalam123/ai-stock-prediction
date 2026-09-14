import { useState } from "react";
import NewsPanel from "../components/NewsPanel";
import BaseBadge from "../components/BaseBadge";

/**
 * Market news & sentiment.
 *
 * Headlines come from the same provider layer as prices (`/api/stocks/{t}/news`),
 * so a PSX ticker resolves to its Karachi listing and a `^`-prefixed symbol
 * gives the broader market. Sentiment is the backend's lexicon heuristic and is
 * always labeled as such — this page never invents a headline or a score.
 */
const NEWS_TICKERS = ["OGDC", "LUCK", "HBL", "MEBL", "SYS", "PSO", "ENGRO", "HUBC"];
const MARKET_SYMBOL = "^GSPC";

export default function NewsPage() {
  const [ticker, setTicker] = useState("OGDC");

  return (
    <main>
      <div className="psx-page-head">
        <div>
          <p>Headlines &amp; sentiment</p>
          <h1>News</h1>
        </div>
        <BaseBadge variant="info">
          {ticker === MARKET_SYMBOL ? "Global market" : `${ticker} · PSX`}
        </BaseBadge>
      </div>

      <div className="quick-tickers" role="group" aria-label="Select a ticker for news">
        <button
          className={`quick-ticker-btn ${ticker === MARKET_SYMBOL ? "active" : ""}`}
          onClick={() => setTicker(MARKET_SYMBOL)}
        >
          Market
        </button>
        {NEWS_TICKERS.map((t) => (
          <button
            key={t}
            className={`quick-ticker-btn ${ticker === t ? "active" : ""}`}
            onClick={() => setTicker(t)}
          >
            {t}
          </button>
        ))}
      </div>

      <NewsPanel ticker={ticker} />
    </main>
  );
}
