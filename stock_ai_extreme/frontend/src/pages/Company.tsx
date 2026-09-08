import {FormEvent,useEffect,useState} from "react";
import {getJSON,Num,Pct,Money,MetaBadge} from "../lib/api";
type Valuation={trailing_pe:number|null;forward_pe:number|null;price_to_book:number|null;price_to_sales:number|null;eps_trailing:number|null;eps_forward:number|null;peg_ratio:number|null;market_cap:number|null;enterprise_value:number|null};
type Report={ticker:string;valuation:Valuation;profitability:Record<string,number|null|string>;balance_sheet:Record<string,number|null|string>;dividends:Record<string,any>;analyst:Record<string,any>;price_context:Record<string,number>;employees:number|null;sector:string|null;industry:string|null;data_meta?:any;disclaimer:string};
const EXAMPLES=["AAPL","MSFT","NVDA","JPM","XOM"];
function Row({label,value,hint}:{label:string;value:React.ReactNode;hint?:string}){return <div className="kv"><span>{label}{hint&&<small className="dim"> {hint}</small>}</span><b>{value??"—"}</b></div>}
export default function Company(){
  const [ticker,setTicker]=useState("AAPL"),[data,setData]=useState<Report|null>(null),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  async function load(t:string){
    setBusy(true);setErr(null);setData(null);
    try{setData(await getJSON<Report>(`/api/stocks/${t}/fundamentals`))}
    catch(e:any){setErr(e.message)}
    finally{setBusy(false)}
  }
  useEffect(()=>{load("AAPL")},[]);
  function submit(e:FormEvent){e.preventDefault();if(ticker.trim())load(ticker.trim().toUpperCase())}
  const p=data?.price_context||{},prof=data?.profitability||{};
  return <section>
    <header className="page-head"><div><p>Company deep-dive</p><h1>Company Fundamentals</h1></div></header>
    <form onSubmit={submit} className="row-form">
      <label>Ticker <input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} aria-label="Ticker"/></label>
      <button disabled={busy}>{busy?"Loading…":"Load fundamentals"}</button>
      <div className="chips">{EXAMPLES.map(t=><button type="button" key={t} className="chip as-btn" onClick={()=>{setTicker(t);load(t)}}>{t}</button>)}</div>
    </form>
    {err&&<p className="error-text">{err}</p>}
    {data&&<>
      <div className="card-row">
        <div className="card"><div className="k">Market cap</div><div className="v"><Money v={data.valuation.market_cap}/></div><div className="s">{data.sector||"sector n/a"} · {data.industry||"industry n/a"}</div></div>
        <div className="card"><div className="k">P/E (trailing)</div><div className="v"><Num v={data.valuation.trailing_pe}/></div><div className="s">forward <Num v={data.valuation.forward_pe}/> · PEG <Num v={data.valuation.peg_ratio}/></div></div>
        <div className="card"><div className="k">Profitability grade</div><div className={`v ${(prof.grade as string)==="strong"||(prof.grade as string)==="healthy"?"pos":prof.grade==="weak"?"neg":""}`}>{(prof.grade as string)||"—"}</div><div className="s">ROE <Num v={prof.return_on_equity_pct as number}/> · margin <Num v={prof.profit_margin_pct as number}/>%</div></div>
        <div className="card"><div className="k">52-week position</div><div className="v">{p.position_52w_pct!==undefined?`${p.position_52w_pct.toFixed(0)}%`:"—"}</div><div className="s">low <Num v={p.low_52w}/> · high <Num v={p.high_52w}/></div></div>
      </div>
      <div className="grid-2">
        <section className="panel"><h2>Valuation <MetaBadge meta={data.data_meta}/></h2>
          <Row label="Price / Book" value={<Num v={data.valuation.price_to_book}/>}/>
          <Row label="Price / Sales" value={<Num v={data.valuation.price_to_sales}/>}/>
          <Row label="EPS (trailing / forward)" value={<><Num v={data.valuation.eps_trailing}/> / <Num v={data.valuation.eps_forward}/></>}/>
          <Row label="Enterprise value" value={<Money v={data.valuation.enterprise_value}/>}/>
          <Row label="Employees" value={data.employees?.toLocaleString()}/>
        </section>
        <section className="panel"><h2>Balance sheet & dividends</h2>
          <Row label="Net cash" value={<Money v={data.balance_sheet.net_cash as number}/>}/>
          <Row label="Debt / equity" value={<><Num v={data.balance_sheet.debt_to_equity_pct as number}/>% ({(data.balance_sheet.leverage as string)||"—"})</>}/>
          <Row label="Current ratio" value={<Num v={data.balance_sheet.current_ratio as number}/>}/>
          <Row label="Dividend rate / yield" value={<><Money v={data.dividends.dividend_rate}/> · <Num v={data.dividends.dividend_yield_pct as number}/>%</>}/>
          <Row label="Payout ratio" value={<Num v={data.dividends.payout_ratio_pct as number}/>}/>
        </section>
      </div>
      <div className="grid-2">
        <section className="panel"><h2>Analyst view</h2>
          <Row label="Consensus" value={(data.analyst.recommendation_key as string)?.toUpperCase()}/>
          <Row label="Target mean" value={<Money v={data.analyst.target_mean_price}/>}/>
          <Row label="Target range" value={<><Money v={data.analyst.target_low_price}/> – <Money v={data.analyst.target_high_price}/></>}/>
          <Row label="Implied upside" value={<Pct v={data.analyst.target_upside_pct}/>}/>
          <Row label="Analysts" value={data.analyst.analysts_count as number}/>
        </section>
        <section className="panel"><h2>Price context</h2>
          <Row label="1-month return" value={<Pct v={p.return_1m_pct}/>}/>
          <Row label="3-month return" value={<Pct v={p.return_3m_pct}/>}/>
          <Row label="Gross margin" value={<Pct v={prof.gross_margin_pct as number}/>}/>
          <Row label="Operating margin" value={<Pct v={prof.operating_margin_pct as number}/>}/>
          <Row label="Return on assets" value={<Pct v={prof.return_on_assets_pct as number}/>}/>
        </section>
      </div>
      <small>{data.disclaimer}</small>
    </>}
  </section>;
}
