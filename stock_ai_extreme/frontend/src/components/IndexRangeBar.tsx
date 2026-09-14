import { fmtNum } from "../lib/psxMarket";

interface Props {
  label: string;
  low: number;
  high: number;
  current: number;
}

export default function IndexRangeBar({ label, low, high, current }: Props) {
  const span = high - low || 1;
  const pct = Math.min(100, Math.max(0, ((current - low) / span) * 100));

  return (
    <div className="index-range">
      <div className="index-range-head">
        <span className="index-range-label">{label}</span>
        <span className="index-range-value">
          <span className="low">{fmtNum(low)}</span>
          <span className="current">{fmtNum(current)}</span>
          <span className="high">{fmtNum(high)}</span>
        </span>
      </div>
      <div className="index-range-track">
        <div className="index-range-fill" style={{ width: `${pct}%` }} />
        <div className="index-range-marker" style={{ left: `${pct}%` }} title={`${fmtNum(current)}`} />
      </div>
      <div className="index-range-scale">
        <span>LOW</span>
        <span>HIGH</span>
      </div>
    </div>
  );
}