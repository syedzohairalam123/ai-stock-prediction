import {useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
const iso=(d:Date)=>d.toISOString().slice(0,10);
type Result={total_return_pct:number;benchmark_return_pct:number;max_drawdown_pct:number;win_rate:number;
  num_trades:number;directional_accuracy:number;mae:number;rmse:number;test_days:number;model:string;disclaimer:string};
export default function BacktestPanel({ticker}:{ticker:string}){
  const [model,setModel]=useState("ridge"),[testDays,setTestDays]=useState(60),[result,setResult]=useState<Result|null>(null),
        [busy,setBusy]=useState(false),[err,setErr]=useState<string|null>(null);
  function run(){
    setBusy(true);setErr(null);setResult(null);
    const end=iso(new Date()),start=iso(new Date(Date.now()-1000*86400000));
    fetch(`${API}/api/stocks/${ticker}/backtest`,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({start,end,model,test_days:testDays,refit_every:5})})
      .then(r=>{if(!r.ok) return r.json().then(b=>{throw new Error(b.detail||"Backtest failed")}); return r.json()})
      .then(setResult).catch(e=>setErr(e.message)).finally(()=>setBusy(false));
  }
  return <section className="panel backtest">
    <h2>Walk-Forward Backtest</h2>
    <div className="backtest-controls">
      <label>Model <select value={model} onChange={e=>setModel(e.target.value)}>
        <option value="ridge">Ridge</option><option value="rf">Random Forest</option>
      </select></label>
      <label>Test window <select value={testDays} onChange={e=>setTestDays(Number(e.target.value))}>
        <option value={30}>30 days</option><option value={60}>60 days</option><option value={90}>90 days</option>
      </select></label>
      <button onClick={run} disabled={busy}>{busy?"Running…":`Backtest ${ticker}`}</button>
    </div>
    {err&&<p className="backtest-error">{err}</p>}
    {result&&<>
      <div className="backtest-grid">
        <div className="metric"><span>Strategy return</span><strong className={result.total_return_pct>=0?"pos":"neg"}>{result.total_return_pct.toFixed(2)}%</strong></div>
        <div className="metric"><span>Buy &amp; hold</span><strong>{result.benchmark_return_pct.toFixed(2)}%</strong></div>
        <div className="metric"><span>Max drawdown</span><strong>{result.max_drawdown_pct.toFixed(2)}%</strong></div>
        <div className="metric"><span>Win rate</span><strong>{(result.win_rate*100).toFixed(1)}%</strong></div>
        <div className="metric"><span>Directional accuracy</span><strong>{(result.directional_accuracy*100).toFixed(1)}%</strong></div>
        <div className="metric"><span>Trades / MAE</span><strong>{result.num_trades} / {result.mae}</strong></div>
      </div>
      <small>{result.disclaimer}</small>
    </>}
  </section>;
}
