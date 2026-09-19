/**
 * Phase 8 — Professional News & Financial Intelligence Desk
 * 
 * Frontend service for news API communication with comprehensive TypeScript types.
 */

import axios from "./axios";
import { INDICES, getStockMeta } from "./psxMarket";

export interface NewsSentiment {
  score: number;
  label: "bullish" | "bearish" | "neutral";
}

/**
 * One validated entity attached to an article by the backend analytics layer.
 * `type` is SYMBOL | INDEX | TOPIC.
 */
export interface NewsEntity {
  type: "SYMBOL" | "INDEX" | "TOPIC" | string;
  value: string;
  label: string;
}

/**
 * Freshness of an article, computed by the backend from the *publisher's own*
 * timestamp — never from when we fetched it. The UI uses this to avoid ever
 * presenting an older story as breaking news.
 */
export type NewsDataMode = "LIVE" | "RECENT" | "STALE" | "UNKNOWN";

/**
 * Newsworthy-ness score computed from the article text.
 * `components` breaks the total down so the ranking is inspectable.
 */
export interface NewsImpactComponents {
  event: number;
  source: number;
  entities: number;
  signal: number;
  recency: number;
}

export interface NewsArticle {
  id: number;
  title: string;
  slug: string;
  publisher: string | null;
  author: string | null;
  published_at: string | null;
  image_url: string | null;
  excerpt: string | null;
  content?: string | null;
  category: string;
  tags: string[];
  related_symbols: string[];
  related_indices: string[];
  topics?: string[];
  keywords?: string[];
  entities?: NewsEntity[];
  event_type?: string | null;
  impact_score?: number | null;
  reading_time_minutes?: number | null;
  word_count?: number | null;
  source_url: string;
  source_type: string;
  priority: string;
  data_source: string;
  data_mode?: NewsDataMode;
  sentiment: NewsSentiment;
  /** Present only when the response was produced by a text search. */
  relevance_score?: number;
  created_at?: string;
  updated_at?: string;
  feed_key?: string | null;
}

export type NewsSortMode = "recent" | "impact" | "relevance";

export interface NewsFilters {
  category?: string;
  publisher?: string;
  symbol?: string;
  event_type?: string;
  priority?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
  sort?: NewsSortMode;
  min_impact?: number;
  page?: number;
  page_size?: number;
}

