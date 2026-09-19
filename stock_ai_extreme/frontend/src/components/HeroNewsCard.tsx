/**
 * Phase 8 — Hero News Card Component
 *
 * The desk's lead story. Ranked by the backend's computed impact score rather
 * than by "newest with a picture", so the most consequential recent story is
 * the hero even when a routine wire item landed five minutes later.
 */

import { NewsArticle } from "../lib/newsService";
import { formatRelativeTime } from "../utils/dateFormat";
import BaseBadge from "./BaseBadge";
import SafeImage from "./SafeImage";
import {
  NewsEventBadge,
  NewsFreshness,
  NewsImpactBadge,
  NewsKeywordChips,
  NewsPriorityBadge,
  NewsSentiment,
  NewsTickerLinks,
} from "./NewsMeta";

interface HeroNewsCardProps {
  article: NewsArticle | null;
  loading?: boolean;
  /** Shown when the desk is reachable but genuinely has no lead story. */
  emptyReason?: string | null;
}

export default function HeroNewsCard({ article, loading, emptyReason }: HeroNewsCardProps) {
  if (loading) {
    return (
      <article className="hero-news-card loading" aria-label="Loading featured news">
        <div className="hero-news-image skeleton" />
        <div className="hero-news-content">
          <div className="hero-news-meta">
            <div className="skeleton skeleton-badge" />
            <div className="skeleton skeleton-text skeleton-text-sm" />
          </div>
          <div className="skeleton skeleton-text skeleton-text-xl" />
          <div className="skeleton skeleton-text skeleton-text-lg" />
          <div className="skeleton skeleton-text skeleton-text-md" />
        </div>
      </article>
    );
  }

  if (!article) {
    return (
      <article className="hero-news-card empty" aria-label="No featured news available">
        <div className="hero-news-empty">
          <svg
            className="hero-news-empty-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"
            />
          </svg>
          <p>No featured news available</p>
          <small>
            {emptyReason ??
              "The desk has no lead story in the recent window — refresh to ingest the latest feeds."}
          </small>
        </div>
      </article>
    );
  }

  const getCategoryVariant = (category: string): "default" | "success" | "warning" | "danger" | "info" => {
    switch (category.toUpperCase()) {
      case "PSX":
      case "STOCKS":
        return "success";
      case "BANKING":
      case "ECONOMY":
        return "info";
      case "REGULATION":
        return "warning";
      case "FOREX":
      case "COMMODITIES":
        return "default";
      default:
        return "default";
    }
  };

  return (
    <article className="hero-news-card" aria-labelledby="hero-news-title">
      <div className="hero-news-image-container">
        <SafeImage
          src={article.image_url}
          alt={article.title}
          className="hero-news-image"
          wrapperClassName="hero-news-image-wrapper"
          aspectRatio="16 / 9"
          loading="eager"
          fallbackLabel="No image published"
        />
        <div className="hero-news-overlay" />
      </div>

      <div className="hero-news-content">
        <div className="hero-news-meta">
          <BaseBadge variant={getCategoryVariant(article.category)}>
            {article.category}
          </BaseBadge>

          <NewsEventBadge article={article} />
          <NewsPriorityBadge article={article} />
          <NewsImpactBadge article={article} />
          <NewsFreshness article={article} />
          <NewsSentiment article={article} />

          <span className="hero-news-time">
            {formatRelativeTime(article.published_at)}
          </span>
        </div>

        <h2 id="hero-news-title" className="hero-news-title">
          {article.title}
        </h2>

        {article.excerpt && (
          <p className="hero-news-excerpt">{article.excerpt}</p>
        )}

        <NewsKeywordChips keywords={article.keywords} limit={6} />

        <div className="hero-news-footer">
          <div className="hero-news-publisher">
            {article.publisher && (
              <>
                <svg
                  className="hero-news-publisher-icon"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"
                  />
                </svg>
                <span>{article.publisher}</span>
              </>
            )}
            
            {article.author && (
              <>
                <span className="hero-news-separator">·</span>
                <span>by {article.author}</span>
              </>
            )}
          </div>

          <a
            href={article.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hero-news-link"
            aria-label={`Read full article: ${article.title}`}
          >
            Read article
            <svg
              className="hero-news-link-icon"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              />
            </svg>
          </a>
        </div>

        <NewsTickerLinks symbols={article.related_symbols} limit={5} className="hero-news-tickers" />
      </div>
    </article>
  );
}

// `useState` is no longer needed here — SafeImage owns the image error state now.
