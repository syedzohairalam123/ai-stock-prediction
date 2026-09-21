/**
 * Phase 17 (spec §14) — topic timeline.
 *
 * Each row is a stored observation bucket: how many mentions/articles/sources
 * the topic accumulated in that window, from real articles. Bar widths are
 * relative to the busiest bucket in the same series, so a quiet topic is
 * visibly quiet rather than normalised into looking busy.
 */
import { useMemo } from "react";
import { Clock } from "lucide-react";
import { fixed, formatDateTime, type TopicTimelinePoint } from "../../lib/breakingNews";

interface Props {
  points: TopicTimelinePoint[];
  loading?: boolean;
  /** Metric driving the bar width. */
  metric?: "mention_count" | "article_count" | "source_count";
  limit?: number;
}

const METRIC_LABELS: Record<string, string> = {
  mention_count: "mentions",
  article_count: "articles",
  source_count: "sources",
};

export default function TopicTimeline({ points, loading = false, metric = "mention_count", limit = 48 }: Props) {
  const series = useMemo(
    () =>
      [...points]
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
        .slice(-limit),
    [points, limit],
  );

  const max = useMemo(
    () => series.reduce((acc, point) => Math.max(acc, Number(point[metric] ?? 0)), 0),
    [series, metric],
  );

  return (
    <section className="bn-card">
      <header className="bn-card-head">
        <h3>
          <Clock size={15} aria-hidden /> Activity timeline
        </h3>
        <span className="bn-muted">{METRIC_LABELS[metric]} per stored bucket</span>
      </header>

      {loading && <p className="bn-muted">Loading timeline…</p>}
      {!loading && series.length === 0 && (
        <p className="bn-muted">
          No stored timeline points for this topic yet. Points are written when an ingest observes the topic, so an
          empty timeline means the topic has not been seen recently — not that it is quiet.
        </p>
      )}

      {series.length > 0 && (
        <div className="bn-timeline">
          {series.map((point) => {
            const value = Number(point[metric] ?? 0);
            const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
            return (
              <div className="bn-timeline-row" key={point.id}>
                <span className="bn-timeline-time" title={formatDateTime(point.timestamp)}>
                  {formatDateTime(point.timestamp)}
                </span>
                <span className="bn-timeline-bar" aria-hidden>
                  <span
                    className="bn-timeline-fill"
                    style={{ width: `${width}%` }}
                    data-direction={point.trend_score !== null ? undefined : "unknown"}
                  />
                </span>
                <span className="bn-timeline-value">
                  {value} {METRIC_LABELS[metric]}
                </span>
                <span className="bn-timeline-side">
                  {point.article_count} articles · {point.source_count} sources
                  {point.trend_score !== null && <> · score {fixed(point.trend_score, 1)}</>}
                  {point.related_activity !== null && <> · related {fixed(point.related_activity, 2)}</>}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
