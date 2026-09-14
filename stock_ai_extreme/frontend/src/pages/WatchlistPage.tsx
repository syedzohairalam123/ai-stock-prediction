import {useNavigate} from "react-router-dom";
import Watchlist from "../components/Watchlist";

export default function WatchlistPage(){
  const navigate=useNavigate();
  return <main>
    <header><p>Your saved tickers, persisted server-side</p><h1>Watchlist</h1></header>
    <Watchlist active="" onSelect={t=>navigate(`/stock/${t}`)}/>
  </main>;
}