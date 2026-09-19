import {useNavigate} from "react-router-dom";
import Watchlist from "../components/Watchlist";
import MarketsOverview from "../components/MarketsOverview";

// PSX blue chips — these open the live stock dashboard (the backend resolves
// bare PSX symbols to their Karachi listings automatically).
const QUICK_TICKERS=["OGDC","LUCK","HBL","MEBL","SYS","PSO","ENGRO","HUBC"];

export default function HomePage(){
  const navigate=useNavigate();
  return <main>
    <header>
      <p>AI-powered market intelligence</p>
      <h1>Command Center</h1>
      <div className="quick-tickers">
        {QUICK_TICKERS.map(t=><button key={t} className="quick-ticker-btn" onClick={()=>navigate(`/stock/${t}`)}>{t}</button>)}
      </div>
    </header>
    <Watchlist active="" onSelect={t=>navigate(`/stock/${t}`)}/>
    <MarketsOverview/>
    <section className="panel home-links">
      <h2>Explore</h2>
      <div className="home-links-grid">
        <button onClick={()=>navigate("/screener-classic")}>🔎 Classic Screener — filter the market by real technicals</button>
        <button onClick={()=>navigate("/screener")}>🔎 Advanced Screener — analytical ranking with composite scores</button>
        <button onClick={()=>navigate("/compare")}>📊 Compare — correlation, beta, 3D market map</button>
        <button onClick={()=>navigate("/watchlist")}>⭐ Watchlist — track your tickers</button>
        <button onClick={()=>navigate("/popular")}>🔥 Popular Stocks — live PSX discovery cards</button>
        <button onClick={()=>navigate("/portfolio/transactions")}>💼 Portfolio Engine — transactions, positions & P&L</button>
        <button onClick={()=>navigate("/alerts")}>🔔 Alerts — see everything you're watching for</button>
      </div>
    </section>
  </main>;
}