import {useEffect,useState} from "react";
import {useNavigate} from "react-router-dom";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
const TYPE_LABELS:Record<string,string>={price_above:"Price above",price_below:"Price below",pct_change:"Daily change beyond ±",rsi_overbought:"RSI above",rsi_oversold:"RSI below"};

export default function AlertsOverviewPage(){
  const navigate=useNavigate();
  const [alerts,setAlerts]=useState<any[]>([]);
  function load(){fetch(`${API}/api/alerts`).then(r=>r.json()).then(setAlerts).catch(()=>{})}
  useEffect(load,[]);
  function remove(id:number){fetch(`${API}/api/alerts/${id}`,{method:"DELETE"}).then(load)}
  const active=alerts.filter(a=>a.active), resolved=alerts.filter(a=>!a.active);
  return <main>
    <header><p>Everything you're watching for, across every ticker</p><h1>Alerts</h1></header>
    <section className="panel">
      <h2>Active ({active.length})</h2>
      {active.length===0&&<p className="empty">No active alerts. Open a stock's page to add one.</p>}
      <ul className="alerts-list">
        {active.map(a=><li key={a.id}>
          <button className="watchlist-ticker" onClick={()=>navigate(`/stock/${a.ticker}`)}>{a.ticker}</button>
          <span>{TYPE_LABELS[a.alert_type]||a.alert_type} {a.threshold}</span>
          <button className="watchlist-remove" aria-label="Delete alert" onClick={()=>remove(a.id)}>×</button>
        </li>)}
      </ul>
    </section>
    {resolved.length>0&&<section className="panel">
      <h2>Recently Triggered ({resolved.length})</h2>
      <ul className="alerts-list">
        {resolved.map(a=><li key={a.id} className="resolved">
          <button className="watchlist-ticker" onClick={()=>navigate(`/stock/${a.ticker}`)}>{a.ticker}</button>
          <span>{TYPE_LABELS[a.alert_type]||a.alert_type} {a.threshold}</span>
          <span className="alerts-resolved-tag">triggered at {a.triggered_value} on {a.triggered_at?.slice(0,10)}</span>
          <button className="watchlist-remove" aria-label="Delete alert" onClick={()=>remove(a.id)}>×</button>
        </li>)}
      </ul>
    </section>}
  </main>;
}