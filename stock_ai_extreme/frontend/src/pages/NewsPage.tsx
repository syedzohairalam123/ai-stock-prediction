/**
 * Phase 8 — Professional News & Financial Intelligence Desk
 * 
 * Complete news dashboard with:
 * - Hero news card
 * - Professional news feed
 * - Advanced filtering and search
 * - Ticker linking
 * - Real-time data from multiple sources
 * - Responsive design
 * - Accessibility features
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  NewsService,
  NewsFilters as INewsFilters,
  NewsArticle,
  NewsSourcesResponse,
  NewsStatsResponse,
  StoryCluster,
  TrendingEntity,
} from "../lib/newsService";
import HeroNewsCard from "../components/HeroNewsCard";
import NewsFeed from "../components/NewsFeed";
import NewsFilters from "../components/NewsFilters";
import NewsSearch from "../components/NewsSearch";
import NewsSourceHealth from "../components/NewsSourceHealth";
import StoryClusters from "../components/StoryClusters";
import TrendingStrip from "../components/TrendingStrip";
import BaseBadge from "../components/BaseBadge";

/** Rolling window the intelligence panels are computed over. */
const INTELLIGENCE_WINDOW_HOURS = 72;

export default function NewsPage() {
  const [heroArticle, setHeroArticle] = useState<NewsArticle | null>(null);
  const [heroEmptyReason, setHeroEmptyReason] = useState<string | null>(null);
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [publishers, setPublishers] = useState<string[]>([]);

  const [trending, setTrending] = useState<TrendingEntity[]>([]);
  const [trendingArticles, setTrendingArticles] = useState<number | undefined>();
  const [trendingLoading, setTrendingLoading] = useState(false);
  const [trendingError, setTrendingError] = useState<string | null>(null);

  const [clusters, setClusters] = useState<StoryCluster[]>([]);
  const [clustersAnalyzed, setClustersAnalyzed] = useState<number | undefined>();
  const [clustersDisclaimer, setClustersDisclaimer] = useState<string | undefined>();
  const [clustersLoading, setClustersLoading] = useState(false);
  const [clustersError, setClustersError] = useState<string | null>(null);

  const [sources, setSources] = useState<NewsSourcesResponse | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  const [stats, setStats] = useState<NewsStatsResponse | null>(null);

  const [filters, setFilters] = useState<INewsFilters>({
    page: 1,
    page_size: 20,
    sort: "recent",
  });

  const [pagination, setPagination] = useState({
    page: 1,
    page_size: 20,
    total: 0,
    pages: 1,
  });

  const [loading, setLoading] = useState(false);
  const [heroLoading, setHeroLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  // Guards against a slow response from an earlier filter overwriting a newer
  // one — a real race whenever the user types in the search box.
  const requestId = useRef(0);
  const filtersKey = useMemo(() => JSON.stringify(filters), [filters]);

  const loadHeroNews = useCallback(async () => {
    try {
      setHeroLoading(true);
      const response = await NewsService.getHeroNews();
      setHeroArticle(response.hero);
      setHeroEmptyReason(response.hero ? null : (response.reason ?? null));
    } catch (err) {
      console.error("Failed to load hero news:", err);
      setHeroEmptyReason("The lead story could not be loaded from the desk.");
    } finally {
      setHeroLoading(false);
    }
  }, []);

  const loadNews = useCallback(async (current: INewsFilters) => {
    const id = ++requestId.current;
    try {
      setLoading(true);
      setError(null);
      const response = await NewsService.searchNews(current);
      if (id !== requestId.current) return; // a newer request already answered
      setArticles(response.items);
      setPagination(response.pagination);
    } catch (err) {
      if (id !== requestId.current) return;
      console.error("Failed to load news:", err);
      setError("Failed to load news. Please try again.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  const loadCategories = async () => {
    try {
      const response = await NewsService.getCategories();
      setCategories(response.categories.map(c => c.name));
    } catch (err) {
      console.error("Failed to load categories:", err);
    }
  };

  const loadPublishers = async () => {
    try {
      const response = await NewsService.getPublishers();
      setPublishers(response.publishers);
    } catch (err) {
      console.error("Failed to load publishers:", err);
    }
  };

  const loadIntelligence = useCallback(async () => {
    setTrendingLoading(true);
    try {
      const response = await NewsService.getTrending(INTELLIGENCE_WINDOW_HOURS, 12);
      setTrending(response.entities);
      setTrendingArticles(response.articles_considered);
      setTrendingError(null);
    } catch (err) {
      console.error("Failed to load trending:", err);
      setTrendingError("the trending endpoint could not be reached");
    } finally {
      setTrendingLoading(false);
    }

    setClustersLoading(true);
    try {
      const response = await NewsService.getClusters({
        windowHours: INTELLIGENCE_WINDOW_HOURS,
        limit: 400,
      });
      setClusters(response.clusters);
      setClustersAnalyzed(response.articles_analyzed);
      setClustersDisclaimer(response.disclaimer);
      setClustersError(null);
    } catch (err) {
      console.error("Failed to load clusters:", err);
      setClustersError("the clustering endpoint could not be reached");
    } finally {
      setClustersLoading(false);
    }

    setSourcesLoading(true);
    try {
      const [sourcesResponse, statsResponse] = await Promise.all([
        NewsService.getSources(),
        NewsService.getStats(168),
      ]);
      setSources(sourcesResponse);
      setStats(statsResponse);
      setSourcesError(null);
    } catch (err) {
      console.error("Failed to load source health:", err);
      setSourcesError("the source-status endpoint could not be reached");
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadHeroNews();
    loadCategories();
    loadPublishers();
    loadIntelligence();
  }, [loadHeroNews, loadIntelligence]);

  // Feed reload on any filter change (debounced search arrives pre-debounced;
  // the key comparison stops an identical object identity from re-fetching).
  useEffect(() => {
    loadNews(filters);
  }, [filtersKey, filters, loadNews]);

  const handleRefreshNews = async () => {
    try {
      setRefreshing(true);
      setRefreshNote(null);
      const result = await NewsService.refreshNews("Pakistan stock market finance business");
      setRefreshNote(
        `${result.articles_stored} new article(s) stored · ${result.sources_ok} feed(s) responded · ${result.total_articles} total`,
      );
      await Promise.all([loadNews(filters), loadHeroNews(), loadIntelligence()]);
    } catch (err) {
      console.error("Failed to refresh news:", err);
      setError("Failed to refresh news. Please try again.");
    } finally {
      setRefreshing(false);
    }
  };

  const handleFiltersChange = (newFilters: INewsFilters) => {
    setFilters(newFilters);
  };

  const handleSearchChange = (search: string) => {
    // A text query is only meaningful when ranked; asking the backend for BM25
    // ordering is what makes the first results the *best* matches.
    setFilters({ ...filters, search, sort: search ? "relevance" : "recent", page: 1 });
  };

  const handleSortChange = (sort: "recent" | "impact" | "relevance") => {
    setFilters({ ...filters, sort, page: 1 });
  };

  const handlePageChange = (page: number) => {
    setFilters({ ...filters, page });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleSelectTopic = (topic: string) => {
    setFilters((current) => ({ ...current, search: topic, sort: "relevance", page: 1 }));
  };

  const handleOpenCluster = (cluster: StoryCluster) => {
    const symbol = cluster.symbols[0];
    if (symbol) {
      setFilters((current) => ({ ...current, symbol, search: undefined, page: 1 }));
    } else if (cluster.terms[0]) {
      setFilters((current) => ({ ...current, search: cluster.terms[0], sort: "relevance", page: 1 }));
    }
  };

  return (
    <main className="news-page">
      {/* Page Header */}
      <div className="psx-page-head">
        <div>
          <p>Financial Intelligence Desk</p>
          <h1>News & Markets</h1>
        </div>
        <div className="news-page-actions">
          <BaseBadge variant="info">
            {pagination.total} articles
          </BaseBadge>
          {stats && (
            <BaseBadge variant="default">
              {stats.publishers} publishers · avg impact {stats.avg_impact_score ?? "—"}
            </BaseBadge>
          )}
          <button
            onClick={handleRefreshNews}
            disabled={refreshing}
            className="news-refresh-btn"
            aria-label="Refresh news"
          >
            <svg
              className={`news-refresh-icon ${refreshing ? "spinning" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Refresh result — says how much came back and from how many feeds,
          rather than leaving the user to guess whether it worked. */}
      {refreshNote && (
        <p className="news-refresh-note" role="status">
          {refreshNote}
        </p>
      )}

      {/* Hero News Section */}
      <section className="news-hero-section" aria-labelledby="hero-news-title">
        <HeroNewsCard
          article={heroArticle}
          loading={heroLoading}
          emptyReason={heroEmptyReason}
        />
      </section>

      {/* Trending + story clusters: computed from the same stored corpus the
          feed reads, so the panels and the list never disagree. */}
      <TrendingStrip
        entities={trending}
        loading={trendingLoading}
        error={trendingError}
        windowHours={INTELLIGENCE_WINDOW_HOURS}
        articlesConsidered={trendingArticles}
        onSelectTopic={handleSelectTopic}
      />

      <StoryClusters
        clusters={clusters}
        loading={clustersLoading}
        error={clustersError}
        articlesAnalyzed={clustersAnalyzed}
        disclaimer={clustersDisclaimer}
        onOpenCluster={handleOpenCluster}
      />

      {/* Search Bar */}
      <section className="news-search-section">
        <NewsSearch
          value={filters.search || ""}
          onChange={handleSearchChange}
          loading={loading}
          debounceMs={300}
        />
      </section>

      {/* Filters */}
      <NewsFilters
        filters={filters}
        onChange={handleFiltersChange}
        categories={categories}
        publishers={publishers}
        loading={loading}
      />

      {/* Error Message */}
      {error && (
        <div className="news-error" role="alert">
          <svg
            className="news-error-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p>{error}</p>
          <button onClick={() => loadNews(filters)} className="news-error-retry">
            Try again
          </button>
        </div>
      )}

      {/* News Feed */}
      <section className="news-feed-section" aria-label="News articles feed">
        <div className="news-feed-header">
          <div>
            <h2 className="news-feed-heading">
              {filters.category ? `${filters.category} News` : "Latest News"}
            </h2>
            <p className="news-feed-subheading">
              {filters.search && `Results for "${filters.search}"`}
              {filters.symbol && ` • Related to ${filters.symbol}`}
              {!filters.search && !filters.symbol && "Ranked by recency — switch to impact or relevance below"}
            </p>
          </div>

          <div className="news-sort-control" role="group" aria-label="Sort the news feed">
            {([
              { id: "recent", label: "Newest first" },
              { id: "impact", label: "Highest impact" },
              { id: "relevance", label: "Best match" },
            ] as const).map((option) => (
              <button
                key={option.id}
                type="button"
                className={`news-sort-button${(filters.sort ?? "recent") === option.id ? " is-active" : ""}`}
                aria-pressed={(filters.sort ?? "recent") === option.id}
                onClick={() => handleSortChange(option.id)}
                disabled={option.id === "relevance" && !filters.search}
                title={
                  option.id === "relevance" && !filters.search
                    ? "Type a search term to rank by relevance"
                    : undefined
                }
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <NewsFeed
          articles={articles}
          loading={loading}
          page={pagination.page}
          totalPages={pagination.pages}
          onPageChange={handlePageChange}
        />
      </section>

      {/* Source Health — the honest list of which feeds actually answered. */}
      <NewsSourceHealth data={sources} loading={sourcesLoading} error={sourcesError} />

      {/* Data Sources Disclaimer */}
      <footer className="news-disclaimer">
        <svg
          className="news-disclaimer-icon"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <div>
          <p className="news-disclaimer-title">News Sources & Data Integrity</p>
          <p className="news-disclaimer-text">
            Headlines are aggregated from real publisher feeds — Dawn, The Express
            Tribune, Google News, BBC, CNBC, WSJ, Yahoo Finance and others — plus
            NewsAPI, Finnhub and Alpha Vantage when keys are configured. Every
            headline, publisher, timestamp and link is the publisher's own; nothing
            is rewritten or invented, and a feed that fails contributes no articles.
            Sentiment is a lexicon heuristic, entity linking is validated against the
            terminal's real PSX symbol universe, and impact/clustering are computed
            from the article text itself. Informational only — not investment advice.
          </p>
        </div>
      </footer>
    </main>
  );
}
