/**
 * Phase 8 — News Feed Component
 * 
 * Professional news feed with thumbnails, proper layout, pagination,
 * and performance optimization with lazy loading.
 */

import { memo } from "react";
import { Link } from "react-router-dom";
import { NewsArticle, isLinkableIndex } from "../lib/newsService";
import { formatRelativeTime } from "../utils/dateFormat";
import SafeImage from "./SafeImage";
import { NewsKeywordChips, NewsMetaRow, NewsTickerLinks } from "./NewsMeta";

interface NewsFeedProps {
  articles: NewsArticle[];
  loading?: boolean;
  onLoadMore?: () => void;
  hasMore?: boolean;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
}

/**
 * One feed row.
 *
 * Memoised because a feed of 20-100 rows re-renders on every keystroke while
 * the search box is debounced — without this, all of them re-render for a
 * change that only affects one.
 *
 * The structure is a `<article>` containing the headline as the single primary
 * link (not a whole-row anchor), which keeps the ticker links inside the row
 * actually clickable and stops a keyboard user tabbing through one giant
 * target per row.
 */
const NewsFeedItem = memo(function NewsFeedItem({ article }: { article: NewsArticle }) {
  return (
    <article className="news-feed-item">
      <div className="news-feed-thumbnail-container">
        <SafeImage
          src={article.image_url}
          alt={article.title}
          className="news-feed-thumbnail"
          wrapperClassName="news-feed-thumbnail-wrapper"
          aspectRatio="4 / 3"
          fallbackLabel="No image published"
        />
      </div>

      <div className="news-feed-content">
        <NewsMetaRow article={article} />

        <h3 className="news-feed-title">
          <a
            href={article.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="news-feed-title-link"
          >
            {article.title}
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </h3>

        {article.excerpt && <p className="news-feed-excerpt">{article.excerpt}</p>}

        <NewsKeywordChips keywords={article.keywords} limit={4} />

        <div className="news-feed-footer">
          {article.publisher && (
            <span className="news-feed-publisher">{article.publisher}</span>
          )}
          <span className="news-feed-time">{formatRelativeTime(article.published_at)}</span>

          <NewsTickerLinks symbols={article.related_symbols} limit={3} className="news-feed-tickers" />

          {article.related_indices && article.related_indices.length > 0 && (
            <span className="news-feed-indices">
              {article.related_indices.slice(0, 2).map((index) =>
                isLinkableIndex(index) ? (
                  <Link key={index} to={`/index/${index}`} className="news-feed-index-link">
                    {index}
                  </Link>
                ) : (
                  <span key={index} className="news-feed-index">
                    {index}
                  </span>
                ),
              )}
            </span>
          )}
        </div>
      </div>
    </article>
  );
});

function NewsFeedSkeleton() {
  return (
    <div className="news-feed-item loading">
      <div className="news-feed-thumbnail-container">
        <div className="skeleton news-feed-thumbnail" />
      </div>
      <div className="news-feed-content">
        <div className="news-feed-meta">
          <div className="skeleton skeleton-badge" />
          <div className="skeleton skeleton-text skeleton-text-xs" />
        </div>
        <div className="skeleton skeleton-text skeleton-text-lg" />
        <div className="skeleton skeleton-text skeleton-text-md" />
        <div className="skeleton skeleton-text skeleton-text-sm" />
      </div>
    </div>
  );
}

export default function NewsFeed({
  articles,
  loading,
  onLoadMore,
  hasMore,
  page = 1,
  totalPages = 1,
  onPageChange,
}: NewsFeedProps) {
  if (loading && articles.length === 0) {
    return (
      <div className="news-feed" role="feed" aria-busy="true" aria-label="Loading news feed">
        {Array.from({ length: 6 }).map((_, i) => (
          <NewsFeedSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (!loading && articles.length === 0) {
    return (
      <div className="news-feed-empty">
        <svg
          className="news-feed-empty-icon"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <p className="news-feed-empty-title">No news articles found</p>
        <p className="news-feed-empty-text">
          Try adjusting your filters or search terms
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="news-feed" role="feed" aria-label="News articles">
        {articles.map((article) => (
          <NewsFeedItem key={article.id} article={article} />
        ))}
      </div>

      {/* Pagination Controls */}
      {onPageChange && totalPages > 1 && (
        <div className="news-feed-pagination" role="navigation" aria-label="News pagination">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || loading}
            className="pagination-btn pagination-btn-prev"
            aria-label="Previous page"
          >
            <svg
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
            Previous
          </button>

          <div className="pagination-info">
            Page <span className="pagination-current">{page}</span> of{" "}
            <span className="pagination-total">{totalPages}</span>
          </div>

          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages || loading}
            className="pagination-btn pagination-btn-next"
            aria-label="Next page"
          >
            Next
            <svg
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>
        </div>
      )}

      {/* Infinite Scroll Load More */}
      {onLoadMore && hasMore && !onPageChange && (
        <div className="news-feed-load-more">
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="load-more-btn"
            aria-label="Load more articles"
          >
            {loading ? (
              <>
                <svg
                  className="load-more-spinner"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Loading...
              </>
            ) : (
              "Load more"
            )}
          </button>
        </div>
      )}
    </>
  );
}
