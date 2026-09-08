import {FormEvent,useEffect,useState} from "react";
import {postJSON,Pct,Num,MetaBadge} from "../lib/api";
type Row={ticker:string;last_close:number|null;momentum_1m_pct:number|null;momentum_3m_pct:number|null;trend_score:number|null;rsi_14:number|null;annualized_volatility_pct:number|null;composite_score:number;rank:number;data_source:string;data_status:string};
type Report={scanned:number;ranked:Row[];unavailable:Record<string,string>;methodology:{composite:string;note:string}};
const DEFAULTS="AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,JPM,XOM,GLD,BTC-USD";
export default function Screener(){
  const [tickers,setTickers]=useState(DEFAULTS),[rep,setRep]=useState<Report|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  useEffect(()=>{run()},[]); // eslint-disable-line react-hooks/exhaustive-deps
  async function run(){
    setBusy(true);setErr(null);
    try{
      const list=tickers.split(",").map(s=>s.trim().toUpperCase()).filter(Boolean);
      setRep(await postJSON<Report>("/api/screener",{tickers:list,lookback_days:365}));
    }catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }
  function submit(e:FormEvent){e.preventDefault();run()}
  const maxComp=Math.max(...(rep?.ranked.map(r=>r.composite_score)||[1]),1);
  return <section>
    <header className="page-head"><div><p>Analytical ranking engine</p><h1>Screener</h1></div></header>
    <section className="panel">
      <form onSubmit={submit} className="row-form">
        <label>Tickers (comma-sep) <input value={tickers} onChange={e=>setTickers(e.target.value)} size={40} aria-label="Tickers"/></label>
        <button disabled={busy}>{busy?"Scanning…":"Run scan"}</button>
      </form>
      {err&&<p className="error-text">{err}</p>}
      {rep&&<><p className="dim">{rep.scanned} scanned · {rep.ranked.length} ranked{Object.keys(rep.unavailable).length?` · ${Object.keys(rep.unavailable).length} unavailable`:""}</p>
        <table>
          <thead><tr><th>#</th><th>Ticker</th><th>Composite</th><th>1m mom</th><th>3m mom</th><th>Trend</th><th>RSI</th><th>Vol (ann.)</th><th>Last</th><th>Data</th></tr></thead>
          <tbody>{rep.ranked.map(r=><tr key={r.ticker}>
            <td><b>{r.rank}</b></td><td><b>{r.ticker}</b></td>
            <td><div className="bar-cell"><span className="bar" style={{width:`${(r.composite_score/maxComp)*100}%`}}/><span>{r.composite_score.toFixed(1)}</span></div></td>
            <td><Pct v={r.momentum_1m_pct}/></td><td><Pct v={r.momentum_3m_pct}/></td>
            <td><Pct v={r.trend_score}/></td><td><Num v={r.rsi_14} digits={1}/></td>
            <td><Num v={r.annualized_volatility_pct} digits={1}/>%</td>
            <td><Num v={r.last_close}/></td>
            <td><MetaBadge meta={{status:r.data_status,source:r.data_source}}/></td>
          </tr>)}</tbody>
        </table>
        {Object.keys(rep.unavailable).length>0&&<div className="warn-banner">
          Unavailable: {Object.entries(rep.unavailable).map(([t,why])=>`${t} (${why})`).join(" · ")}
        </div>}
        <small>{rep.methodology.composite}. {rep.methodology.note}</small>
      </>}
    </section>
  </section>;
}
