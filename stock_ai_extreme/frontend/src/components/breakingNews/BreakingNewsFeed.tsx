/**
 * Phase 17 (spec §4, §5, §6, §17) — the breaking feed.
 *
 * What the UI deliberately does *not* do:
 *
 * * It never labels a story "breaking" itself — the level comes from the stored
 *   score, and the score's components and weights are shown on demand.
 * * It never shows five copies of one event as five stories: rows are clusters,
 *   and the count of corroborating publishers is printed with them.
 * * It never presents an AI summary as fact: summaries are fetched on request,
 *   rendered in a labelled block, and a provider that is unavailable says so.
 */
import { useState } from "react";
import { AlertTriangle, Bot, ChevronDown, ChevronRight, ExternalLink, Layers, RefreshCw, Users } from "lucide-react";
import {
  fetchEventDetail,
  fixed,
  formatDateTime,
  levelClass,
  rankedComponents,
  summarizeEvent,
  timeAgo,
  type BreakingFeedMeta,
  type BreakingNewsEvent,
  type EventSummary,
  type StreamTransport,
} from "../../lib/breakingNews";
import NewsImpactCard from "./NewsImpactCard";

interface Props {
  items: BreakingNewsEvent[];
  meta: BreakingFeedMeta | null;
  loading: boolean;
  error: string | null;
  transport?: StreamTransport;
  selectedId?: string | null;
  onSelect?: (event: BreakingNewsEvent | null) => void;
  onRefresh?: () => void;
  onIngest?: () => void;
  ingesting?: boolean;
  /** Entities offered as impact targets for the selected event. */
  impactTargetsFor?: (event: BreakingNewsEvent) => Array<{ entity: string; entityType?: "STOCK" | "INDEX" | "COMMODITY" | "FOREX" | "CRYPTO" }>;
}

