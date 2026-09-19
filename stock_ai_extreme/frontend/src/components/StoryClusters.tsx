/**
 * Phase 8 — Story Clusters
 *
 * Turns a flat feed into "N outlets are reporting this".
 *
 * The grouping is the backend's TF-IDF cosine clustering over headline and lede
 * text (see `POST /api/news/clusters`). Each card shows how many articles and
 * which publishers are involved — the honest signal — plus the highest impact
 * score in the group and the terms that hold it together, so a reader can see
 * *why* these were grouped instead of trusting an opaque number.
 */

import BaseBadge from "./BaseBadge";
import { StoryCluster } from "../lib/newsService";
import { formatRelativeTime } from "../utils/dateFormat";

interface StoryClustersProps {
  clusters: StoryCluster[];
  loading?: boolean;
  error?: string | null;
  articlesAnalyzed?: number;
  disclaimer?: string;
  onOpenCluster?: (cluster: StoryCluster) => void;
}

function ClusterCard({
  cluster,
  onOpen,
}: {
  cluster: StoryCluster;
  onOpen?: (cluster: StoryCluster) => void;
}) {
  // The cluster key is `symbol-event-index`; the symbol prefix is the first
  // entity the grouping settled on, used as a readable subtitle.
  const [symbolPart, eventPart] = cluster.key.split("-");
  const title =
    cluster.symbols.length > 0
      ? cluster.symbols.slice(0, 3).join(" · ")
      : symbolPart?.toUpperCase() || "Market-wide";

  const interactive = Boolean(onOpen);
  const Wrapper = interactive ? "button" : "div";

  return (
    <Wrapper
      className={`cluster-card${interactive ? " cluster-card-interactive" : ""}`}
      {...(interactive ? { type: "button" as const, onClick: () => onOpen?.(cluster) } : {})}
    >
      <header className="cluster-card-head">
        <span className="cluster-card-size">
          <span aria-hidden="true">📰</span> {cluster.size} sources
        </span>
        {cluster.max_impact > 0 && (
          <BaseBadge
            variant={cluster.max_impact >= 65 ? "danger" : cluster.max_impact >= 38 ? "warning" : "default"}
            size="sm"
          >
            {Math.round(cluster.max_impact)}/100
            <span className="sr-only"> peak impact</span>
          </BaseBadge>
        )}
      </header>

      <h3 className="cluster-card-title">{title}</h3>

      {eventPart && eventPart !== "general" && (
        <p className="cluster-card-event">{eventPart.replace(/_/g, " ")}</p>
      )}

      <p className="cluster-card-publishers" title={cluster.publishers.join(", ")}>
        {cluster.publishers.slice(0, 4).join(" · ")}
        {cluster.publishers.length > 4 && ` +${cluster.publishers.length - 4} more`}
      </p>

      {cluster.terms.length > 0 && (
        <ul className="cluster-card-terms" aria-label="Terms defining this cluster">
          {cluster.terms.slice(0, 5).map((term) => (
            <li key={term}>{term}</li>
          ))}
        </ul>
      )}

      <footer className="cluster-card-foot">
        {cluster.last_seen && <span>Latest {formatRelativeTime(cluster.last_seen)}</span>}
        {cluster.article_ids.length > 0 && (
          <span className="cluster-card-ids">
            {cluster.article_ids.length} article
            {cluster.article_ids.length === 1 ? "" : "s"}
          </span>
        )}
      </footer>
    </Wrapper>
  );
}

export default function StoryClusters({
  clusters,
  loading,
  error,
  articlesAnalyzed,
  disclaimer,
  onOpenCluster,
}: StoryClustersProps) {
  return (
    <section className="story-clusters" aria-labelledby="clusters-heading" aria-live="polite">
      <header className="story-clusters-head">
        <div>
          <h2 id="clusters-heading">Story clusters</h2>
          <p>
            Stories being reported by more than one outlet
            {typeof articlesAnalyzed === "number" ? ` · ${articlesAnalyzed} articles analysed` : ""}
          </p>
        </div>
        <BaseBadge variant="info">{clusters.length} groups</BaseBadge>
      </header>

      {loading && (
        <div className="story-clusters-grid" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="cluster-card loading">
              <div className="skeleton skeleton-badge" />
              <div className="skeleton skeleton-text skeleton-text-lg" />
              <div className="skeleton skeleton-text skeleton-text-sm" />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <p className="story-clusters-empty" role="status">
          Clustering is unavailable right now — {error}
        </p>
      )}

      {!loading && !error && clusters.length === 0 && (
        <p className="story-clusters-empty" role="status">
          No multi-outlet stories in this window yet.
        </p>
      )}

      {!loading && !error && clusters.length > 0 && (
        <div className="story-clusters-grid">
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.key} cluster={cluster} onOpen={onOpenCluster} />
          ))}
        </div>
      )}

      {disclaimer && <p className="story-clusters-note">{disclaimer}</p>}
    </section>
  );
}
