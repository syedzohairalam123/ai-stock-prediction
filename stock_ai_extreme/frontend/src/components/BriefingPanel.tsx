import {useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
export default function BriefingPanel({ticker}:{ticker:string}){
  const [result,setResult]=useState<any>(null),[busy,setBusy]=useState(false);
  function generate(){
    setBusy(true);setResult(null);
    fetch(`${API}/api/stocks/${ticker}/briefing`,{method:"POST"}).then(r=>r.json()).then(setResult).finally(()=>setBusy(false));
  }
  return <section className="panel briefing">
    <h2>AI Market Briefing</h2>
    <button onClick={generate} disabled={busy}>{busy?"Generating…":`Generate briefing for ${ticker}`}</button>
    {result?.status==="OK"&&<p className="briefing-text">{result.text}</p>}
    {result?.status==="UNAVAILABLE"&&<p className="empty">AI briefing needs an <code>ANTHROPIC_API_KEY</code> configured on the backend (see <code>backend/.env.example</code>) — the rest of the app works fine without it.</p>}
    {result?.status==="ERROR"&&<p className="backtest-error">Briefing failed: {result.reason}</p>}
    {result?.structured_data&&<details className="briefing-data"><summary>Data the briefing was grounded in</summary>
      <pre>{JSON.stringify(result.structured_data,null,2)}</pre>
    </details>}
  </section>;
}
