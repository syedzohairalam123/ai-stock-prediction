/**
 * Phase 8 — Trending Strip
 *
 * "What the market is being talked about most right now."
 *
 * The ranking comes from the backend's time-decayed mention counts, so a topic
 * with six mentions this morning outranks one with forty last week. The strip
 * shows the window and the number of articles it was computed from, because a
 * ranking with no visible basis is not much better than a guess.
 *
 * A ticker term links to its stock page only when it is a real symbol; indices
 * and topics are shown as plain filters that re-run the search.
 */

import { Link } from "react-router-dom";
import { TrendingEntity, dataModeMeta, isLinkableSymbol } from "../lib/newsService";
import BaseBadge from "./BaseBadge";

interface TrendingStripProps {
  entities: TrendingEntity[];
  loading?: boolean;
  error?: string | null;
  windowHours: number;
  articlesConsidered?: number;
  onSelectTopic?: (topic: string) => void;
}

function TrendItem({
  entity,
  onSelectTopic,
}: {
  entity: TrendingEntity;
  onSelectTopic?: (topic: string) => void;
}) {
  const sentiment = entity.avg_sentiment;
  const sentimentLabel =
    sentiment === null || sentiment === undefined
      ? null
      : sentiment > 0.15
        ? "bullish"
        : sentiment < -0.15
          ? "bearish"
          : "neutral";

  const body = (
    <>
      <span className="trending-item-value">{entity.label || entity.value}</span>
      <span className="trending-item-count">
        <span aria-hidden="true">×</span>
        {entity.count}
        <span className="sr-only"> mentions</span>
      </span>
      {sentimentLabel && (
        <span className={`trending-item-sentiment news-sentiment-${sentimentLabel}`}>
          <span aria-hidden="true">
            {sentimentLabel === "bullish" ? "▲" : sentimentLabel === "bearish" ? "▼" : "◆"}
          </span>
          <span className="sr-only">{sentimentLabel}</span>
        </span>
      )}
    </>
  );

  if (entity.type === "SYMBOL" && isLinkableSymbol(entity.value)) {
    return (
      <Link
        to={`/stock/${encodeURIComponent(entity.value)}`}
        className="trending-item trending-item-symbol"
        aria-label={`${entity.value}: ${entity.count} mentions, view stock`}
      >
        {body}
      </Link>
    );
  }

  if (onSelectTopic) {
    return (
      <button
        type="button"
        className="trending-item trending-item-topic"
        onClick={() => onSelectTopic(entity.label || entity.value)}
        aria-label={`Filter news by ${entity.label || entity.value}`}
      >
        {body}
      </button>
    );
  }

  return <span className="trending-item">{body}</span>;
}

export default function TrendingStrip({
  entities,
  loading,
  error,
  windowHours,
  articlesConsidered,
  onSelectTopic,
}: TrendingStripProps) {
  const horizon = windowHours % 24 === 0 ? `${windowHours / 24}d` : `${windowHours}h`;

  return (
    <section className="trending-strip" aria-labelledby="trending-heading" aria-live="polite">
      <header className="trending-strip-head">
        <h2 id="trending-heading" className="trending-strip-title">
          <span aria-hidden="true">📈</span> Trending
        </h2>
        <p className="trending-strip-sub">
          Time-decayed mentions over the last {horizon}
          {typeof articlesConsidered === "number" && articlesConsidered > 0
            ? ` · from ${articlesConsidered} articles`
            : ""}
        </p>
      </header>

      {loading && (
        <div className="trending-strip-track" aria-busy="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="skeleton trending-item-skeleton" />
          ))}
        </div>
      )}

      {!loading && error && (
        <p className="trending-strip-empty" role="status">
          Trending is unavailable right now — {error}
        </p>
      )}

      {!loading && !error && entities.length === 0 && (
        <p className="trending-strip-empty" role="status">
          No entities have been tracked in this window yet. Refresh the desk to
          ingest the latest feeds.
        </p>
      )}

      {!loading && !error && entities.length > 0 && (
        <div className="trending-strip-track">
          {entities.map((entity) => (
            <TrendItem
              key={`${entity.type}:${entity.value}`}
              entity={entity}
              onSelectTopic={onSelectTopic}
            />
          ))}
        </div>
      )}

      {!loading && !error && entities.length > 0 && (
        <p className="trending-strip-note">
          Counts are decayed by recency (half-life {Math.max(1, Math.round(windowHours / 3))}h);
          sentiment is the lexicon mean across those mentions.
        </p>
      )}

      {/* Keeps the freshness vocabulary in one place: the strip explains the
          same LIVE/RECENT labels the article cards use. */}
      <p className="sr-only">
        Article freshness uses: {Object.entries({
          LIVE: dataModeMeta("LIVE").label,
          RECENT: dataModeMeta("RECENT").label,
          STALE: dataModeMeta("STALE").label,
        }).map(([key, label]) => `${key} = ${label}`).join(", ")}.
      </p>
      <BaseBadge variant="info" size="sm" className="sr-only">
        {entities.length} trending terms
      </BaseBadge>
    </section>
  );
}
