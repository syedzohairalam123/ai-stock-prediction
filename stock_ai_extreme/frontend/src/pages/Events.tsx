import {FormEvent,useEffect,useState} from "react";
import {getJSON,postJSON,Pct,MetaBadge} from "../lib/api";
type Study={event_label:string;sample_size:number;avg_move_1d_pct:number;avg_move_5d_pct:number;avg_move_20d_pct:number;positive_1d_rate:number;worst_5d_pct:number;best_5d_pct:number;dates_used:string[];reliability:string};
type Stress={score:number|null;level:string;headline_count:number;geopolitical_share:number;average_news_sentiment?:number;top_keywords:string[];note:string};
type Report={ticker:string;event_study:Study;stress_score:Stress|null;data_meta?:any;disclaimer:string};
type StressReport=Stress&{affected_assets:any;data_meta:any};
const EXAMPLES=[["2008-09-15","Lehman collapse"],["2020-03-09","COVID oil crash"],["2022-02-24","Ukraine invasion"],["2023-03-10","SVB failure"]] as const;
export default function Events(){
  const [ticker,setTicker]=useState("AAPL"),[dates,setDates]=useState("2020-03-09, 2022-02-24"),[label,setLabel]=useState("Crisis events"),[rep,setRep]=useState<Report|null>(null),[stress,setStress]=useState<StressReport|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  useEffect(()=>{
    getJSON<StressReport>(`/api/market-stress?ticker=${encodeURIComponent(ticker)}`).then(setStress).catch(()=>setStress(null));
  },[ticker]);
  async function run(e:FormEvent){
    e.preventDefault();setBusy(true);setErr(null);
    try{
      const list=dates.split(",").map(s=>s.trim()).filter(Boolean);
      setRep(await postJSON<Report>(`/api/stocks/${encodeURIComponent(ticker)}/events/study`,{event_dates:list,label}));
    }catch(ex:any){setErr(ex.message);setRep(null)}
    finally{setBusy(false)}
  }
  const level=stress?.level||"unavailable";
  return <section>
    <header className="page-head"><div><p>Event impact analytics</p><h1>Events & Stress</h1></div></header>
    <div className="card-row">
      <div className={`card stress ${level}`}><div className="k">Market stress gauge</div>
        <div className={`v ${level==="low"?"pos":level==="severe"||level==="high"?"neg":""}`}>{stress?.score!==null&&stress?.score!==undefined?stress.score.toFixed(1):"—"}</div>
        <div className="s">{level} · {stress?.headline_count??0} headlines · {stress?.note||"no headlines available"}</div>
        {stress?.top_keywords?.length?<div className="chips">{stress.top_keywords.map(k=><span key={k} className="chip">{k}</span>)}</div>:null}
      </div>
      {stress?.affected_assets?.often_rises_on_stress&&<div className="card"><div className="k">Historically stress-sensitive</div>
        <div className="s">Rises: {stress.affected_assets.often_rises_on_stress.join(", ")||"—"}</div>
        <div className="s">Falls: {(stress.affected_assets.often_falls_on_stress||[]).join(", ")||"—"}</div>
        <div className="s">{stress.affected_assets.note}</div>
      </div>}
    </div>
    <section className="panel">
      <h2>Historical event study</h2>
      <p className="dim">What did this asset ACTUALLY do after similar past dates — measured on real price windows, never a prediction of future political outcomes.</p>
      <form onSubmit={run} className="row-form">
        <label>Ticker <input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} aria-label="Ticker"/></label>
        <label>Event dates (comma-sep) <input value={dates} onChange={e=>setDates(e.target.value)} size={32} aria-label="Event dates"/></label>
        <label>Label <input value={label} onChange={e=>setLabel(e.target.value)} aria-label="Event label"/></label>
        <button disabled={busy}>{busy?"Studying…":"Run study"}</button>
      </form>
      <div className="chips">{EXAMPLES.map(([d,n])=><button key={d} className="chip as-btn" onClick={()=>setDates(cur=>cur?`${cur}, ${d}`:d)}>+ {n} ({d})</button>)}</div>
      {err&&<p className="error-text">{err}</p>}
      {rep&&<><div className="card-row">
          <div className="card"><div className="k">Sample size</div><div className="v">{rep.event_study.sample_size}</div><div className="s">{rep.event_study.reliability} — {rep.event_study.sample_size<5?"treat as anecdote":"interpret with context"}</div></div>
          <div className="card"><div className="k">Avg move +1d</div><div className="v"><Pct v={rep.event_study.avg_move_1d_pct}/></div><div className="s">positive next-day rate {(rep.event_study.positive_1d_rate*100).toFixed(0)}%</div></div>
          <div className="card"><div className="k">Avg move +5d</div><div className="v"><Pct v={rep.event_study.avg_move_5d_pct}/></div><div className="s">worst {rep.event_study.worst_5d_pct}% · best {rep.event_study.best_5d_pct}%</div></div>
          <div className="card"><div className="k">Avg move +20d</div><div className="v"><Pct v={rep.event_study.avg_move_20d_pct}/></div><div className="s">dates used: {rep.event_study.dates_used.join(", ")||"—"}</div></div>
        </div>
        <div className="meta-line">Study <MetaBadge meta={rep.data_meta}/> · <small>{rep.disclaimer}</small></div>
      </>}
    </section>
  </section>;
}
