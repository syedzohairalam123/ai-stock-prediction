import {useEffect,useState} from "react";
const API=import.meta.env.VITE_API_URL||"http://127.0.0.1:8000";
export default function DriftIndicator({ticker,model}:{ticker:string;model:string}){
  const [report,setReport]=useState<any>(null);
  useEffect(()=>{
    fetch(`${API}/api/monitoring/drift?ticker=${ticker}&model=${model}`).then(r=>r.json()).then(setReport).catch(()=>setReport(null));
  },[ticker,model]);
  if(!report||report.status==="insufficient_data") return (
    <div className="drift-indicator neutral">Model health: not enough resolved predictions yet for {ticker}/{model}.</div>
  );
  return <div className={`drift-indicator ${report.drift_detected?"warn":"ok"}`}>
    Model health ({report.sample_size} resolved predictions): {report.drift_detected?"⚠ possible drift":"✓ stable"} — recent MAE {report.recent_mae} vs overall {report.overall_mae}
  </div>;
}