export default function BreakingNewsFeed({
  items,
  meta,
  loading,
  error,
  transport,
  selectedId,
  onSelect,
  onRefresh,
  onIngest,
  ingesting = false,
  impactTargetsFor,
}: Props) {
  if (loading && items.length === 0) {
    return <p className="bn-muted">Building the breaking desk from the stored corpus…</p>;
  }

  if (error) {
    return (
      <div className="bn-warning bn-warning-lg" role="alert">
        <AlertTriangle size={15} aria-hidden />
        <div>
          <strong>The feed could not be built.</strong>
          <p>{error}</p>
          {onRefresh && (
            <button type="button" className="bn-btn" onClick={onRefresh}>
              <RefreshCw size={12} aria-hidden /> Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="bn-empty">
        <Layers size={22} aria-hidden />
        <p>No events in this window.</p>
        <p className="bn-muted">
          The desk only shows stories built from real publisher timestamps inside the selected window. Run an ingest to
          pull live feeds.
        </p>
        {onIngest && (
          <button type="button" className="bn-btn" onClick={onIngest} disabled={ingesting}>
            <RefreshCw size={12} className={ingesting ? "bn-spin" : undefined} aria-hidden />
            {ingesting ? "Ingesting live feeds…" : "Ingest live feeds"}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="bn-feed">
      {meta && (
        <div className="bn-feed-meta">
          <span>
            {meta.total_events} events · {meta.breaking_count} breaking · {meta.significant_count} significant
          </span>
          <span>
            {meta.articles_analyzed} articles analysed → {meta.clusters_found} clusters from{" "}
            {meta.sources_consulted} sources
          </span>
          <span>Built {formatDateTime(meta.generated_at)}</span>
          {transport && <span className="bn-transport">transport: {transport}</span>}
        </div>
      )}

      <ol className="bn-feed-list">
        {items.map((event) => (
          <li key={event.id}>
            <FeedRow
              event={event}
              selected={selectedId === event.id}
              onSelect={onSelect}
              impactTargets={impactTargetsFor?.(event) ?? []}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}

function FeedRow({
  event,
  selected,
  onSelect,
  impactTargets,
}: {
  event: BreakingNewsEvent;
  selected: boolean;
  onSelect?: (event: BreakingNewsEvent | null) => void;
  impactTargets: Array<{ entity: string; entityType?: "STOCK" | "INDEX" | "COMMODITY" | "FOREX" | "CRYPTO" }>;
}) {
  const [showScores, setShowScores] = useState(false);
  const [coverage, setCoverage] = useState<Array<{ id?: number; title?: string; url?: string; publisher?: string }> | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [impactTarget, setImpactTarget] = useState(impactTargets[0]?.entity ?? null);
  const [summary, setSummary] = useState<EventSummary | null>(null);
  const [summaryState, setSummaryState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const components = rankedComponents(event.score_components, event.score_weights);

  const openCoverage = async () => {
    if (coverage || coverageError) return;
    try {
      const detail = await fetchEventDetail(event.id);
      const raw = detail.market_associations?.["corroborating_coverage"];
      const rows = Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
      setCoverage(
        rows.map((row) => ({
          id: typeof row.id === "number" ? row.id : undefined,
          title: typeof row.title === "string" ? row.title : undefined,
          url: typeof row.url === "string" ? row.url : undefined,
          publisher: typeof row.publisher === "string" ? row.publisher : undefined,
        })),
      );
    } catch (err) {
      setCoverageError(err instanceof Error ? err.message : "Coverage lookup failed");
    }
  };

  const requestSummary = async (force = false) => {
    setSummaryState("loading");
    setSummaryError(null);
    try {
      const result = await summarizeEvent(event.id, force);
      setSummary(result);
      setSummaryState("ready");
    } catch (err) {
      setSummaryError(err instanceof Error ? err.message : "Summary request failed");
      setSummaryState("error");
    }
  };

  const toggleSelected = () => {
    const next = selected ? null : event;
    onSelect?.(next);
    if (next) void openCoverage();
  };

  return (
    <article id={`bn-event-${event.id}`} className={`bn-item${selected ? " selected" : ""}`}>
      <div className="bn-item-head">
        <span className={`bn-badge ${levelClass(event.breaking_level)}`}>{event.breaking_level}</span>
        <span className="bn-score" title={`Breaking score ${event.breaking_score.toFixed(2)} of 100`}>
          {event.breaking_score.toFixed(1)}
        </span>
        <button type="button" className="bn-score-toggle" onClick={() => setShowScores((v) => !v)} aria-expanded={showScores}>
          {showScores ? <ChevronDown size={12} aria-hidden /> : <ChevronRight size={12} aria-hidden />} score
        </button>
        {event.data_mode && <span className="bn-mode">{event.data_mode}</span>}
        {event.impact_detected && <span className="bn-badge bn-mag-medium">impact measured</span>}
        {event.ai_summary && <span className="bn-badge bn-ai-badge"><Bot size={10} aria-hidden /> AI summary</span>}
      </div>

      <h3 className="bn-item-title">
        <a href={event.url} target="_blank" rel="noopener noreferrer">
          {event.title}
        </a>
      </h3>

      {event.excerpt && <p className="bn-item-excerpt">{event.excerpt}</p>}

      <div className="bn-item-meta">
        <span>{event.publisher || "publisher unavailable"}</span>
        {/* The publisher's own clock, never the fetch time. */}
        <span title={formatDateTime(event.published_at)}>{event.time_ago ?? timeAgo(event.published_at)}</span>
        {event.category && <span>{event.category}</span>}
        {event.cluster_size > 1 && (
          <span className="bn-cluster" title="Independent publishers covering the same event">
            <Users size={11} aria-hidden /> {event.cluster_size} sources
          </span>
        )}
        {event.source && <span className="bn-source-key">{event.source}</span>}
      </div>

      {(event.affected_entities.length > 0 || event.affected_indices.length > 0 || event.topics.length > 0) && (
        <div className="bn-chip-row">
          {event.affected_entities.slice(0, 10).map((entity) => (
            <span key={entity} className="bn-chip">
              {entity}
            </span>
          ))}
          {event.affected_indices.slice(0, 6).map((entity) => (
            <span key={entity} className="bn-chip bn-chip-index">
              {entity}
            </span>
          ))}
          {event.topics.slice(0, 6).map((topic) => (
            <span key={topic} className="bn-chip bn-chip-topic">
              #{topic}
            </span>
          ))}
        </div>
      )}

      {showScores && (
        <div className="bn-breakdown">
          {components.length === 0 ? (
            <p className="bn-muted">No stored score breakdown for this event.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Component</th>
                  <th scope="col">Value</th>
                  <th scope="col">Weight</th>
                </tr>
              </thead>
              <tbody>
                {components.map((row) => (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td>{fixed(row.contribution, 3)}</td>
                    <td>{row.weight === null ? "—" : fixed(row.weight, 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="bn-note">
            Weighted sum of the components above. The detector never treats "most recent" as "most breaking".
          </p>
        </div>
      )}

      {coverage && coverage.length > 0 && (
        <div className="bn-coverage">
          <h5>Corroborating coverage</h5>
          <ul>
            {coverage.slice(0, 8).map((row, index) => (
              <li key={`${row.id ?? index}`}>
                {row.url ? (
                  <a href={row.url} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={11} aria-hidden /> {row.publisher ?? "publisher unavailable"}
                  </a>
                ) : (
                  <span>{row.publisher ?? "publisher unavailable"}</span>
                )}
                <span className="bn-muted">{row.title ?? "headline unavailable"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {coverageError && <p className="bn-warning">{coverageError}</p>}

      <div className="bn-item-actions">
        <button type="button" className="bn-btn" onClick={toggleSelected}>
          <Layers size={12} aria-hidden /> {selected ? "Hide market impact" : "Market impact"}
        </button>
        <button type="button" className="bn-btn" onClick={() => void requestSummary(false)} disabled={summaryState === "loading"}>
          <Bot size={12} className={summaryState === "loading" ? "bn-spin" : undefined} aria-hidden />
          {event.ai_summary && summaryState === "idle" ? "Show AI summary" : "Generate AI summary"}
        </button>
        {summaryState === "ready" && (
          <button type="button" className="bn-ghost-btn" onClick={() => void requestSummary(true)}>
            Regenerate
          </button>
        )}
      </div>

      {summaryState === "error" && (
        <div className="bn-warning" role="alert">
          <AlertTriangle size={13} aria-hidden /> {summaryError}
        </div>
      )}

      {summaryState !== "error" && (summary?.summary || event.ai_summary) && (
        <div className="bn-ai-summary">
          <header>
            <Bot size={12} aria-hidden />
            <strong>AI-generated summary</strong>
            <span className="bn-muted">
              {summary?.model ?? event.ai_summary_model ?? "model unavailable"} ·{" "}
              {formatDateTime(summary?.generated_at ?? event.ai_summary_generated_at)}
            </span>
          </header>
          <p>{summary?.summary ?? event.ai_summary}</p>
          <p className="bn-note">
            {summary?.label ?? "AI-generated summary — verify against the source article."} It is grounded in the stored
            article text and adds no facts of its own.
          </p>
        </div>
      )}

      {summaryState === "ready" && !summary?.summary && (
        <div className="bn-warning">
          <AlertTriangle size={13} aria-hidden />
          <span>
            {String(summary?.reason ?? summary?.message ?? summary?.status ?? "The AI provider returned no summary.")} No
            summary is shown rather than one being invented.
          </span>
        </div>
      )}

      {selected && (
        <div className="bn-impact-wrap">
          {impactTargets.length > 1 && (
            <div className="bn-impact-targets">
              <label htmlFor={`bn-target-${event.id}`}>Entity</label>
              <select
                id={`bn-target-${event.id}`}
                value={impactTarget ?? ""}
                onChange={(changeEvent) => setImpactTarget(changeEvent.target.value)}
              >
                {impactTargets.map((target) => (
                  <option key={target.entity} value={target.entity}>
                    {target.entity}
                  </option>
                ))}
              </select>
            </div>
          )}
          {impactTarget ? (
            <NewsImpactCard
              newsId={event.id}
              articleId={event.article_id}
              entity={impactTarget}
              entityType={impactTargets.find((t) => t.entity === impactTarget)?.entityType ?? "STOCK"}
              publishedAt={event.published_at}
              title={event.title}
            />
          ) : (
            <p className="bn-muted">
              No validated market entity is associated with this event, so no impact window can be measured for it.
            </p>
          )}
        </div>
      )}
    </article>
  );
}
