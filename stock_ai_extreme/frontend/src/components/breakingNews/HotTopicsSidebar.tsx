/**
 * Phase 17 (spec §11) — HOT TOPICS sidebar.
 *
 * Topics are ranked strictly by the stored trend score, which is derived from
 * measurable activity: mention counts, article velocity, source spread and
 * recency, plus related forecast/market activity where the backend could obtain
 * it. No monetary "volume today" figure is ever displayed because no data source
 * in this stack supplies one.
 */
import { Link } from "react-router-dom";
import { Flame, RefreshCw, TrendingUp } from "lucide-react";
import type { NewsTopic } from "../../lib/breakingNews";
import TopicCard from "./TopicCard";

interface Props {
  topics: NewsTopic[];
  loading?: boolean;
  error?: string | null;
  meta?: Record<string, unknown> | null;
  onRefresh?: () => void;
  limit?: number;
}

export default function HotTopicsSidebar({ topics, loading = false, error = null, meta, onRefresh, limit }: Props) {
  const visible = typeof limit === "number" ? topics.slice(0, limit) : topics;

  return (
    <section className="bn-card bn-hot-topics" aria-live="polite">
      <header className="bn-card-head">
        <h3>
          <Flame size={15} aria-hidden /> Hot topics
        </h3>
        {onRefresh && (
          <button type="button" className="bn-ghost-btn" onClick={onRefresh} disabled={loading}>
            <RefreshCw size={12} className={loading ? "bn-spin" : undefined} aria-hidden />
            Refresh
          </button>
        )}
      </header>

      {loading && <p className="bn-muted">Loading ranked topics…</p>}
      {error && <p className="bn-warning">{error}</p>}

      {!loading && !error && visible.length === 0 && (
        <p className="bn-muted">
          No topics have activity in the current window. Topics appear only after real articles land — run an
          ingest to populate the desk.
        </p>
      )}

      <ol className="bn-topic-list">
        {visible.map((topic, index) => (
          <li key={topic.id}>
            <TopicCard topic={topic} rank={index + 1} variant="compact" />
          </li>
        ))}
      </ol>

      {meta && typeof meta["latest_seen"] === "string" && (
        <p className="bn-note">Window last updated {String(meta["latest_seen"])}</p>
      )}

      <Link className="bn-link bn-hot-all" to="/breaking-news?view=topics">
        <TrendingUp size={12} aria-hidden /> See every ranked topic
      </Link>
    </section>
  );
}
