import {useEffect,useRef,useState} from "react";
const WS_URL=import.meta.env.VITE_WS_URL||"ws://127.0.0.1:8000";
export type LiveQuote={type:string;ticker?:string;price?:number|null;source?:string;status?:string;timestamp?:string;message?:string};
export function useStockWebSocket(ticker:string){
  const [quote,setQuote]=useState<LiveQuote|null>(null);
  const [state,setState]=useState("connecting");
  const retry=useRef<number>();
  useEffect(()=>{
    let socket:WebSocket|undefined;
    let stopped=false;
    let connectTimer:number|undefined;
    const open=()=>{
      if(stopped) return;
      setState("connecting");
      const ws=new WebSocket(`${WS_URL}/ws/stock/${encodeURIComponent(ticker)}`);
      socket=ws;
      ws.onopen=()=>{
        if(stopped){ws.close();return;}
        setState("connected");
      };
      ws.onmessage=e=>{try{setQuote(JSON.parse(e.data))}catch{}};
      ws.onerror=()=>setState("error");
      ws.onclose=()=>{
        if(!stopped){
          setState("reconnecting");
          retry.current=window.setTimeout(open,3000);
        }
      };
    };
    // Defer the connection by one tick: React StrictMode double-mounts effects
    // in dev, and the first mount's cleanup used to close a socket that was
    // still CONNECTING — which makes the browser log "WebSocket is closed
    // before the connection is established". Deferring means the first
    // mount's cleanup cancels the timer before any socket exists.
    connectTimer=window.setTimeout(open,0);
    return()=>{
      stopped=true;
      window.clearTimeout(connectTimer);
      window.clearTimeout(retry.current);
      socket?.close();
    };
  },[ticker]);
  return{quote,state};
}