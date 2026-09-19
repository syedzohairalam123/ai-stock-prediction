/**
 * Phase 9 — Popular Stocks Page
 * 
 * Discovery dashboard for popular PSX stocks with:
 * - Category filtering
 * - Real-time price data
 * - Stock cards with trends
 * - Watchlist integration
 */

import { useState, useEffect } from "react";
import { PortfolioService, PopularStock } from "../lib/portfolioService";
import StockCard from "../components/StockCard";
import BaseBadge from "../components/BaseBadge";

export default function PopularStocksPage() {
  const [stocks, setStocks] = useState<PopularStock[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [unavailable, setUnavailable] = useState<{ symbol: string; reason: string }[]>([]);
  const [requested, setRequested] = useState(0);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);

  useEffect(() => {
    loadCategories();
    loadWatchlist();
    loadStocks();
  }, [selectedCategory]);

  const loadCategories = async () => {
    try {
      const response = await PortfolioService.getStockCategories();
      setCategories(response.categories.map(c => c.id));
    } catch (err) {
      console.error("Failed to load categories:", err);
    }
  };

  const loadWatchlist = async () => {
    try {
      const items = await PortfolioService.getWatchlist();
      setWatchlist(new Set(items.map(item => item.ticker)));
    } catch (err) {
      console.error("Failed to load watchlist:", err);
    }
  };

  const loadStocks = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await PortfolioService.getPopularStocks(
        selectedCategory || undefined,
        selectedCategory ? 20 : 30
      );

      setStocks(response.stocks);
      // Honest per-symbol failure reporting (spec S) — symbols the provider
      // cannot price are listed, never silently dropped or faked.
      setUnavailable(response.unavailable ?? []);
      setRequested(response.requested ?? response.stocks.length);
    } catch (err) {
      console.error("Failed to load stocks:", err);
      setError("Failed to load stocks. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = () => {
    loadStocks();
    loadWatchlist();
  };

  const handleWatchlistToggle = (symbol: string, isAdded: boolean) => {
    setWatchlistError(null);
    setWatchlist(prev => {
      const updated = new Set(prev);
      if (isAdded) {
        updated.add(symbol);
      } else {
        updated.delete(symbol);
      }
      return updated;
    });
  };

  /** Spec S: a failed watchlist action is visible, never swallowed. */
  const handleWatchlistError = (symbol: string, message: string) => {
    setWatchlistError(`${symbol}: ${message}`);
  };

  const handleCategoryChange = (category: string | null) => {
    setSelectedCategory(category);
  };

  return (
    <main className="popular-stocks-page">
      {/* Page Header */}
      <div className="psx-page-head">
        <div>
          <p>Stock Discovery</p>
          <h1>Popular PSX Stocks</h1>
        </div>
        <div className="popular-stocks-actions">
          <BaseBadge variant="info">
            {stocks.length} stocks
          </BaseBadge>
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="popular-stocks-refresh-btn"
            aria-label="Refresh stocks"
          >
            <svg
              className={`popular-stocks-refresh-icon ${loading ? "spinning" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* Category Filter */}
      <div className="popular-stocks-categories">
        <button
          onClick={() => handleCategoryChange(null)}
          className={`category-btn ${selectedCategory === null ? "active" : ""}`}
        >
          All Stocks
        </button>
        {categories.map(category => (
          <button
            key={category}
            onClick={() => handleCategoryChange(category)}
            className={`category-btn ${selectedCategory === category ? "active" : ""}`}
          >
            {category.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
          </button>
        ))}
      </div>

      {/* Watchlist action error (spec S) */}
      {watchlistError && (
        <div className="form-error-banner" role="alert">
          <span>{watchlistError}</span>
          <button className="tx-confirm-no" onClick={() => setWatchlistError(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="popular-stocks-error" role="alert">
          <svg
            className="popular-stocks-error-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p>{error}</p>
          <button onClick={handleRefresh} className="popular-stocks-error-retry">
            Try again
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && stocks.length === 0 && (
        <div className="popular-stocks-grid">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="stock-card loading">
              <div className="skeleton stock-card-skeleton" />
            </div>
          ))}
        </div>
      )}

      {/* Stocks Grid */}
      {!loading && stocks.length === 0 && !error && (
        <div className="popular-stocks-empty">
          <svg
            className="popular-stocks-empty-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
          </svg>
          <p>No stocks found</p>
          <small>Try selecting a different category</small>
        </div>
      )}

      {stocks.length > 0 && (
        <div className="popular-stocks-grid">
          {stocks.map(stock => (
            <StockCard
              key={stock.symbol}
              stock={stock}
              isInWatchlist={watchlist.has(stock.symbol)}
              onWatchlistToggle={handleWatchlistToggle}
              onWatchlistError={handleWatchlistError}
            />
          ))}
        </div>
      )}

      {/* Honest per-symbol failure report (spec S) */}
      {!loading && unavailable.length > 0 && (
        <p className="popular-stocks-unavailable" role="status">
          {unavailable.length} of {requested} symbols could not be priced right now
          ({unavailable.slice(0, 6).map(u => u.symbol).join(", ")}
          {unavailable.length > 6 ? "…" : ""}). They are hidden until the provider
          can quote them — no placeholder prices are shown.
        </p>
      )}

      {/* Info Footer */}
      <footer className="popular-stocks-footer">
        <svg
          className="popular-stocks-footer-icon"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <div>
          <p className="popular-stocks-footer-title">Real-Time Market Data</p>
          <p className="popular-stocks-footer-text">
            All prices and trends are fetched from live market data sources. Click any stock
            to view detailed information and charts. Add stocks to your watchlist for quick access.
          </p>
        </div>
      </footer>
    </main>
  );
}
