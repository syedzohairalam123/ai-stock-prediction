/**
 * Phase 21B §15 — data source panel.
 *
 * For one match: its source, last update, data mode and data quality
 * (LIVE / DELAYED / STALE / UNAVAILABLE). For the hub: per-provider health.
 * Nothing here is inferred — every value is the backend's own label.
 */
import { Database } from "lucide-react";

import {
  dataModeTone,
  formatDateTime,
  NA,
  relTime,
  type EsportsMatch,
  type SourceStatus,
} from "../../lib/esports";

function toneClass(value: string | null | undefined): string {
  return `esp-mode--${dataModeTone(value)}`;
}

export default function DataSourcePanel({
  match,
  sources,
}: {
  match?: EsportsMatch | null;
  sources?: SourceStatus[];
}) {
  return (
    <section className="esp-sources" aria-label="Data source status">
      <h3>
        <Database size={13} aria-hidden="true" /> Data source
      </h3>

      {match && (
        <dl className="esp-sources-grid">
          <div>
            <dt>Source</dt>
            <dd>{match.source || NA}</dd>
          </div>
          <div>
            <dt>Last updated</dt>
            <dd title={formatDateTime(match.last_updated)}>{relTime(match.last_updated)}</dd>
          </div>
          <div>
            <dt>Data mode</dt>
            <dd>
              <span className={`esp-mode ${toneClass(match.data_mode)}`}>{match.data_mode || NA}</span>
            </dd>
          </div>
          <div>
            <dt>Data quality</dt>
            <dd>
              <span className={`esp-mode ${toneClass(match.data_quality)}`}>{match.data_quality || NA}</span>
            </dd>
          </div>
        </dl>
      )}

      {sources && sources.length > 0 && (
        <ul className="esp-provider-list">
          {sources.map((source) => (
            <li key={source.name} className={`esp-provider esp-provider--${(source.status || "unknown").toLowerCase()}`}>
              <div className="esp-provider-head">
                <strong>{source.name}</strong>
                <span>{source.status}</span>
              </div>
              <p className="esp-muted">
                {source.request_count ?? NA} requests
                {source.error_count ? ` · ${source.error_count} errors` : ""}
                {typeof source.avg_latency_ms === "number" ? ` · ${Math.round(source.avg_latency_ms)}ms avg` : ""}
              </p>
              <p className="esp-muted">
                {source.data_mode ? `${source.data_mode}` : "mode n/a"}
                {source.refresh ? ` · ${source.refresh}` : ""}
                {source.last_success ? ` · last ok ${relTime(source.last_success)}` : ""}
              </p>
              {source.error && <p className="esp-provider-error">{source.error}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
