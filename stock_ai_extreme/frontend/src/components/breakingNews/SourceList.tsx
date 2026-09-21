/**
 * Phase 17 (spec §16) — source reliability.
 *
 * Every number here is stored: the reliability blend and its parts were computed
 * by the backend from observable feed behaviour (articles published, breaking
 * rate, feed errors, fetch success). An unsourced social post never appears
 * equivalent to an official filing, because the score is computed from the
 * publisher's registered source type and its own track record.
 */
import { useState } from "react";
import { AlertTriangle, ExternalLink, Radio } from "lucide-react";
import {
  fixed,
  formatDateTime,
  statusClass,
  type SourceMetadata,
  type SourcesResponse,
} from "../../lib/breakingNews";

interface Props {
  data: SourcesResponse | null;
  loading?: boolean;
  error?: string | null;
  /** Number of publishers rendered before "show all". */
  initial?: number;
}

export default function SourceList({ data, loading = false, error = null, initial = 12 }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (loading) return <p className="bn-muted">Loading publisher registry…</p>;
  if (error) return <p className="bn-warning"><AlertTriangle size={13} aria-hidden /> {error}</p>;
  if (!data || data.sources.length === 0) {
    return (
      <p className="bn-muted">
        No publishers registered yet. Sources are recorded the first time a feed delivers a real article.
      </p>
    );
  }

  const rows = expanded ? data.sources : data.sources.slice(0, initial);
  const summary = data.summary ?? {};

  return (
    <div className="bn-sources">
      <ul className="bn-source-list">
        {rows.map((source) => (
          <li key={source.id} className="bn-source-row">
            <div className="bn-source-main">
              <span className="bn-source-name">
                {source.publisher}
                <span className={`bn-badge ${statusClass(source.status)}`}>{source.status}</span>
              </span>
              <span className="bn-source-meta">
                {source.source_type}
                {source.region && ` · ${source.region}`}
                {source.feed_key && ` · feed ${source.feed_key}`}
                {" · "}
                {source.article_count} articles ({source.breaking_count} breaking)
              </span>
              <span className="bn-source-meta">
                Last published {formatDateTime(source.last_published)} · retrieved {formatDateTime(source.last_retrieved)}
              </span>
              {source.last_error && (
                <span className="bn-source-error" title={source.last_error}>
                  <AlertTriangle size={11} aria-hidden /> {source.consecutive_errors} consecutive error(s):{" "}
                  {truncate(source.last_error)}
                </span>
              )}
            </div>
            <div className="bn-source-scores">
              <Score label="Reliability" value={source.reliability_score} />
              <Score label="Timeliness" value={source.timeliness_score} />
              <Score label="Completeness" value={source.completeness_score} />
              <Score label="Accuracy" value={source.accuracy_score} />
              {source.source_url && (
                <a href={source.source_url} target="_blank" rel="noopener noreferrer" className="bn-link">
                  <ExternalLink size={11} aria-hidden /> source
                </a>
              )}
            </div>
          </li>
        ))}
      </ul>

      {data.sources.length > initial && (
        <button type="button" className="bn-ghost-btn" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show fewer publishers" : `Show all ${data.sources.length} publishers`}
        </button>
      )}

      {data.feed_health.length > 0 && (
        <div className="bn-feed-health">
          <h5>
            <Radio size={13} aria-hidden /> Feed health (last ingest)
          </h5>
          <ul>
            {data.feed_health.map((feed, index) => (
              <li key={`${String(feed.key ?? feed.name ?? index)}`}>
                <span>{String(feed.name ?? feed.key ?? "feed")}</span>
                <span className="bn-muted">
                  {feed.ok === false ? `error: ${String(feed.error ?? "unknown")}` : `${String(feed.items ?? 0)} items`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="bn-note">
        Registry generated {formatDateTime(data.generated_at)}
        {typeof summary["average_reliability"] === "number" &&
          ` · mean reliability ${fixed(summary["average_reliability"] as number, 3)}`}
        {typeof summary["active"] === "number" && ` · ${summary["active"]} active`}
        {typeof summary["degraded"] === "number" && ` · ${summary["degraded"]} degraded`}
      </p>
    </div>
  );
}

function Score({ label, value }: { label: string; value: number | null }) {
  const pct = value === null ? null : Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="bn-source-score" title={value === null ? "not measured yet" : `${label}: ${value.toFixed(3)}`}>
      <span className="bn-k">{label}</span>
      <span className="bn-score-bar" aria-hidden>
        <span className="bn-score-fill" style={{ width: pct === null ? "0%" : `${pct}%` }} />
      </span>
      <span className="bn-score-value">{value === null ? "n/a" : fixed(value, 2)}</span>
    </span>
  );
}

function truncate(value: string, max = 96): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}
