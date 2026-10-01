/**
 * Phase 22A — data-quality + gap-detection panel (spec §8, §11, §12).
 *
 * States plainly whether the series is complete. A detected gap is shown as
 * `DATA GAP DETECTED` with the exact counts — never silently smoothed over.
 */
import type { GapReport, QualityAssessment } from "../../lib/crypto";
import { formatDuration, NA, statusTone } from "../../lib/cryptoFormat";

export interface CryptoDataQualityPanelProps {
  quality: QualityAssessment | undefined;
  gaps: GapReport | undefined;
  timeframeLabel: string;
  parseStats?: Record<string, number> | null;
}

export function CryptoDataQualityPanel({
  quality,
  gaps,
  timeframeLabel,
  parseStats,
}: CryptoDataQualityPanelProps) {
  const hasGap = gaps ? gaps.missing_intervals > 0 : false;
  const completeness = gaps?.completeness ?? quality?.completeness ?? null;

  return (
    <section className="panel crypto-quality-panel">
      <div className="crypto-panel-head">
        <h2>
          Data quality · {timeframeLabel}
          {quality && (
            <span className={`crypto-chip ${statusTone(quality.status)}`}>{quality.label}</span>
          )}
        </h2>
        <span className={`crypto-chip ${hasGap ? "warn" : "native"}`}>
          {gaps?.label ?? "AWAITING DATA"}
        </span>
      </div>

      <div className="crypto-stat-grid compact">
        <Metric label="Freshness" value={quality?.status ?? NA} />
        <Metric label="Provider healthy" value={truthy(quality?.components?.provider_healthy)} />
        <Metric label="Symbol mapped" value={truthy(quality?.components?.symbol_mapped)} />
        <Metric label="Candles" value={num(quality?.components?.candles)} />
        <Metric label="Age" value={quality?.age_ms != null ? formatDuration(quality.age_ms / 1000) : NA} />
        <Metric
          label="Completeness"
          value={completeness != null ? `${(completeness * 100).toFixed(2)}%` : NA}
        />
        <Metric label="Expected intervals" value={gaps ? String(gaps.expected_intervals) : NA} />
        <Metric label="Received intervals" value={gaps ? String(gaps.received_intervals) : NA} />
        <Metric label="Missing intervals" value={gaps ? String(gaps.missing_intervals) : NA} highlight={hasGap} />
        <Metric label="Duplicates" value={gaps ? String(gaps.duplicate_intervals) : NA} />
        <Metric label="Out of order" value={gaps ? String(gaps.out_of_order) : NA} />
        <Metric label="Largest gap" value={gaps ? formatDuration(gaps.largest_gap_seconds) : NA} />
      </div>

      {quality?.driver && <p className="crypto-note">Quality driver: {quality.driver}</p>}

      {hasGap && gaps && (
        <div className="crypto-warn" role="status">
          <strong>DATA GAP DETECTED</strong>
          <span>
            {gaps.missing_intervals} missing interval(s) between {gaps.received_intervals} received candles;
            largest gap {formatDuration(gaps.largest_gap_seconds)}. Missing candles are not fabricated.
          </span>
        </div>
      )}

      {parseStats && (
        <details className="crypto-details">
          <summary>Provider parse audit</summary>
          <div className="crypto-kv">
            {Object.entries(parseStats).map(([key, value]) => (
              <div key={key}>
                <span>{key.replace(/_/g, " ")}</span>
                <b>{value}</b>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function Metric({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className={`crypto-stat${highlight ? " warn" : ""}`}>
      <span className="crypto-stat-k">{label}</span>
      <span className="crypto-stat-v">{value}</span>
    </div>
  );
}

function num(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : NA;
}

function truthy(value: unknown): string {
  if (value === true) return "yes";
  if (value === false) return "no";
  return NA;
}

export default CryptoDataQualityPanel;
