import {useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
type SentimentT={score:number;label:string;positive_words:number;negative_words:number};
type NewsItemT={title:string;publisher:string|null;link:string|null;published_at:string|null;sentiment:SentimentT};
type NewsT={items:NewsItemT[];aggregate:{total:number;average_score:number;label:string;bullish_count:number;bearish_count:number;neutral_count:number};meta?:{source?:string;status?:string};disclaimer?:string};
function SentimentChip({s}:{s:SentimentT}){
  const cls=s.label==="bullish"?"pos":s.label==="bearish"?"neg":"neutral";
  return <span className={`sentiment-chip ${cls}`}>{s.label==="bullish"?"▲":s.label==="bearish"?"▼":"◆"} {s.label} <small>({s.score>=0?"+":""}{s.score.toFixed(2)})</small></span>;
}
export default function NewsPanel({ticker}:{ticker:string}){
  const [data,setData]=useState<NewsT|null>(null),[error,setError]=useState<string|null>(null),[loading,setLoading]=useState(false);
  useEffect(()=>{
    let cancelled=false;setLoading(true);setError(null);
    fetch(`${API}/api/stocks/${ticker}/news`).then(r=>r.ok?r.json():Promise.reject(r.status))
      .then(d=>{if(!cancelled)setData(d)})
      .catch(()=>{if(!cancelled)setError("News unavailable right now.")})
      .finally(()=>{if(!cancelled)setLoading(false)});
    return ()=>{cancelled=true};
  },[ticker]);
  const agg=data?.aggregate;
  return <section className="panel news">
    <div className="news-head">
      <h2>News & Sentiment — {ticker}</h2>
      {agg&&<div className="news-agg">
        <span className={`sentiment-chip ${agg.label==="bullish"?"pos":agg.label==="bearish"?"neg":"neutral"}`}>{agg.label==="bullish"?"▲":agg.label==="bearish"?"▼":"◆"} aggregate: {agg.label}</span>
        <span className="news-counts">{agg.bullish_count}▲ · {agg.bearish_count}▼ · {agg.neutral_count}◆ of {agg.total}</span>
      </div>}
    </div>
    {loading&&<p className="empty">Loading headlines…</p>}
    {error&&<p className="empty">{error}</p>}
    {!loading&&!error&&data&&data.items.length===0&&<p className="empty">No recent headlines for {ticker}.</p>}
    {!loading&&!error&&data&&data.items.length>0&&<ul className="news-list">
      {data.items.map((n,i)=><li key={i}>
        <SentimentChip s={n.sentiment}/>
        {n.link?<a href={n.link} target="_blank" rel="noreferrer">{n.title}</a>:<span>{n.title}</span>}
        <small>{n.publisher||""}{n.published_at?` · ${new Date(n.published_at).toLocaleDateString()}`:""}</small>
      </li>)}
    </ul>}
    <small className="news-disclaimer">{data?.disclaimer||"Lexicon-based sentiment heuristic, not investment advice."}</small>
  </section>;
}