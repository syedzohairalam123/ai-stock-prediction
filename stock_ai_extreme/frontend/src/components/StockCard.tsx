/**
 * Phase 9 — Stock Card Component
 * 
 * Displays stock information with:
 * - Symbol, name, price, change
 * - Mini trend sparkline chart
 * - Watchlist add/remove button
 * - Click to navigate to stock detail
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PopularStock, PortfolioService } from "../lib/portfolioService";
import BaseBadge from "./BaseBadge";

interface StockCardProps {
  stock: PopularStock;
  isInWatchlist?: boolean;
  onWatchlistToggle?: (symbol: string, isAdded: boolean) => void;
  /** Surfaced when the watchlist action fails — the page shows it as a banner. */
  onWatchlistError?: (symbol: string, message: string) => void;
}

export default function StockCard({ stock, isInWatchlist = false, onWatchlistToggle, onWatchlistError }: StockCardProps) {
  const navigate = useNavigate();
  const [isAddingToWatchlist, setIsAddingToWatchlist] = useState(false);

  const handleCardClick = () => {
    navigate(`/stock/${stock.symbol}`);
  };

  const handleWatchlistClick = async (e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent card click
    
    try {
      setIsAddingToWatchlist(true);
      
      if (isInWatchlist) {
        await PortfolioService.removeFromWatchlist(stock.symbol);
        onWatchlistToggle?.(stock.symbol, false);
      } else {
        await PortfolioService.addToWatchlist(stock.symbol);
        onWatchlistToggle?.(stock.symbol, true);
      }
    } catch (error) {
      console.error("Watchlist toggle failed:", error);
      onWatchlistError?.(
        stock.symbol,
        error instanceof Error ? error.message : `Could not update watchlist for ${stock.symbol}`
      );
    } finally {
      setIsAddingToWatchlist(false);
    }
  };

  const getChangeColor = () => {
    if (stock.change === null || stock.change === undefined) return "text-gray-600";
    return stock.change >= 0 ? "text-green-600" : "text-red-600";
  };

  const getChangeIcon = () => {
    if (stock.change === null || stock.change === undefined) return "—";
    return stock.change >= 0 ? "▲" : "▼";
  };

  // Generate mini sparkline SVG
  const renderSparkline = () => {
    if (!stock.trend || stock.trend.length < 2) {
      return null;
    }

    const width = 80;
    const height = 24;
    const padding = 2;

    const prices = stock.trend.map(t => t.price);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice || 1;

    const points = stock.trend.map((point, index) => {
      const x = (index / (stock.trend.length - 1)) * (width - 2 * padding) + padding;
      const y = height - padding - ((point.price - minPrice) / priceRange) * (height - 2 * padding);
      return `${x},${y}`;
    }).join(" ");

    const trendColor = stock.change && stock.change >= 0 ? "#10b981" : "#ef4444";

    return (
      <svg width={width} height={height} className="stock-card-sparkline">
        <polyline
          points={points}
          fill="none"
          stroke={trendColor}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  };

  return (
    <div
      className="stock-card"
      onClick={handleCardClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        // Keyboard parity for the card's primary action (open stock).
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleCardClick();
        }
      }}
      aria-label={`Open ${stock.symbol} — ${stock.name}`}
    >
      <div className="stock-card-header">
        <div className="stock-card-info">
          <h3 className="stock-card-symbol">{stock.symbol}</h3>
          <p className="stock-card-name">{stock.name}</p>
        </div>

        <button
          onClick={handleWatchlistClick}
          disabled={isAddingToWatchlist}
          className={`stock-card-watchlist-btn ${isInWatchlist ? "active" : ""}`}
          aria-label={isInWatchlist ? "Remove from watchlist" : "Add to watchlist"}
          title={isInWatchlist ? "Remove from watchlist" : "Add to watchlist"}
        >
          {isInWatchlist ? (
            <svg fill="currentColor" viewBox="0 0 20 20" className="w-5 h-5">
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            </svg>
          ) : (
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          )}
        </button>
      </div>

      <div className="stock-card-price">
        <span className="stock-card-price-value">
          {stock.price !== null && stock.price !== undefined
            ? `PKR ${stock.price.toFixed(2)}`
            : "PRICE UNAVAILABLE"}
        </span>
      </div>

      <div className="stock-card-change">
        <span className={`stock-card-change-value ${getChangeColor()}`}>
          {getChangeIcon()}{" "}
          {stock.change !== null && stock.change !== undefined
            ? `${Math.abs(stock.change).toFixed(2)}`
            : "—"}
        </span>
        {stock.change_pct !== null && stock.change_pct !== undefined && (
          <span className={`stock-card-change-pct ${getChangeColor()}`}>
            ({stock.change_pct >= 0 ? "+" : ""}{stock.change_pct.toFixed(2)}%)
          </span>
        )}
      </div>

      {stock.trend && stock.trend.length > 0 && (
        <div className="stock-card-chart">
          {renderSparkline()}
        </div>
      )}

      {stock.sector && (
        <div className="stock-card-footer">
          <BaseBadge variant="default" size="sm">
            {stock.sector}
          </BaseBadge>
        </div>
      )}
    </div>
  );
}
