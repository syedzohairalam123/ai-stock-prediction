import Plot from "react-plotly.js";
type Row={date:string;rsi_14?:number;macd?:number;macd_signal?:number;stoch_k?:number;stoch_d?:number;adx_14?:number;plus_di_14?:number;minus_di_14?:number};
const layout=(title:string,extra:object={})=>({title,paper_bgcolor:"#10172bbd",plot_bgcolor:"#10172bbd",font:{color:"#e6edf7",size:11},
  margin:{t:34,l:38,r:12,b:26},xaxis:{gridcolor:"#263458"},yaxis:{gridcolor:"#263458"},showlegend:true,legend:{orientation:"h",y:1.25},...extra} as any);
const cfg={responsive:true,displaylogo:false,displayModeBar:false} as any;
export default function IndicatorPanels({rows}:{rows:Row[]}){
  const x=rows.map(r=>r.date);
  if(!rows.length) return null;
  return <section className="panel indicators">
    <h2>Momentum &amp; Trend Indicators</h2>
    <div className="indicator-grid">
      <div className="indicator-cell">
        <Plot data={[{x,y:rows.map(r=>r.rsi_14??null),type:"scatter",mode:"lines",name:"RSI 14",line:{color:"#67e8f9"}},
          {x,y:x.map(()=>70),type:"scatter",mode:"lines",name:"Overbought",line:{color:"#fb7185",dash:"dot",width:1}},
          {x,y:x.map(()=>30),type:"scatter",mode:"lines",name:"Oversold",line:{color:"#4ade80",dash:"dot",width:1}}]}
          layout={layout("RSI (14)",{yaxis:{range:[0,100],gridcolor:"#263458"}})} config={cfg} style={{width:"100%",height:210}}/>
      </div>
      <div className="indicator-cell">
        <Plot data={[{x,y:rows.map(r=>r.macd??null),type:"scatter",mode:"lines",name:"MACD",line:{color:"#f472b6"}},
          {x,y:rows.map(r=>r.macd_signal??null),type:"scatter",mode:"lines",name:"Signal",line:{color:"#facc15",dash:"dot"}}]}
          layout={layout("MACD")} config={cfg} style={{width:"100%",height:210}}/>
      </div>
      <div className="indicator-cell">
        <Plot data={[{x,y:rows.map(r=>r.stoch_k??null),type:"scatter",mode:"lines",name:"%K",line:{color:"#2dd4bf"}},
          {x,y:rows.map(r=>r.stoch_d??null),type:"scatter",mode:"lines",name:"%D",line:{color:"#f472b6",dash:"dot"}}]}
          layout={layout("Stochastic Oscillator",{yaxis:{range:[0,100],gridcolor:"#263458"}})} config={cfg} style={{width:"100%",height:210}}/>
      </div>
      <div className="indicator-cell">
        <Plot data={[{x,y:rows.map(r=>r.adx_14??null),type:"scatter",mode:"lines",name:"ADX",line:{color:"#e6edf7",width:2}},
          {x,y:rows.map(r=>r.plus_di_14??null),type:"scatter",mode:"lines",name:"+DI",line:{color:"#4ade80"}},
          {x,y:rows.map(r=>r.minus_di_14??null),type:"scatter",mode:"lines",name:"-DI",line:{color:"#fb7185"}}]}
          layout={layout("ADX / Directional Index")} config={cfg} style={{width:"100%",height:210}}/>
      </div>
    </div>
  </section>;
}
