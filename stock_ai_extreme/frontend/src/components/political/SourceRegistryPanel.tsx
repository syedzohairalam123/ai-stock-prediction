/**
 * Phase 18 — source registry (spec §5, §13).
 *
 * Every external source, its attribution, its capabilities and its honest
 * health. A source that cannot be reached is shown as unavailable with the
 * reason — it is never hidden and never silently replaced by a substitute.
 */
import { Database, KeyRound } from "lucide-react";
import { usePoliticalSources } from "../../hooks/usePoliticalQueries";
import { fmtDateTime, relativeTime, type SourceStatus } from "../../lib/political";

const STATUS_CLASS: Record<SourceStatus, string> = {
  OK: "ok",
  DEGRADED: "degraded",
  UNAVAILABLE: "unavailable",
  DISABLED: "disabled",
};

const CAPABILITY_LABELS: Record<string, string> = {
  events: "calendar events",
  regional_measurements: "regional measurements",
  historical_measurements: "historical results",
  timeline: "coverage timeline",
  sources: "source descriptors",
};

export default function SourceRegistryPanel() {
  const query = usePoliticalSources();

  return (
    <section className="political-sources panel" aria-label="Data sources">
      <div className="political-sources-head">
        <h2><Database size={15} aria-hidden /> Data sources &amp; attribution</h2>
        {query.data && (
          <span className="dim">
            {query.data.summary.ok ?? 0} ok · {query.data.summary.degraded ?? 0} degraded ·{" "}
            {query.data.summary.unavailable ?? 0} unavailable
          </span>
        )}
      </div>

      {query.isLoading && <div className="skeleton" style={{ height: 100 }} />}
      {query.isError && (
        <div className="market-state market-state-error" role="alert">
          <strong>Source registry unavailable</strong>
          <span>{(query.error as Error)?.message ?? "The backend could not list its sources."}</span>
        </div>
      )}

      {query.data && (
        <ul className="political-source-list">
          {query.data.sources.map((source) => (
            <li key={source.id}>
              <div className="political-source-top">
                <strong>{source.source_url ? (
                  <a href={source.source_url} target="_blank" rel="noopener noreferrer">{source.name}</a>
                ) : source.name}</strong>
                <span className={`political-source-status ${STATUS_CLASS[source.status]}`}>
                  {source.status}
                </span>
              </div>
              <p>{source.description}</p>
              <div className="political-source-meta">
                <span className="dim">{source.kind}</span>
                {source.requires_key && (
                  <span className="political-source-key">
                    <KeyRound size={11} aria-hidden />
                    {source.key_configured ? "key configured" : "no key — may be limited"}
                  </span>
                )}
                <span className="dim">
                  {source.last_success_at
                    ? `last success ${relativeTime(source.last_success_at)}`
                    : "no successful fetch yet"}
                </span>
              </div>
              <div className="political-source-caps">
                {source.capabilities.length === 0 && <span className="dim">no capabilities advertised</span>}
                {source.capabilities.map((capability) => (
                  <span key={capability} className="political-cap-chip">
                    {CAPABILITY_LABELS[capability] ?? capability}
                  </span>
                ))}
              </div>
              {source.last_error && (
                <div className="political-source-error" role="status">
                  {source.last_error}
                  {source.last_fetch_at ? ` (at ${fmtDateTime(source.last_fetch_at)})` : ""}
                </div>
              )}
              {source.attribution && <div className="political-source-attribution dim">{source.attribution}</div>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
