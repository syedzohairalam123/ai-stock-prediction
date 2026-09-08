import {FormEvent,useState} from "react";
import Plot from "react-plotly.js";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
const iso=(d:Date)=>d.toISOString().slice(0,10);
type Report={benchmark:string;correlation_matrix:Record<string,Record<string,number>>;beta:Record<string,number>;
  relative_strength_latest:Record<string,number>;asset_stats:Record<string,{total_return_pct:number;annualized_volatility_pct:number;avg_volume:number|null}>;
  unavailable?:Record<string,string>};
export default function CrossAssetPanel({ticker}:{ticker:string}){
  const [input,setInput]=useState(`${ticker}, MSFT, GOOGL, SPY`),[benchmark,setBenchmark]=useState("SPY"),
        [report,setReport]=useState<Report|null>(null),[busy,setBusy]=useState(false),[err,setErr]=useState<string|null>(null);
  function run(e?:FormEvent){
    e?.preventDefault();
    const tickers=input.split(",").map(t=>t.trim().toUpperCase()).filter(Boolean);
    if(tickers.length<2){setErr("Enter at least 2 tickers.");return}
    setBusy(true);setErr(null);setReport(null);
    const end=iso(new Date()),start=iso(new Date(Date.now()-400*86400000));
    fetch(`${API}/api/cross-asset/report`,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({tickers,start,end,benchmark})})
      .then(r=>{if(!r.ok) return r.json().then(b=>{throw new Error(b.detail||"Could not build report")}); return r.json()})
      .then(setReport).catch(e=>setErr(e.message)).finally(()=>setBusy(false));
  }
  const names=report?Object.keys(report.correlation_matrix):[];
  const z=names.map(row=>names.map(col=>report!.correlation_matrix[row][col]));
  const statsEntries=report?Object.entries(report.asset_stats):[];
  return <section className="panel cross-asset">
    <h2>Cross-Asset Intelligence</h2>
    <form onSubmit={run} className="cross-asset-form">
      <input value={input} onChange={e=>setInput(e.target.value)} placeholder="AAPL, MSFT, GOOGL, SPY" aria-label="Tickers to compare"/>
      <label>Benchmark <input className="benchmark-input" value={benchmark} onChange={e=>setBenchmark(e.target.value.toUpperCase())}/></label>
      <button disabled={busy}>{busy?"Analyzing…":"Compare"}</button>
    </form>
    {err&&<p className="backtest-error">{err}</p>}
    {report&&<>
      <div className="cross-asset-grid">
        <div className="heatmap-wrap">
          <Plot data={[{z,x:names,y:names,type:"heatmap",colorscale:[[0,"#fb7185"],[0.5,"#10172b"],[1,"#4ade80"]],zmin:-1,zmax:1,
            texttemplate:"%{z:.2f}",textfont:{size:10,color:"#e6edf7"}}] as any}
            layout={{title:"Return Correlation Matrix",paper_bgcolor:"#10172bbd",plot_bgcolor:"#10172bbd",font:{color:"#e6edf7",size:11},
              margin:{t:34,l:60,r:12,b:50}} as any} config={{responsive:true,displaylogo:false}} style={{width:"100%",height:340}}/>
        </div>
        <div className="market3d-wrap">
          <Plot data={[{type:"scatter3d",mode:"markers+text",
            x:statsEntries.map(([,s])=>s.total_return_pct),
            y:statsEntries.map(([,s])=>s.annualized_volatility_pct),
            z:statsEntries.map(([,s])=>s.avg_volume??0),
            text:statsEntries.map(([t])=>t),textposition:"top center",
            marker:{size:7,color:statsEntries.map(([,s])=>s.total_return_pct),colorscale:[[0,"#fb7185"],[0.5,"#facc15"],[1,"#4ade80"]]}}] as any}
            layout={{title:"3D Market Map — Return / Volatility / Volume",paper_bgcolor:"#10172bbd",font:{color:"#e6edf7",size:10},
              margin:{t:34,l:0,r:0,b:0},
              scene:{xaxis:{title:"Return %",gridcolor:"#263458"},yaxis:{title:"Volatility %",gridcolor:"#263458"},zaxis:{title:"Avg Volume",gridcolor:"#263458"},
                bgcolor:"#10172bbd"}} as any} config={{responsive:true,displaylogo:false}} style={{width:"100%",height:340}}/>
        </div>
      </div>
      <table className="cross-asset-table">
        <thead><tr><th>Ticker</th><th>Beta vs {report.benchmark}</th><th>Relative Strength</th><th>Return %</th><th>Volatility %</th></tr></thead>
        <tbody>{statsEntries.filter(([t])=>t!==report.benchmark).map(([t,s])=>
          <tr key={t}><td>{t}</td><td>{report.beta[t]??"—"}</td><td>{report.relative_strength_latest[t]??"—"}</td>
            <td className={s.total_return_pct>=0?"pos":"neg"}>{s.total_return_pct.toFixed(2)}</td><td>{s.annualized_volatility_pct.toFixed(2)}</td></tr>)}
        </tbody>
      </table>
      {report.unavailable&&<small className="watchlist-error">Unavailable: {Object.keys(report.unavailable).join(", ")}</small>}
    </>}
  </section>;
}
