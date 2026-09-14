import { useNavigate } from "react-router-dom";
import type { StockQuote } from "../lib/psxMarket";
import { fmtCompact, fmtNum, fmtPct } from "../lib/psxMarket";

interface Props {
  rank: number;
  quote: StockQuote;
}

/** Deterministic brand-color avatar — generated once per symbol, no external images. */
const AVATAR_COLORS = [
  ["#2dd4bf", "#0d9488"],
  ["#6366f1", "#4338ca"],
  ["#f472b6", "#be185d"],
  ["#facc15", "#a16207"],
  ["#fb923c", "#c2410c"],
  ["#a78bfa", "#6d28d9"],
  ["#4ade80", "#15803d"],
  ["#38bdf8", "#0369a1"],
];

function BrandAvatar({ symbol, isIslamic }: { symbol: string; isIslamic: boolean }) {
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) >>> 0;
  const [from, to] = AVATAR_COLORS[h % AVATAR_COLORS.length];
  return (
    <span
      className={`stock-avatar${isIslamic ? " islamic" : ""}`}
      style={{ background: `linear-gradient(135deg, ${from}, ${to})` }}
      aria-hidden
    >
      {symbol.slice(0, 2)}
    </span>
  );
}

export default function MoverCard({ rank, quote }: Props) {
  const navigate = useNavigate();
  const up = quote.change >= 0;

  return (
    <button
      className={`mover-card ${up ? "up" : "down"}`}
      onClick={() => navigate(`/stock/${quote.symbol}`)}
      aria-label={`${quote.name} (${quote.symbol}) — ${fmtNum(quote.price)} PKR, ${fmtPct(quote.changePct)}. View stock dashboard.`}
      title={`Open ${quote.symbol} dashboard`}
    >
      <span className="mover-rank" aria-label={`Rank ${rank}`}>#{rank}</span>
      <BrandAvatar symbol={quote.symbol} isIslamic={quote.isIslamic} />
      <div className="mover-card-main">
        <div className="mover-card-ticker-row">
          <span className="mover-card-ticker">{quote.symbol}</span>
          {quote.isIslamic && <span className="shariah-chip">HALAL</span>}
        </div>
        <span className="mover-card-name">{quote.name}</span>
      </div>
      <div className="mover-card-quote">
        <span className="mover-card-price">{fmtNum(quote.price)}</span>
        <span className={`mover-card-chg ${up ? "pos" : "neg"}`}>{fmtPct(quote.changePct)}</span>
      </div>
      <div className="mover-card-vol">
        <span className="mover-card-vol-label">Vol</span>
        <span className="mover-card-vol-value">{fmtCompact(quote.volume)}</span>
      </div>
    </button>
  );
}
