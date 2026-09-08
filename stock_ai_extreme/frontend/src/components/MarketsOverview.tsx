import {useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
type Row={symbol:string;name:string;price:number|null;change_percent:number|null;source:string;status:string;error?:string};
const TABS=[["crypto","Crypto"],["commodities","Commodities"],["forex","Forex"]] as const;
export default function MarketsOverview(){
  const [tab,setTab]=useState<string>("crypto"),[rows,setRows]=useState<Row[]>([]),[busy,setBusy]=useState(false);
  useEffect(()=>{
    setBusy(true);
    fetch(`${API}/api/markets/${tab}`).then(r=>r.json()).then(setRows).catch(()=>setRows([])).finally(()=>setBusy(false));
  },[tab]);
  return <section className="panel markets">
    <div className="markets-head">
      <h2>Markets</h2>
      <div className="markets-tabs">
        {TABS.map(([id,label])=><button key={id} className={tab===id?"active":""} onClick={()=>setTab(id)}>{label}</button>)}
      </div>
    </div>
    {busy&&<p className="empty">Loading…</p>}
    <div className="markets-grid">
      {rows.map(r=><div key={r.symbol} className="markets-cell">
        <div className="markets-cell-top"><strong>{r.name}</strong><span className={`freshness ${r.status.toLowerCase()}`}>{r.status}</span></div>
        <div className="markets-cell-symbol">{r.symbol}</div>
        {r.price!==null?<div className="markets-cell-price">
          {r.price.toLocaleString(undefined,{maximumFractionDigits:4})}
          {r.change_percent!==null&&<span className={r.change_percent>=0?"pos":"neg"}> {r.change_percent>=0?"▲":"▼"} {Math.abs(r.change_percent).toFixed(2)}%</span>}
        </div>:<div className="markets-cell-price unavailable">Unavailable</div>}
      </div>)}
    </div>
  </section>;
}