export interface NewsPagination {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface NewsSearchResponse {
  items: NewsArticle[];
  pagination: NewsPagination;
  sort: NewsSortMode;
  filters_applied: NewsFilters;
}

/* -------------------------------------------------------------------------- */
/* Intelligence layer types                                                    */
/* -------------------------------------------------------------------------- */

/** One time-decayed trending entity (ticker, index or topic). */
export interface TrendingEntity {
  type: "SYMBOL" | "INDEX" | "TOPIC" | string;
  value: string;
  label: string;
  count: number;
  trend_score: number;
  avg_sentiment: number | null;
  latest_mention: string | null;
}

export interface TrendingResponse {
  window_hours: number;
  half_life_hours: number;
  generated_at: string;
  entities: TrendingEntity[];
  articles_considered: number;
}

/** A set of articles judged to be the same underlying story. */
export interface StoryCluster {
  key: string;
  article_ids: number[];
  size: number;
  publishers: string[];
  symbols: string[];
  terms: string[];
  first_seen: string | null;
  last_seen: string | null;
  max_impact: number;
}

export interface NewsClustersResponse {
  clusters: StoryCluster[];
  count: number;
  multi_source_count: number;
  articles_analyzed: number;
  threshold: number;
  disclaimer: string;
}

/** Real per-feed health from the last ingest — not an assumption. */
export type NewsSourceStatus =
  | "OK"
  | "EMPTY"
  | "ERROR"
  | "DISABLED"
  | "NOT_FETCHED";

export interface NewsSourceHealth {
  key: string;
  name: string;
  region: string;
  url: string;
  status: NewsSourceStatus;
  http_status: number | null;
  items: number;
  error: string | null;
  fetched_at: string | null;
}

export interface NewsSourceRegistryEntry {
  key: string;
  name: string;
  region: string;
  url: string;
  category: string;
  source_type: string;
  enabled: boolean;
  note: string;
}

export interface NewsSourcesResponse {
  sources: NewsSourceHealth[];
  registry: NewsSourceRegistryEntry[];
  summary: {
    total_feeds: number;
    enabled_feeds: number;
    healthy_feeds: number;
    items_available: number;
    last_ingest_at: string | null;
    paid_sources_configured: string[];
  };
}

export interface NewsStatsResponse {
  window_hours: number;
  total_articles: number;
  articles_in_window: number;
  publishers: number;
  articles_with_symbols: number;
  avg_impact_score: number | null;
  newest_published_at: string | null;
  by_category: Record<string, number>;
  by_event_type: Record<string, number>;
  by_priority: Record<string, number>;
  by_data_mode: Record<string, number>;
  generated_at: string;
}

export interface NewsSymbolResponse {
  symbol: string;
  items: NewsArticle[];
  count: number;
  sentiment_aggregate?: {
    count: number;
    bullish: number;
    bearish: number;
    neutral: number;
    avg_impact: number | null;
  };
  /** True when the backend had to fetch this ticker's news live. */
  live_fallback_used?: boolean;
}

export interface NewsListResponse {
  items: NewsArticle[];
  count: number;
}

export interface NewsHeroResponse {
  hero: NewsArticle | null;
  /** Present only when there is no hero, explaining why (e.g. empty corpus). */
  reason?: string;
}

export interface NewsCategoryResponse {
  categories: Array<{
    name: string;
    count: number;
  }>;
}

export interface NewsPublisherResponse {
  publishers: string[];
}

export interface NewsRefreshResponse {
  success: boolean;
  articles_stored: number;
  total_articles: number;
  message: string;
  sources: NewsSourceHealth[];
  sources_ok: number;
  ingested_at: string;
}

/* -------------------------------------------------------------------------- */
/* Presentation helpers (pure functions — no fetching, no rendering)           */
/* -------------------------------------------------------------------------- */

/**
 * Backend base URL, resolved the same way `lib/axios` resolves it. An empty
 * value means "same origin", which is what a Vite/edge proxy serves.
 */
const API_BASE = import.meta.env.VITE_API_URL || "";

/**
 * Build the backend image-proxy URL for a publisher image.
 *
 * Used only as a *retry* after a direct load fails: several publisher CDNs
 * answer a cross-origin `<img>` with 403 while serving the identical bytes to a
 * server. The backend allowlists the hosts it will fetch, so an arbitrary URL
 * cannot be turned into a server-side request.
 */
export function proxiedImageUrl(src: string | null | undefined): string | null {
  if (!src || !src.startsWith("https://")) return null;
  return `${API_BASE}/api/news/image?url=${encodeURIComponent(src)}`;
}

/**
 * Whether a ticker can safely be linked to `/stock/:symbol`.
 *
 * Spec H forbids creating a link for an unknown/invalid symbol, so this checks
 * the symbol against the terminal's real stock universe. A symbol the backend
 * validated but the frontend universe does not know returns false — the article
 * then renders the ticker as plain text instead of a dead link.
 */
export function isLinkableSymbol(symbol: string | null | undefined): boolean {
  if (!symbol) return false;
  const upper = symbol.trim().toUpperCase();
  if (!/^[A-Z][A-Z0-9]{0,9}$/.test(upper)) return false;
  return Boolean(getStockMeta(upper));
}

/** Whether an index label can safely be linked to `/index/:symbol`. */
export function isLinkableIndex(symbol: string | null | undefined): boolean {
  if (!symbol) return false;
  const upper = symbol.trim().toUpperCase();
  return INDICES.some((index) => index.symbol === upper);
}

/** Human label + severity for a feed status. */
export function sourceStatusMeta(status: NewsSourceStatus): {
  label: string;
  variant: "success" | "warning" | "danger" | "default";
} {
  switch (status) {
    case "OK":
      return { label: "Live", variant: "success" };
    case "EMPTY":
      return { label: "No items", variant: "warning" };
    case "ERROR":
      return { label: "Failed", variant: "danger" };
    case "DISABLED":
      return { label: "Off", variant: "default" };
    default:
      return { label: "Not fetched", variant: "default" };
  }
}

/** Human label + severity for an article's freshness mode. */
export function dataModeMeta(mode: NewsDataMode | undefined): {
  label: string;
  variant: "success" | "warning" | "danger" | "default";
} {
  switch (mode) {
    case "LIVE":
      return { label: "Live", variant: "success" };
    case "RECENT":
      return { label: "Recent", variant: "warning" };
    case "STALE":
      return { label: "Older", variant: "default" };
    default:
      return { label: "Date unknown", variant: "default" };
  }
}

/** Human label for an event type, plus the badge variant to render it with. */
export function eventTypeMeta(eventType: string | null | undefined): {
  label: string;
  variant: "success" | "warning" | "danger" | "info" | "default";
} | null {
  if (!eventType || eventType === "GENERAL") return null;
  const map: Record<string, { label: string; variant: "success" | "warning" | "danger" | "info" | "default" }> = {
    DIVIDEND: { label: "Dividend", variant: "success" },
    EARNINGS: { label: "Earnings", variant: "info" },
    MERGER_ACQUISITION: { label: "M&A", variant: "warning" },
    RIGHT_ISSUE: { label: "Rights issue", variant: "info" },
    REGULATORY: { label: "Regulatory", variant: "warning" },
    CONTRACT_AWARD: { label: "Contract", variant: "info" },
    INSIDER: { label: "Insider", variant: "warning" },
    RATING: { label: "Rating", variant: "info" },
    CAPITAL_INCREASE: { label: "Capital", variant: "info" },
    MONETARY_POLICY: { label: "Monetary policy", variant: "warning" },
    MACRO_DATA: { label: "Macro data", variant: "default" },
    MGMT_CHANGE: { label: "Management", variant: "default" },
    LEGAL: { label: "Legal", variant: "danger" },
    MARKET_UPDATE: { label: "Market update", variant: "default" },
  };
  return map[eventType] ?? { label: eventType.replace(/_/g, " "), variant: "default" };
}

/** Impact score band, for showing a compact HIGH/MEDIUM/LOW style chip. */
export function impactBand(score: number | null | undefined): {
  label: string;
  variant: "success" | "warning" | "danger" | "default";
} | null {
  if (score === null || score === undefined) return null;
  if (score >= 65) return { label: "High impact", variant: "danger" };
  if (score >= 38) return { label: "Medium impact", variant: "warning" };
  return { label: "Low impact", variant: "default" };
}

/**
 * News service class for all news-related API calls
 */
class NewsServiceClass {
  /**
   * Refresh news from all sources (keyless publisher feeds + any keyed APIs).
   */
  async refreshNews(
    query: string = "Pakistan stock market",
    symbol: string = "",
    includeRss: boolean = true,
  ): Promise<NewsRefreshResponse> {
    const params = new URLSearchParams();
    if (query) params.append("query", query);
    if (symbol) params.append("symbol", symbol);
    params.append("include_rss", String(includeRss));

    const response = await axios.post<NewsRefreshResponse>(
      `/api/news/refresh?${params.toString()}`
    );
    return response.data;
  }

