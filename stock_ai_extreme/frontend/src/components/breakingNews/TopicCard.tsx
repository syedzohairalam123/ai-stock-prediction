/**
 * Phase 17 (spec §11, §13) — one hot topic, with its maths shown.
 *
 * The trend score is a weighted blend of measurable activity (mention velocity,
 * source count, recency, related activity). The weights come from the backend so
 * this card can display exactly how the number was produced — a ranking nobody
 * can reproduce is a ranking nobody should trust.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, TrendingDown, TrendingUp } from "lucide-react";
import { directionClass, fixed, rankedComponents, type NewsTopic } from "../../lib/breakingNews";

interface Props {
  topic: NewsTopic;
  rank?: number;
  /** `compact` is used inside the hot-topics sidebar. */
  variant?: "compact" | "full";
}

export default function TopicCard({ topic, rank, variant = "compact" }: Props) {
  const [open, setOpen] = useState(false);
  const breakdown = rankedComponents(topic.trend_components, topic.trend_weights);
  const rising = topic.trend_direction === "RISING";
  const falling = topic.trend_direction === "FALLING";

  const href = `/topics/${encodeURIComponent(topic.id)}`;

  return (
    <article className={`bn-topic bn-topic-${variant}`}>
      <div className="bn-topic-row">
        {rank !== undefined && <span className="bn-topic-rank">{rank}</span>}
        <div className="bn-topic-main">
          <Link to={href} className="bn-topic-name">
            {topic.topic_name}
          </Link>
          <div className="bn-topic-meta">
            <span className={`bn-dir ${directionClass(topic.trend_direction)}`}>
              {rising ? <TrendingUp size={12} aria-hidden /> : falling ? <TrendingDown size={12} aria-hidden /> : null}
              {topic.trend_direction}
            </span>
            <span>{topic.mention_count} mentions</span>
            <span>{topic.source_count} sources</span>
            {topic.topic_type && <span>{topic.topic_type.toLowerCase()}</span>}
          </div>
          {variant === "full" && (
            <>
              <div className="bn-topic-meta">
                <span>{topic.article_count} articles</span>
                {topic.article_velocity !== null && <span>{fixed(topic.article_velocity, 2)} articles/hr</span>}
                {topic.recency_score !== null && <span>recency {fixed(topic.recency_score, 2)}</span>}
                {topic.related_activity !== null && <span>related activity {fixed(topic.related_activity, 2)}</span>}
              </div>
              {(topic.related_stocks.length > 0 || topic.related_indices.length > 0) && (
                <div className="bn-chip-row">
                  {topic.related_stocks.slice(0, 8).map((symbol) => (
                    <Link key={symbol} to={`/stock/${symbol}`} className="bn-chip">
                      {symbol}
                    </Link>
                  ))}
                  {topic.related_indices.slice(0, 6).map((symbol) => (
                    <span key={symbol} className="bn-chip bn-chip-index">
                      {symbol}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="bn-topic-score">
          <span className="bn-topic-score-v">{fixed(topic.trend_score, 1)}</span>
          <button
            type="button"
            className="bn-topic-toggle"
            aria-expanded={open}
            aria-label={open ? "Hide trend breakdown" : "Show trend breakdown"}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
          </button>
        </div>
      </div>

      {open && (
        <div className="bn-breakdown">
          {breakdown.length === 0 ? (
            <p className="bn-muted">
              No component breakdown was recorded for this topic — only the stored trend score is available.
            </p>
          ) : (
            <>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Component</th>
                    <th scope="col">Weighted value</th>
                    <th scope="col">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.map((row) => (
                    <tr key={row.key}>
                      <td>{row.label}</td>
                      <td>{fixed(row.contribution, 3)}</td>
                      <td>{row.weight === null ? "—" : fixed(row.weight, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="bn-note">
                Score is the weighted sum of the components above; weights are configured on the backend and
                returned with every topic so the ranking can be reproduced.
              </p>
            </>
          )}
          {topic.last_seen && <p className="bn-note">Last seen {topic.last_seen}</p>}
          <Link className="bn-link" to={href}>
            Open topic detail →
          </Link>
        </div>
      )}
    </article>
  );
}
