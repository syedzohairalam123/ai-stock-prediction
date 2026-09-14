import type { IndexSnapshot } from "../lib/psxMarket";
import { fmtCompact, fmtNum } from "../lib/psxMarket";

export default function IndexStats({ snapshot }: { snapshot: IndexSnapshot }) {
  const up = snapshot.change >= 0;
  const rows: [string, string, string?][] = [
    ["Total Volume", fmtCompact(snapshot.totalVolume)],
    ["Traded Value", `₨ ${fmtCompact(snapshot.tradedValue)}`],
    ["Previous Close", fmtNum(snapshot.prevClose)],
    ["Open", fmtNum(snapshot.open)],
    ["Current Value", fmtNum(snapshot.value)],
    ["Day Change", `${up ? "+" : ""}${fmtNum(snapshot.change)} (${up ? "+" : ""}${snapshot.changePct.toFixed(2)}%)`, up ? "pos" : "neg"],
  ];
  return (
    <div className="index-stats">
      {rows.map(([label, value, cls]) => (
        <div className="index-stat" key={label}>
          <span className="index-stat-label">{label}</span>
          <span className={`index-stat-value ${cls || ""}`}>{value}</span>
        </div>
      ))}
    </div>
  );
}