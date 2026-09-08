import {FormEvent,useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
type HoldingT={id:number;ticker:string;shares:number;avg_cost:number;note:string|null;current_price:number|null;cost_basis:number;market_value:number|null;pnl:number|null;pnl_pct:number|null};
type PortfolioT={holdings:HoldingT[];summary:{positions:number;priced_positions:number;total_cost_basis:number;total_market_value:number;total_pnl:number;total_pnl_pct:number|null};disclaimer?:string};
function Money({v,cls}:{v:number|null;cls?:string}){return <span className={cls}>{v===null?"—":`$${v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`}</span>}
export default function PortfolioPanel(){
  const [data,setData]=useState<PortfolioT|null>(null),[ticker,setTicker]=useState(""),[shares,setShares]=useState(""),[cost,setCost]=useState(""),
        [error,setError]=useState<string|null>(null),[busy,setBusy]=useState(false);
  function load(){
    fetch(`${API}/api/portfolio`).then(r=>r.json()).then(d=>{setData(d);setError(null)}).catch(()=>setError("Could not load portfolio."));
  }
  useEffect(load,[]);
  function add(e:FormEvent){
    e.preventDefault();
    const sh=parseFloat(shares),c=parseFloat(cost);
    if(!ticker.trim()||isNaN(sh)||isNaN(c)||sh<=0||c<0)return;
    setBusy(true);
    fetch(`${API}/api/portfolio`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ticker:ticker.trim(),shares:sh,avg_cost:c})})
      .then(r=>r.ok?r.json():Promise.reject(r.status))
      .then(()=>{setTicker("");setShares("");setCost("");load()})
      .catch(()=>setError("Could not add holding."))
      .finally(()=>setBusy(false));
  }
  function remove(id:number){
    fetch(`${API}/api/portfolio/${id}`,{method:"DELETE"}).then(r=>r.ok?load():setError("Could not delete holding."));
  }
  const s=data?.summary;
  return <section className="panel portfolio">
    <div className="news-head">
      <h2>Portfolio Tracker</h2>
      {s&&<div className="portfolio-summary">
        <span className={s.total_pnl>=0?"pnl-pos":"pnl-neg"}>P&L: {s.total_pnl>=0?"+":""}{s.total_pnl===0?"$0.00":`$${s.total_pnl.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`} ({s.total_pnl_pct===null?"—":`${s.total_pnl_pct>=0?"+":""}${s.total_pnl_pct.toFixed(2)}%`})</span>
        <span className="news-counts">Value ${(s.total_market_value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})} · Cost ${(s.total_cost_basis||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
      </div>}
    </div>
    <form onSubmit={add} className="watchlist-add portfolio-add">
      <input aria-label="Ticker" placeholder="Ticker (AAPL)" value={ticker} onChange={e=>setTicker(e.target.value)}/>
      <input aria-label="Shares" placeholder="Shares" type="number" step="any" min="0" value={shares} onChange={e=>setShares(e.target.value)}/>
      <input aria-label="Avg cost" placeholder="Avg cost" type="number" step="any" min="0" value={cost} onChange={e=>setCost(e.target.value)}/>
      <button type="submit" disabled={busy}>Add</button>
    </form>
    {error&&<p className="watchlist-error">{error}</p>}
    {data&&data.holdings.length===0&&<p className="empty">No holdings yet — add your first position above.</p>}
    {data&&data.holdings.length>0&&<table className="cross-asset-table portfolio-table">
      <thead><tr><th>Ticker</th><th>Shares</th><th>Avg cost</th><th>Last price</th><th>Market value</th><th>P&L</th><th></th></tr></thead>
      <tbody>
        {data.holdings.map(h=>{
          const pnlCls=h.pnl===null?"":h.pnl>=0?"pos":"neg";
          return <tr key={h.id}>
            <td><b>{h.ticker}</b>{h.note&&<small className="watchlist-note"> {h.note}</small>}</td>
            <td>{h.shares}</td>
            <td><Money v={h.avg_cost}/></td>
            <td><Money v={h.current_price}/></td>
            <td><Money v={h.market_value}/></td>
            <td><span className={pnlCls}>{h.pnl===null?"—":`${h.pnl>=0?"+":""}$${h.pnl.toFixed(2)} (${h.pnl_pct===null?"—":`${h.pnl_pct>=0?"+":""}${h.pnl_pct.toFixed(2)}%`})`}</span></td>
            <td><button className="watchlist-remove" aria-label="Remove holding" onClick={()=>remove(h.id)}>×</button></td>
          </tr>;
        })}
      </tbody>
    </table>}
    {s&&s.positions>s.priced_positions&&<small className="watchlist-note">{s.positions-s.priced_positions} holding(s) without a live price (not included in totals).</small>}
    {data?.disclaimer&&<small>{data.disclaimer}</small>}
  </section>;
}