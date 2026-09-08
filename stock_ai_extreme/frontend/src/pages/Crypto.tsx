import {useEffect,useState} from "react";
import {getJSON,postJSON,Num,Pct,Money} from "../lib/api";
type Coin={symbol:string;name:string;price:number|null;change_percent_24h:number|null;change_percent_7d:number|null;change_percent_30d:number|null;market_cap:number|null;market_cap_rank:number|null;total_volume:number|null;circulating_supply:number|null;ath:number|null;ath_change_percent:number|null;source:string;error?:string};
type Report={source:string;status:string;reason?:string;summary?:{tracked:number;priced:number;total_market_cap:number|null;btc_dominance_pct:number|null;eth_dominance_pct:number|null;top_gainer_7d:string|null;worst_performer_7d:string|null};coins:Coin[];disclaimer?:string};
const SOURCES=[["coingecko","CoinGecko (no key)"],["yfinance","yfinance (same provider layer)"]] as const;
export default function Crypto(){
  const [source,setSource]=useState<string>("coingecko"),[rep,setRep]=useState<Report|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);setErr(null);
    try{setRep(await postJSON<Report>("/api/crypto/overview",{source}))}
    catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }
  useEffect(()=>{load()},[source]); // eslint-disable-line react-hooks/exhaustive-deps
  const s=rep?.summary;
  return <section>
    <header className="page-head">
      <div><p>Crypto pro dashboard</p><h1>Crypto</h1></div>
      <label className="source-select">Source <select value={source} onChange={e=>setSource(e.target.value)}>
        {SOURCES.map(([v,l])=><option key={v} value={v}>{l}</option>)}
      </select></label>
    </header>
    {busy&&<p className="empty">Loading crypto market…</p>}
    {err&&<p className="error-text">{err}</p>}
    {rep&&<>{rep.status==="UNAVAILABLE"&&<div className="warn-banner">{rep.source} source unavailable: {rep.reason||"unknown reason"}</div>}
      {s&&<div className="card-row">
        <div className="card"><div className="k">Coins priced</div><div className="v">{s.priced}/{s.tracked}</div><div className="s">via {rep.source}</div></div>
        <div className="card"><div className="k">Total market cap</div><div className="v"><Money v={s.total_market_cap}/></div><div className="s">BTC dom <Num v={s.btc_dominance_pct} digits={1}/>% · ETH dom <Num v={s.eth_dominance_pct} digits={1}/>%</div></div>
        <div className="card"><div className="k">7d best / worst</div><div className="v">{s.top_gainer_7d||"—"} / {s.worst_performer_7d||"—"}</div><div className="s">of {s.tracked} tracked coins</div></div>
      </div>}
      {rep.coins.length>0&&<section className="panel">
        <h2>Coins</h2>
        <table>
          <thead><tr><th>#</th><th>Coin</th><th>Price</th><th>24h</th><th>7d</th><th>30d</th><th>Market cap</th><th>Vol</th><th>vs ATH</th></tr></thead>
          <tbody>{rep.coins.map(c=><tr key={c.symbol}>
            <td>{c.market_cap_rank??"—"}</td><td><b>{c.name}</b> <span className="dim">{c.symbol}</span></td>
            <td><Num v={c.price}/></td>
            <td><Pct v={c.change_percent_24h}/></td><td><Pct v={c.change_percent_7d}/></td><td><Pct v={c.change_percent_30d}/></td>
            <td><Money v={c.market_cap}/></td><td><Money v={c.total_volume}/></td>
            <td><Pct v={c.ath_change_percent}/></td>
          </tr>)}</tbody>
        </table>
      </section>}
      <small>{rep.disclaimer}</small>
    </>}
  </section>;
}