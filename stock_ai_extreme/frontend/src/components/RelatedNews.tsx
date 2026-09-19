/**
 * Phase 8 — Related News (spec I)
 *
 * News for one stock symbol, rendered on the stock detail page.
 *
 * The backend searches the stored corpus first and, when it has nothing for the
 * ticker, asks the publisher's own feed for that company and stores what comes
 * back (see `GET /api/news/by-symbol/{symbol}`). The response says which path
 * was taken, and this component shows it — "fetched live from publisher feeds"
 * is a different claim from "from the desk archive", and the reader deserves to
 * know which one they are looking at.
 *
 * Every state is explicit: skeleton while loading, a real message on error with
 * a retry, and — crucially — a *stated* empty state rather than silently
 * rendering nothing, which is how a broken panel hides as "no news".
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { NewsService, NewsArticle } from "../lib/newsService";
import { formatRelativeTime } from "../utils/dateFormat";
import BaseBadge from "./BaseBadge";
import SafeImage from "./SafeImage";
import { NewsEventBadge, NewsFreshness, NewsImpactBadge, NewsSentiment } from "./NewsMeta";

interface RelatedNewsProps {
  symbol: string;
  limit?: number;
}

interface Aggregate {
  count: number;
  bullish: number;
  bearish: number;
  neutral: number;
  avg_impact: number | null;
}

export default function RelatedNews({ symbol, limit = 5 }: RelatedNewsProps) {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [aggregate, setAggregate] = useState<Aggregate | null>(null);
  const [liveFallback, setLiveFallback] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ignore a response that arrives after the symbol changed — the stock page
  // reuses this component across navigations.
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      setLoading(true);
      setError(null);
      const response = await NewsService.getNewsBySymbol(symbol, limit);
      if (id !== requestId.current) return;
      setArticles(response.items ?? []);
      setAggregate(response.sentiment_aggregate ?? null);
      setLiveFallback(Boolean(response.live_fallback_used));
    } catch (err) {
      if (id !== requestId.current) return;
      console.error("Failed to load related news:", err);
      setError("Related news could not be loaded.");
      setArticles([]);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [symbol, limit]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="related-news" aria-labelledby="related-news-title">
      <header className="related-news-head">
        <h2 id="related-news-title" className="related-news-title">
          <span aria-hidden="true">📰</span> News for {symbol}
        </h2>

        <div className="related-news-meta">
          {liveFallback && (
            <BaseBadge variant="info" size="sm">
              fetched live from publisher feeds
            </BaseBadge>
          )}
          {aggregate && aggregate.count > 0 && (
            <BaseBadge variant="default" size="sm">
              {aggregate.bullish} bullish · {aggregate.bearish} bearish · {aggregate.neutral} neutral
            </BaseBadge>
          )}
          {aggregate?.avg_impact != null && (
            <BaseBadge variant="default" size="sm">
              avg impact {aggregate.avg_impact}
            </BaseBadge>
          )}
        </div>
      </header>

      {loading && (
        <div className="related-news-list" aria-busy="true">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="related-news-item loading">
              <div className="skeleton related-news-thumb" />
              <div className="related-news-content">
                <div className="skeleton skeleton-text skeleton-text-lg" />
                <div className="skeleton skeleton-text skeleton-text-sm" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="related-news-state" role="alert">
          <p>{error}</p>
          <button type="button" className="related-news-retry" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!loading && !error && articles.length === 0 && (
        <p className="related-news-state" role="status">
          No recent coverage found for {symbol} in the publisher feeds we read.
        </p>
      )}

      {!loading && !error && articles.length > 0 && (
        <ul className="related-news-list">
          {articles.map((article) => (
            <li key={article.id} className="related-news-item">
              <a
                href={article.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="related-news-link"
              >
                <SafeImage
                  src={article.image_url}
                  alt={article.title}
                  className="related-news-thumb"
                  wrapperClassName="related-news-thumb-wrapper"
                  aspectRatio="1 / 1"
                  fallbackLabel="No image"
                />

                <div className="related-news-content">
                  <div className="related-news-meta-row">
                    <NewsEventBadge article={article} />
                    <NewsImpactBadge article={article} />
                    <NewsFreshness article={article} />
                    <NewsSentiment article={article} />
                  </div>

                  <h3 className="related-news-title-text">
                    {article.title}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </h3>

                  <div className="related-news-footer">
                    {article.publisher && (
                      <span className="related-news-publisher">{article.publisher}</span>
                    )}
                    <span className="related-news-time">
                      {formatRelativeTime(article.published_at)}
                    </span>
                  </div>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}

      <a href={`/news?symbol=${encodeURIComponent(symbol)}`} className="related-news-view-all">
        View all {symbol} news
        <span aria-hidden="true"> →</span>
      </a>
    </section>
  );
}
