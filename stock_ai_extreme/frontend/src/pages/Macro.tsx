import {useEffect,useState} from "react";
import {getJSON,Pct,Num,MetaBadge} from "../lib/api";
type Indicator={key:string;label:string;unit:string;latest_value:number|null;previous_value:number|null;change:number|null;source:string;fred_series:string|null;proxy_symbol:string|null};
type MacroReport={source:string;status:string;indicators:Indicator[];errors:Record<string,string>;
  yield_curve:{status:string;signal:string|null;message:string}|null;
  regime:{growth:string;inflation:string;policy:string;tone:string;explanation:string}|null;
  calendar:{event:string;typical_day:string;indicator:string;latest_value:number|null;previous_value:number|null;expected:number|null;actual:number|null;surprise:number|null}[];
  disclaimer:string};
const SOURCES=[["yfinance","Market proxies (no key)"],["fred","FRED official (needs key)"]] as const;
export default function Macro(){
  const [source,setSource]=useState<string>("yfinance"),[data,setData]=useState<MacroReport|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  useEffect(()=>{
    setBusy(true);setErr(null);
    getJSON<MacroReport>(`/api/macro?source=${source}`).then(setData).catch(e=>setErr(e.message)).finally(()=>setBusy(false));
  },[source]);
  const tone=data?.regime?.tone;
  return <section>
    <header className="page-head">
      <div><p>Macro intelligence</p><h1>Macro Dashboard</h1></div>
      <label className="source-select">Source <select value={source} onChange={e=>setSource(e.target.value)}>
        {SOURCES.map(([v,l])=><option key={v} value={v}>{l}</option>)}
      </select></label>
    </header>
    {busy&&<p className="empty">Loading macro indicators…</p>}
    {err&&<p className="error-text">{err}</p>}
    {data&&<>{data.status==="UNAVAILABLE"&&<div className="warn-banner">{data.status}{data.errors&&Object.values(data.errors)[0]?`: ${Object.values(data.errors)[0]}`:""} — try the other source.</div>}
      {data.regime&&<div className="card-row">
        <div className="card"><div className="k">Macro tone</div><div className={`v ${tone==="risk-on"?"pos":tone==="risk-off"?"neg":""}`}>{tone||"—"}</div><div className="s">growth {data.regime.growth} · inflation {data.regime.inflation} · policy {data.regime.policy}</div></div>
        <div className={`card yc ${data.yield_curve?.status||""}`}><div className="k">Yield curve</div><div className="v">{data.yield_curve?.status||"—"}</div><div className="s">{data.yield_curve?.message}</div></div>
        <div className="card"><div className="k">Source</div><div className="v">{data.source}</div><div className="s">{data.indicators.length} indicator(s) loaded{Object.keys(data.errors||{}).length?` · ${Object.keys(data.errors).length} failed`:''}</div></div>
      </div>}
      {data.indicators.length>0&&<section className="panel">
        <h2>Indicators <MetaBadge meta={{status:data.status,source:data.source}}/></h2>
        <table>
          <thead><tr><th>Indicator</th><th>Latest</th><th>Prev</th><th>Change</th><th>Unit</th><th>Source series</th></tr></thead>
          <tbody>{data.indicators.map(r=><tr key={r.key}>
            <td>{r.label}</td><td><Num v={r.latest_value}/></td><td><Num v={r.previous_value}/></td>
            <td><Pct v={r.change}/></td><td>{r.unit}</td>
            <td className="dim">{r.fred_series||r.proxy_symbol||"—"}</td>
          </tr>)}</tbody>
        </table>
      </section>}
      {Object.keys(data.errors||{}).length>0&&<section className="panel">
        <h2>Indicator failures (honest degradation)</h2>
        <ul className="plain-list">{Object.entries(data.errors).map(([k,v])=><li key={k}><b>{k}</b>: {v}</li>)}</ul>
      </section>}
      {data.calendar.length>0&&<section className="panel">
        <h2>Economic calendar reference</h2>
        <table>
          <thead><tr><th>Event</th><th>Typical timing</th><th>Latest actual</th><th>Expected</th></tr></thead>
          <tbody>{data.calendar.map(c=><tr key={c.indicator}>
            <td>{c.event}</td><td className="dim">{c.typical_day}</td><td><Num v={c.actual}/></td>
            <td>{c.expected===null?<span className="dim">not provided by source</span>:<Num v={c.expected}/>}</td>
          </tr>)}</tbody>
        </table>
        <small>Expected/surprise columns only fill from an official consensus feed; the API never invents them.</small>
      </section>}
      <small>{data.disclaimer}</small>
    </>}
  </section>;
}
