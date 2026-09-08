import {FormEvent,useEffect,useState} from "react";
import {getJSON,Num,MetaBadge} from "../lib/api";
type Signals={adx_14:number|null;rsi_14:number|null;price_vs_sma30:string|null;di_signal:string|null;annualized_vol_30d:number|null;vol_percentile_1y:number|null};
type RB={method:string;regime:string;label:string;confidence:number;signals:Signals;reasoning:string[]};
type HMM={method:string;regime:string;states:{state:number;days:number;mean_return:number;vol:number;label:string}[];transition_matrix:number[][];note:string}|null;
type Report={ticker:string;status:string;message?:string;rule_based:RB|null;hmm:HMM;summary?:string;disclaimer?:string;data_meta?:any};
const EXAMPLES=["AAPL","MSFT","NVDA","^GSPC","BTC-USD"];
export default function Analytics(){
  const [ticker,setTicker]=useState("AAPL"),[data,setData]=useState<Report|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  async function load(t:string){
    setBusy(true);setErr(null);
    try{setData(await getJSON<Report>(`/api/stocks/${encodeURIComponent(t)}/regime`))}
    catch(e:any){setErr(e.message);setData(null)}
    finally{setBusy(false)}
  }
  useEffect(()=>{load("AAPL")},[]);
  function submit(e:FormEvent){e.preventDefault();if(ticker.trim())load(ticker.trim())}
  const rb=data?.rule_based??null,sig=rb?.signals??null;
  return <section>
    <header className="page-head"><div><p>Regime analytics</p><h1>Market Regime</h1></div></header>
    <form onSubmit={submit} className="row-form">
      <label>Ticker <input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} aria-label="Ticker"/></label>
      <button disabled={busy}>{busy?"Analyzing…":"Detect regime"}</button>
      <div className="chips">{EXAMPLES.map(t=><button type="button" key={t} className="chip as-btn" onClick={()=>{setTicker(t);load(t)}}>{t}</button>)}</div>
    </form>
    {err&&<p className="error-text">{err}</p>}
    {data?.status==="insufficient_data"&&<div className="warn-banner">{data.message}</div>}
    {rb&&data&&<>
      <div className="card-row">
        <div className="card"><div className="k">Current regime</div><div className={`v ${rb.regime==="trending_up"?"pos":rb.regime==="trending_down"?"neg":""}`}>{rb.label}</div><div className="s">confidence {(rb.confidence*100).toFixed(0)}% · method {rb.method}</div></div>
        <div className="card"><div className="k">Trend strength (ADX 14)</div><div className="v"><Num v={sig?.adx_14} digits={1}/></div><div className="s">{sig?.price_vs_sma30||"—"} 30d mean · {sig?.di_signal||"—"} DI</div></div>
        <div className="card"><div className="k">Volatility regime</div><div className="v"><Num v={sig?.vol_percentile_1y} digits={0}/>th pct</div><div className="s">30d annualized vol <Num v={sig?.annualized_vol_30d} digits={1}/>%</div></div>
        <div className="card"><div className="k">RSI 14</div><div className="v"><Num v={sig?.rsi_14} digits={1}/></div><div className="s">momentum gauge — 30 oversold / 70 overbought</div></div>
        <div className="card"><div className="k">HMM regime</div><div className="v">{data.hmm?data.hmm.regime:"not available"}</div><div className="s">{data.hmm?"gaussian HMM over daily returns":"install hmmlearn for the statistical model"}</div></div>
        <div className="card"><div className="k">Data freshness</div><div className="v">—</div><div className="s"><MetaBadge meta={data.data_meta}/></div></div>
      </div>
      <div className="grid-2">
        <section className="panel">
          <h2>Why this classification (rule-based, explainable)</h2>
          <ul className="plain-list">{rb.reasoning.map((r,i)=><li key={i}>{r}</li>)}</ul>
          <small>{data.disclaimer}</small>
        </section>
        <section className="panel">
          <h2>Hidden Markov model {data.hmm?"":"(optional)"}</h2>
          {data.hmm?<table>
            <thead><tr><th>State</th><th>Days</th><th>Mean return</th><th>Vol</th></tr></thead>
            <tbody>{data.hmm.states.map(s=><tr key={s.state}>
              <td><b>{s.label}</b>{s.state===data.hmm!.states.findIndex(x=>x.label===data.hmm!.regime)?<span className="chip">current</span>:null}</td>
              <td>{s.days}</td><td>{(s.mean_return*100).toFixed(3)}%</td><td>{(s.vol*100).toFixed(2)}%</td>
            </tr>)}</tbody>
          </table>:<p className="dim">hmmlearn isn't installed — the deterministic rule-based classifier above is the always-available baseline. <code>pip install hmmlearn</code> to enable.</p>}
        </section>
      </div>
    </>}
  </section>;
}