  /**
   * Search and filter news with pagination
   */
  async searchNews(filters: NewsFilters): Promise<NewsSearchResponse> {
    const response = await axios.post<NewsSearchResponse>("/api/news/search", filters);
    return response.data;
  }

  /**
   * Get latest news articles
   */
  async getLatestNews(limit: number = 20, category?: string): Promise<NewsListResponse> {
    const params = new URLSearchParams();
    params.append("limit", limit.toString());
    if (category) params.append("category", category);
    
    const response = await axios.get<NewsListResponse>(
      `/api/news/latest?${params.toString()}`
    );
    return response.data;
  }

  /**
   * Get hero/featured news article
   */
  async getHeroNews(): Promise<NewsHeroResponse> {
    const response = await axios.get<NewsHeroResponse>("/api/news/hero");
    return response.data;
  }

  /**
   * Get news by stock symbol
   */
  async getNewsBySymbol(symbol: string, limit: number = 10): Promise<NewsSymbolResponse> {
    const response = await axios.get<NewsSymbolResponse>(
      `/api/news/by-symbol/${symbol}?limit=${limit}`
    );
    return response.data;
  }

  /**
   * Get available news categories
   */
  async getCategories(): Promise<NewsCategoryResponse> {
    const response = await axios.get<NewsCategoryResponse>("/api/news/categories");
    return response.data;
  }

  /**
   * Get available publishers
   */
  async getPublishers(): Promise<NewsPublisherResponse> {
    const response = await axios.get<NewsPublisherResponse>("/api/news/publishers");
    return response.data;
  }

  /**
   * Get full article by ID
   */
  async getArticle(id: number): Promise<NewsArticle> {
    const response = await axios.get<NewsArticle>(`/api/news/${id}`);
    return response.data;
  }

  /**
   * Articles related to one article (shared entities + BM25 text similarity).
   */
  async getRelatedNews(articleId: number, limit: number = 6): Promise<{ article_id: number; items: NewsArticle[]; count: number }> {
    const response = await axios.get(`/api/news/${articleId}/related?limit=${limit}`);
    return response.data;
  }

  /**
   * What the market is being talked about most right now (time-decayed).
   */
  async getTrending(windowHours: number = 72, top: number = 12): Promise<TrendingResponse> {
    const response = await axios.get<TrendingResponse>(
      `/api/news/trending?window_hours=${windowHours}&top=${top}`
    );
    return response.data;
  }

  /**
   * Groups of articles covering the same underlying story.
   */
  async getClusters(params: {
    windowHours?: number;
    category?: string;
    symbol?: string;
    threshold?: number;
    limit?: number;
  } = {}): Promise<NewsClustersResponse> {
    const response = await axios.post<NewsClustersResponse>("/api/news/clusters", {
      window_hours: params.windowHours ?? 72,
      category: params.category,
      symbol: params.symbol,
      threshold: params.threshold ?? 0.3,
      limit: params.limit ?? 400,
    });
    return response.data;
  }

  /**
   * Real health of every configured feed, from the last ingest.
   */
  async getSources(): Promise<NewsSourcesResponse> {
    const response = await axios.get<NewsSourcesResponse>("/api/news/sources");
    return response.data;
  }

  /**
   * Desk statistics computed from the stored corpus.
   */
  async getStats(hours: number = 168): Promise<NewsStatsResponse> {
    const response = await axios.get<NewsStatsResponse>(`/api/news/stats?hours=${hours}`);
    return response.data;
  }
}

// Export singleton instance
export const NewsService = new NewsServiceClass();
