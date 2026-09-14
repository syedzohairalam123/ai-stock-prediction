import {useState} from "react";
import {useNavigate} from "react-router-dom";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";

interface ScreenerResult {
  universe_size:number;
  scanned:number;
  matched:number;
  failed:string[];
  results:any[];
}

export default function ScreenerPage(){
  const navigate=useNavigate();
  const [filters,setFilters]=useState({minPctChange:"",maxPctChange:"",minRsi:"",maxRsi:"",trend:"",sortBy:"pct_change",sortDesc:true});
  const [result,setResult]=useState<ScreenerResult|null>(null),[busy,setBusy]=useState(false);

  function run(){
    setBusy(true);
    const body:any={sort_by:filters.sortBy,sort_desc:filters.sortDesc,limit:25};
    if(filters.minPctChange!=="") body.min_pct_change=parseFloat(filters.minPctChange);
    if(filters.maxPctChange!=="") body.max_pct_change=parseFloat(filters.maxPctChange);
    if(filters.minRsi!=="") body.min_rsi=parseFloat(filters.minRsi);
    if(filters.maxRsi!=="") body.max_rsi=parseFloat(filters.maxRsi);
    if(filters.trend) body.trend=filters.trend;
    fetch(`${API}/api/screener-classic`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})
      .then(r=>r.json()).then(setResult).finally(()=>setBusy(false));
  }

  return <main>
    <header><p>Real technicals, no fake fundamentals</p><h1>Stock Screener</h1></header>
    <section className="panel screener-form">
      <div className="screener-filters">
        <label>Daily change % ≥ <input type="number" value={filters.minPctChange} onChange={e=>setFilters({...filters,minPctChange:e.target.value})} placeholder="any"/></label>
        <label>Daily change % ≤ <input type="number" value={filters.maxPctChange} onChange={e=>setFilters({...filters,maxPctChange:e.target.value})} placeholder="any"/></label>
        <label>RSI ≥ <input type="number" value={filters.minRsi} onChange={e=>setFilters({...filters,minRsi:e.target.value})} placeholder="any"/></label>
        <label>RSI ≤ <input type="number" value={filters.maxRsi} onChange={e=>setFilters({...filters,maxRsi:e.target.value})} placeholder="any"/></label>
        <label>Trend <select value={filters.trend} onChange={e=>setFilters({...filters,trend:e.target.value})}>
          <option value="">Any</option><option value="uptrend">Uptrend</option><option value="downtrend">Downtrend</option><option value="mixed">Mixed</option>
        </select></label>
        <label>Sort by <select value={filters.sortBy} onChange={e=>setFilters({...filters,sortBy:e.target.value})}>
          <option value="pct_change">Daily change</option><option value="rsi_14">RSI</option><option value="volatility_pct">Volatility</option><option value="price">Price</option>
        </select></label>
      </div>
      <button onClick={run} disabled={busy}>{busy?"Scanning…":"Scan Market"}</button>
    </section>
    {result&&<section className="panel screener-results">
      <p className="screener-summary">Scanned {result.scanned} of {result.universe_size} · {result.matched} matched{result.failed?.length>0&&` · ${result.failed.length} unavailable`}</p>
      <table>
        <thead><tr><th>Ticker</th><th>Price</th><th>Change %</th><th>RSI</th><th>Volatility %</th><th>Trend</th><th>Data</th></tr></thead>
        <tbody>{result.results?.map((r:any)=>
          <tr key={r.ticker} className="screener-row" onClick={()=>navigate(`/stock/${r.ticker}`)}>
            <td><strong>{r.ticker}</strong></td><td>{r.price}</td>
            <td className={r.pct_change>=0?"pos":"neg"}>{r.pct_change.toFixed(2)}</td>
            <td>{r.rsi_14??"—"}</td><td>{r.volatility_pct??"—"}</td><td>{r.trend??"—"}</td>
            <td><span className={`freshness ${(r.data_status||"").toLowerCase()}`}>{r.data_status}</span></td>
          </tr>)}
        </tbody>
      </table>
      {result.results?.length===0&&<p className="empty">No matches — widen your filters.</p>}
    </section>}
  </main>;
}