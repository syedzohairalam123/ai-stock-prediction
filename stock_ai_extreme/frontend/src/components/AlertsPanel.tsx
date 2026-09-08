import {FormEvent,useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
type AlertT={id:number;ticker:string;alert_type:string;threshold:number;active:boolean;triggered_at:string|null;triggered_value:number|null};
const TYPE_LABELS:Record<string,string>={price_above:"Price above",price_below:"Price below",pct_change:"Daily change beyond ±",rsi_overbought:"RSI above",rsi_oversold:"RSI below"};
export default function AlertsPanel({ticker}:{ticker:string}){
  const [alerts,setAlerts]=useState<AlertT[]>([]),[type,setType]=useState("price_above"),[threshold,setThreshold]=useState(""),
        [checking,setChecking]=useState(false),[justTriggered,setJustTriggered]=useState<any[]>([]);
  function load(){fetch(`${API}/api/alerts?ticker=${ticker}`).then(r=>r.json()).then(setAlerts).catch(()=>{})}
  useEffect(load,[ticker]);
  function add(e:FormEvent){
    e.preventDefault(); const t=parseFloat(threshold); if(isNaN(t)) return;
    fetch(`${API}/api/alerts`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ticker,alert_type:type,threshold:t})})
      .then(()=>{setThreshold("");load()});
  }
  function remove(id:number){fetch(`${API}/api/alerts/${id}`,{method:"DELETE"}).then(load)}
  function checkNow(){
    setChecking(true);setJustTriggered([]);
    fetch(`${API}/api/stocks/${ticker}/alerts/check`,{method:"POST"}).then(r=>r.json())
      .then(d=>{setJustTriggered(d.triggered||[]);load()}).finally(()=>setChecking(false));
  }
  return <section className="panel alerts">
    <h2>Smart Alerts — {ticker}</h2>
    <form onSubmit={add} className="alerts-form">
      <select value={type} onChange={e=>setType(e.target.value)}>
        {Object.entries(TYPE_LABELS).map(([k,label])=><option key={k} value={k}>{label}</option>)}
      </select>
      <input type="number" step="any" value={threshold} onChange={e=>setThreshold(e.target.value)} placeholder="Threshold" aria-label="Threshold"/>
      <button>Add Alert</button>
      <button type="button" onClick={checkNow} disabled={checking}>{checking?"Checking…":"Check Now"}</button>
    </form>
    {justTriggered.length>0&&<div className="alerts-triggered">🔔 Triggered: {justTriggered.map(t=>`${TYPE_LABELS[t.alert_type]} ${t.threshold} (now ${t.current_value})`).join(" · ")}</div>}
    {alerts.length===0&&<p className="empty">No alerts set for {ticker} yet.</p>}
    <ul className="alerts-list">
      {alerts.map(a=><li key={a.id} className={a.active?"":"resolved"}>
        <span>{TYPE_LABELS[a.alert_type]} {a.threshold}</span>
        {!a.active&&<span className="alerts-resolved-tag">triggered at {a.triggered_value}</span>}
        <button className="watchlist-remove" aria-label="Delete alert" onClick={()=>remove(a.id)}>×</button>
      </li>)}
    </ul>
  </section>;
}
