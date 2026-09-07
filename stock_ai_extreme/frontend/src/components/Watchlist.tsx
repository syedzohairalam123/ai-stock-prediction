import {useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
type Item={id:number;ticker:string;note:string|null;added_at:string};
export default function Watchlist({active,onSelect}:{active:string;onSelect:(t:string)=>void}){
  const [items,setItems]=useState<Item[]>([]),[input,setInput]=useState(""),[err,setErr]=useState<string|null>(null),[busy,setBusy]=useState(false);
  function load(){fetch(`${API}/api/watchlist`).then(r=>r.json()).then(setItems).catch(()=>{})}
  useEffect(load,[]);
  function add(e:React.FormEvent){
    e.preventDefault(); const t=input.trim(); if(!t) return; setBusy(true); setErr(null);
    fetch(`${API}/api/watchlist`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ticker:t})})
      .then(r=>{if(!r.ok) return r.json().then(b=>{throw new Error(b.detail||"Could not add ticker")}); return r.json()})
      .then(()=>{setInput("");load()}).catch(e=>setErr(e.message)).finally(()=>setBusy(false));
  }
  function remove(ticker:string){fetch(`${API}/api/watchlist/${ticker}`,{method:"DELETE"}).then(load)}
  return <aside className="panel watchlist">
    <h2>Watchlist</h2>
    <form onSubmit={add} className="watchlist-add">
      <input value={input} onChange={e=>setInput(e.target.value)} placeholder="Add ticker…" aria-label="Add to watchlist"/>
      <button disabled={busy}>+</button>
    </form>
    {err&&<small className="watchlist-error">{err}</small>}
    {items.length===0&&<p className="empty">No tickers saved yet.</p>}
    <ul>
      {items.map(i=><li key={i.id} className={i.ticker===active?"active":""}>
        <button className="watchlist-ticker" onClick={()=>onSelect(i.ticker)}>{i.ticker}</button>
        {i.note&&<span className="watchlist-note">{i.note}</span>}
        <button className="watchlist-remove" aria-label={`Remove ${i.ticker}`} onClick={()=>remove(i.ticker)}>×</button>
      </li>)}
    </ul>
  </aside>;
}
