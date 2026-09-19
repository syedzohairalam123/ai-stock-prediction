/**
 * Phase 8 — shared news metadata pieces.
 *
 * Rendered by both the hero card and every feed item, so an article looks the
 * same wherever it appears. Everything here is presentation only: the values
 * come from the backend's analytics layer, and nothing is computed by guessing.
 *
 * Two rules are enforced in this file:
 *
 *  1. **Status is never colour-only.** Freshness and sentiment always carry a
 *     word, an arrow or a symbol as well as a colour class, so the information
 *     survives a colour-blind or monochrome rendering (spec S).
 *  2. **A ticker is only a link when it is real.** `isLinkableSymbol` checks the
 *     terminal's own stock universe, so an article never produces a link to a
 *     `/stock/...` page that cannot be priced (spec H).
 */

import { Link } from "react-router-dom";
import BaseBadge from "./BaseBadge";
import {
  NewsArticle,
  dataModeMeta,
  eventTypeMeta,
  impactBand,
  isLinkableSymbol,
} from "../lib/newsService";

/** Freshness chip computed from the publisher's own timestamp. */
export function NewsFreshness({ article }: { article: NewsArticle }) {
  const meta = dataModeMeta(article.data_mode);
  return (
    <BaseBadge variant={meta.variant} size="sm">
      <span aria-hidden="true">●</span> {meta.label}
    </BaseBadge>
  );
}

/** Event-type chip (Dividend, Earnings, M&A, ...). Renders nothing for GENERAL. */
export function NewsEventBadge({ article }: { article: NewsArticle }) {
  const meta = eventTypeMeta(article.event_type);
  if (!meta) return null;
  return (
    <BaseBadge variant={meta.variant} size="sm">
      {meta.label}
    </BaseBadge>
  );
}

/** Impact score chip with the numeric score so it is inspectable, not a vibe. */
export function NewsImpactBadge({ article }: { article: NewsArticle }) {
  const band = impactBand(article.impact_score);
  if (!band || article.impact_score == null) return null;
  return (
    <BaseBadge variant={band.variant} size="sm">
      <span className="sr-only">{band.label}: </span>
      {Math.round(article.impact_score)}
      <span aria-hidden="true">/100</span>
    </BaseBadge>
  );
}

/** Priority chip (HIGH / NORMAL / LOW) as produced by the ingest pipeline. */
export function NewsPriorityBadge({ article }: { article: NewsArticle }) {
  if (!article.priority || article.priority === "NORMAL") return null;
  return (
    <BaseBadge
      variant={article.priority === "HIGH" ? "danger" : "default"}
      size="sm"
    >
      {article.priority === "HIGH" ? "Breaking" : "Low priority"}
    </BaseBadge>
  );
}

/** Reading-time estimate, omitted when the article has no measured word count. */
export function NewsReadingTime({ article }: { article: NewsArticle }) {
  if (!article.reading_time_minutes) return null;
  return (
    <span className="news-reading-time">
      <span aria-hidden="true">⏱</span> {article.reading_time_minutes} min read
    </span>
  );
}

/** Sentiment shown as arrow + word, never colour alone. */
export function NewsSentiment({ article }: { article: NewsArticle }) {
  const label = article.sentiment?.label ?? "neutral";
  const icon = label === "bullish" ? "▲" : label === "bearish" ? "▼" : "◆";
  return (
    <span className={`news-sentiment news-sentiment-${label}`}>
      <span aria-hidden="true">{icon}</span> {label}
      <span className="sr-only"> sentiment</span>
    </span>
  );
}

/**
 * Validated ticker links.
 *
 * A symbol that the frontend stock universe does not recognise renders as inert
 * text with an explanatory title, instead of a link that leads nowhere.
 */
export function NewsTickerLinks({
  symbols,
  limit = 4,
  className = "",
}: {
  symbols: string[] | undefined;
  limit?: number;
  className?: string;
}) {
  const list = (symbols ?? []).slice(0, limit);
  if (list.length === 0) return null;

  return (
    <div className={`news-ticker-links ${className}`.trim()}>
      <span className="news-ticker-links-label">Related:</span>
      {list.map((symbol) =>
        isLinkableSymbol(symbol) ? (
          <Link
            key={symbol}
            to={`/stock/${encodeURIComponent(symbol)}`}
            className="news-ticker-link"
            aria-label={`View ${symbol} stock details`}
          >
            {symbol}
          </Link>
        ) : (
          <span
            key={symbol}
            className="news-ticker-link news-ticker-link-inert"
            title={`${symbol} is not in this terminal's stock universe`}
          >
            {symbol}
          </span>
        ),
      )}
    </div>
  );
}

/** Keywords / topics attached by the analytics layer. */
export function NewsKeywordChips({
  keywords,
  limit = 5,
}: {
  keywords: string[] | undefined;
  limit?: number;
}) {
  const list = (keywords ?? []).slice(0, limit);
  if (list.length === 0) return null;
  return (
    <div className="news-keyword-chips" aria-label="Article keywords">
      {list.map((keyword) => (
        <span key={keyword} className="news-keyword-chip">
          {keyword}
        </span>
      ))}
    </div>
  );
}

/** The standard one-line meta row used by feed items. */
export function NewsMetaRow({ article }: { article: NewsArticle }) {
  return (
    <div className="news-meta-row">
      <BaseBadge variant="default" size="sm">
        {article.category}
      </BaseBadge>
      <NewsEventBadge article={article} />
      <NewsImpactBadge article={article} />
      <NewsPriorityBadge article={article} />
      <NewsFreshness article={article} />
      <NewsSentiment article={article} />
      <NewsReadingTime article={article} />
    </div>
  );
}
