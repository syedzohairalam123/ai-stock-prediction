/**
 * Phase 17 (spec §14) — `/topics/:topicId`.
 *
 * A topic's detail view is assembled entirely from stored observations:
 *
 * * the topic row itself (trend score with its components and weights),
 * * the hourly timeline the topic engine wrote,
 * * the real articles that mention it,
 * * the market impact rows previously measured for those articles,
 * * the publishers that carried them.
 *
 * An empty section means "no stored observation", and it says so rather than
 * filling the gap with generated content.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Building2,
  Newspaper,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import ImpactSparkline from "../components/breakingNews/ImpactSparkline";
import NewsImpactCard from "../components/breakingNews/NewsImpactCard";
import TopicTimeline from "../components/breakingNews/TopicTimeline";
import {
  directionClass,
  fetchTopicDetail,
  fixed,
  formatDateTime,
  magnitudeClass,
  rankedComponents,
  signed,
  timeAgo,
  type TopicArticle,
  type TopicDetail,
} from "../lib/breakingNews";

export default function TopicDetailPage() {
  const { topicId } = useParams<{ topicId: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<TopicDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [impactArticle, setImpactArticle] = useState<TopicArticle | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    try {
      setDetail(await fetchTopicDetail(id, { hours: 168, limit: 80 }));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load this topic");
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (topicId) void load(topicId);
  }, [topicId, load]);

  const topic = detail?.topic ?? null;
  const breakdown = useMemo(
    () => rankedComponents(topic?.trend_components, topic?.trend_weights),
    [topic?.trend_components, topic?.trend_weights],
  );

  const movementByArticle = useMemo(() => {
    const map = new Map<number, TopicDetail["impact_events"]>();
    (detail?.impact_events ?? []).forEach((impact) => {
      if (impact.article_id === null) return;
      const list = map.get(impact.article_id) ?? [];
      list.push(impact);
      map.set(impact.article_id, list);
    });
    return map;
  }, [detail?.impact_events]);

  if (loading) return <p className="bn-muted">Loading topic…</p>;

  if (error || !topic) {
    return (
      <div className="bn-empty">
        <AlertTriangle size={22} aria-hidden />
        <p>{error ?? "Topic not found."}</p>
        <button type="button" className="bn-btn" onClick={() => navigate("/breaking-news?view=topics")}>
          <ArrowLeft size={12} aria-hidden /> Back to ranked topics
        </button>
      </div>
    );
  }

  const rising = topic.trend_direction === "RISING";
  const falling = topic.trend_direction === "FALLING";

  return (
    <div className="bn-page">
      <header className="bn-topic-hero">
        <div>
          <Link className="bn-link" to="/breaking-news?view=topics">
            <ArrowLeft size={12} aria-hidden /> All topics
          </Link>
          <h1>{topic.topic_name}</h1>
          <div className="bn-topic-meta">
            <span className={`bn-dir ${directionClass(topic.trend_direction)}`}>
              {rising ? <TrendingUp size={12} aria-hidden /> : falling ? <TrendingDown size={12} aria-hidden /> : null}
              {topic.trend_direction}
            </span>
            <span>{topic.topic_type.toLowerCase()} topic</span>
            {topic.category && <span>{topic.category}</span>}
            <span>first seen {formatDateTime(topic.first_seen)}</span>
            <span>last seen {formatDateTime(topic.last_seen)}</span>
          </div>
        </div>
        <div className="bn-topic-hero-score">
          <span className="bn-topic-score-v">{fixed(topic.trend_score, 1)}</span>
          <span className="bn-k">trend score</span>
          <button type="button" className="bn-ghost-btn" onClick={() => void load(topic.id)}>
            <RefreshCw size={12} aria-hidden /> Reload
          </button>
        </div>
      </header>

      <div className="bn-stat-row">
        <div className="bn-stat">
          <span className="bn-k">Mentions</span>
          <span className="bn-stat-v">{topic.mention_count}</span>
        </div>
        <div className="bn-stat">
          <span className="bn-k">Articles</span>
          <span className="bn-stat-v">{topic.article_count}</span>
        </div>
        <div className="bn-stat">
          <span className="bn-k">Sources</span>
          <span className="bn-stat-v">{topic.source_count}</span>
        </div>
        <div className="bn-stat">
          <span className="bn-k">Velocity</span>
          <span className="bn-stat-v">{topic.article_velocity === null ? "n/a" : `${fixed(topic.article_velocity, 2)}/h`}</span>
        </div>
        <div className="bn-stat">
          <span className="bn-k">Recency</span>
          <span className="bn-stat-v">{topic.recency_score === null ? "n/a" : fixed(topic.recency_score, 2)}</span>
        </div>
        <div className="bn-stat">
          <span className="bn-k">Related activity</span>
          <span className="bn-stat-v">{topic.related_activity === null ? "n/a" : fixed(topic.related_activity, 2)}</span>
        </div>
      </div>

      <div className="bn-layout">
        <div className="bn-layout-main">
          <TopicTimeline points={detail?.timeline ?? []} loading={false} metric="mention_count" />

          <section className="bn-card">
            <header className="bn-card-head">
              <h3>
                <Newspaper size={15} aria-hidden /> Related articles
              </h3>
              <span className="bn-muted">{detail?.articles.length ?? 0} stored articles</span>
            </header>
            {(detail?.articles.length ?? 0) === 0 && (
              <p className="bn-muted">No stored articles reference this topic in the selected window.</p>
            )}
            <ul className="bn-article-list">
              {(detail?.articles ?? []).map((article) => (
                <li key={article.id}>
                  <a href={article.url} target="_blank" rel="noopener noreferrer">
                    {article.title}
                  </a>
                  <div className="bn-item-meta">
                    <span>{article.publisher ?? "publisher unavailable"}</span>
                    <span title={formatDateTime(article.published_at)}>{timeAgo(article.published_at)}</span>
                    {article.event_type && <span>{article.event_type}</span>}
                    {article.impact_score !== null && <span>impact score {fixed(article.impact_score, 1)}</span>}
                    <span className="bn-mode">{article.data_mode}</span>
                  </div>
                  {article.symbols.length > 0 && (
                    <div className="bn-chip-row">
                      {article.symbols.slice(0, 8).map((symbol) => (
                        <Link key={symbol} className="bn-chip" to={`/stock/${symbol}`}>
                          {symbol}
                        </Link>
                      ))}
                    </div>
                  )}
                  <button type="button" className="bn-ghost-btn" onClick={() => setImpactArticle(article)}>
                    <BarChart3 size={11} aria-hidden /> Measure market impact for this article
                  </button>
                  {(movementByArticle.get(article.id) ?? []).map((impact) => (
                    <div className="bn-impact-inline" key={`${impact.id ?? impact.entity}-${impact.observation_window}`}>
                      <div className="bn-item-meta">
                        <span>{impact.entity}</span>
                        <span className={`bn-badge ${magnitudeClass(impact.impact_magnitude)}`}>
                          {impact.impact_magnitude}
                        </span>
                        <span>{impact.observation_window} window</span>
                        <span className={((impact.price_change_percent ?? 0) >= 0 ? "bn-pos" : "bn-neg")}>
                          {signed(impact.price_change_percent, 3, "%")}
                        </span>
                        {impact.window_available === false && <span className="bn-muted">window unavailable</span>}
                      </div>
                      <ImpactSparkline
                        points={impact.series}
                        publishedAt={impact.news_published_at}
                        width={280}
                        height={64}
                        ariaLabel={`${impact.entity} observed bars for article ${article.id}`}
                      />
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          </section>

          {impactArticle && (
            <section className="bn-card">
              <header className="bn-card-head">
                <h3>
                  <BarChart3 size={15} aria-hidden /> Impact: {impactArticle.title}
                </h3>
                <button type="button" className="bn-ghost-btn" onClick={() => setImpactArticle(null)}>
                  Close
                </button>
              </header>
              <NewsImpactCard
                newsId={null}
                articleId={impactArticle.id}
                entity={impactArticle.symbols[0] ?? topic.related_stocks[0] ?? ""}
                publishedAt={impactArticle.published_at ?? topic.last_seen ?? new Date().toISOString()}
                title={impactArticle.title}
              />
            </section>
          )}
        </div>

        <aside className="bn-layout-side">
          <section className="bn-card">
            <header className="bn-card-head">
              <h3>
                <BarChart3 size={15} aria-hidden /> Trend score composition
              </h3>
            </header>
            {breakdown.length === 0 ? (
              <p className="bn-muted">No stored component breakdown for this topic.</p>
            ) : (
              <table className="bn-table">
                <thead>
                  <tr>
                    <th scope="col">Component</th>
                    <th scope="col">Value</th>
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
            )}
          </section>

          <section className="bn-card">
            <header className="bn-card-head">
              <h3>Related instruments</h3>
            </header>
            {topic.related_stocks.length === 0 && topic.related_indices.length === 0 && (
              <p className="bn-muted">No priceable instrument was associated with this topic.</p>
            )}
            <div className="bn-chip-row">
              {topic.related_stocks.map((symbol) => (
                <Link key={symbol} className="bn-chip" to={`/stock/${symbol}`}>
                  {symbol}
                </Link>
              ))}
              {topic.related_indices.map((symbol) => (
                <span key={symbol} className="bn-chip bn-chip-index">
                  {symbol}
                </span>
              ))}
            </div>
            {topic.related_entities.length > 0 && (
              <p className="bn-note">Also extracted: {topic.related_entities.slice(0, 12).join(", ")}</p>
            )}
          </section>

          <section className="bn-card">
            <header className="bn-card-head">
              <h3>
                <Building2 size={15} aria-hidden /> Source list
              </h3>
              <span className="bn-muted">{detail?.sources.length ?? 0} publishers</span>
            </header>
            {(detail?.sources.length ?? 0) === 0 ? (
              <p className="bn-muted">No publishers recorded for this topic.</p>
            ) : (
              <ul className="bn-plain-list">
                {(detail?.sources ?? []).map((publisher) => (
                  <li key={publisher}>{publisher}</li>
                ))}
              </ul>
            )}
          </section>

          <section className="bn-card">
            <header className="bn-card-head">
              <h3>Observed market movement</h3>
              <span className="bn-muted">{detail?.impact_events.length ?? 0} rows</span>
            </header>
            {(detail?.impact_events.length ?? 0) === 0 ? (
              <p className="bn-muted">
                No market impact has been measured for this topic's articles yet. Impact rows are written only when real
                bars exist on both sides of publication.
              </p>
            ) : (
              <ul className="bn-plain-list">
                {(detail?.impact_events ?? []).slice(0, 12).map((impact) => (
                  <li key={`${impact.id ?? impact.entity}-${impact.observation_window}`}>
                    <span>
                      {impact.entity} · {impact.observation_window}
                    </span>
                    <span className={(impact.price_change_percent ?? 0) >= 0 ? "bn-pos" : "bn-neg"}>
                      {signed(impact.price_change_percent, 3, "%")}
                    </span>
                    <span className="bn-muted">{impact.notes}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="bn-note">Price movement observed after publication. Correlation does not imply causation.</p>
          </section>
        </aside>
      </div>

      {detail && (
        <footer className="bn-footnote">
          <p className="bn-muted">
            Detail generated {formatDateTime(detail.generated_at)} · topic id {topic.id}
          </p>
        </footer>
      )}
    </div>
  );
}
