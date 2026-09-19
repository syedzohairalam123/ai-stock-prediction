/**
 * Phase 8 — News Filters Component
 * 
 * Professional filtering system for news with category, publisher,
 * date range, and ticker filters that update without page reload.
 */

import { useState, useEffect } from "react";
import { NewsFilters as INewsFilters } from "../lib/newsService";
import { formatDateForInput, getDateRange } from "../utils/dateFormat";
import BaseInput from "./BaseInput";

interface NewsFiltersProps {
  filters: INewsFilters;
  onChange: (filters: INewsFilters) => void;
  categories: string[];
  publishers: string[];
  loading?: boolean;
}

export default function NewsFilters({
  filters,
  onChange,
  categories,
  publishers,
  loading,
}: NewsFiltersProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [localFilters, setLocalFilters] = useState<INewsFilters>(filters);

  useEffect(() => {
    setLocalFilters(filters);
  }, [filters]);

  const handleFilterChange = (key: keyof INewsFilters, value: string) => {
    const updated = { ...localFilters, [key]: value || undefined, page: 1 };
    setLocalFilters(updated);
    onChange(updated);
  };

  const handleDateRangePreset = (preset: "today" | "week" | "month" | "year") => {
    const range = getDateRange(preset);
    const updated = {
      ...localFilters,
      date_from: range.from,
      date_to: range.to,
      page: 1,
    };
    setLocalFilters(updated);
    onChange(updated);
  };

  const handleClearFilters = () => {
    const cleared: INewsFilters = { page: 1, page_size: filters.page_size };
    setLocalFilters(cleared);
    onChange(cleared);
  };

  const hasActiveFilters =
    filters.category ||
    filters.publisher ||
    filters.symbol ||
    filters.date_from ||
    filters.date_to ||
    filters.search;

  return (
    <div className="news-filters" role="region" aria-label="News filters">
      <div className="news-filters-header">
        <h3 className="news-filters-title">
          <svg
            className="news-filters-icon"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
            />
          </svg>
          Filters
        </h3>

        <div className="news-filters-actions">
          {hasActiveFilters && (
            <button
              onClick={handleClearFilters}
              className="news-filters-clear"
              disabled={loading}
              aria-label="Clear all filters"
            >
              Clear all
            </button>
          )}

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="news-filters-toggle"
            aria-expanded={isExpanded}
            aria-label={isExpanded ? "Collapse filters" : "Expand filters"}
          >
            {isExpanded ? "Collapse" : "Expand"}
            <svg
              className={`news-filters-toggle-icon ${isExpanded ? "expanded" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="news-filters-content">
          {/* Category Filter */}
          <div className="news-filter-group">
            <label htmlFor="filter-category" className="news-filter-label">
              Category
            </label>
            <select
              id="filter-category"
              value={localFilters.category || ""}
              onChange={(e) => handleFilterChange("category", e.target.value)}
              disabled={loading}
              className="news-filter-select"
            >
              <option value="">All Categories</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
          </div>

          {/* Publisher Filter */}
          <div className="news-filter-group">
            <label htmlFor="filter-publisher" className="news-filter-label">
              Publisher
            </label>
            <select
              id="filter-publisher"
              value={localFilters.publisher || ""}
              onChange={(e) => handleFilterChange("publisher", e.target.value)}
              disabled={loading}
              className="news-filter-select"
            >
              <option value="">All Publishers</option>
              {publishers.map((pub) => (
                <option key={pub} value={pub}>
                  {pub}
                </option>
              ))}
            </select>
          </div>

          {/* Symbol/Ticker Filter */}
          <div className="news-filter-group">
            <label htmlFor="filter-symbol" className="news-filter-label">
              Stock Symbol
            </label>
            <BaseInput
              id="filter-symbol"
              type="text"
              value={localFilters.symbol || ""}
              onChange={(e) => handleFilterChange("symbol", e.target.value.toUpperCase())}
              placeholder="e.g., OGDC, HBL"
              disabled={loading}
            />
          </div>

          {/* Date Range Presets */}
          <div className="news-filter-group">
            <label className="news-filter-label">Quick Date Range</label>
            <div className="news-filter-presets">
              <button
                onClick={() => handleDateRangePreset("today")}
                disabled={loading}
                className="news-filter-preset-btn"
              >
                Today
              </button>
              <button
                onClick={() => handleDateRangePreset("week")}
                disabled={loading}
                className="news-filter-preset-btn"
              >
                Last 7 days
              </button>
              <button
                onClick={() => handleDateRangePreset("month")}
                disabled={loading}
                className="news-filter-preset-btn"
              >
                Last 30 days
              </button>
              <button
                onClick={() => handleDateRangePreset("year")}
                disabled={loading}
                className="news-filter-preset-btn"
              >
                Last year
              </button>
            </div>
          </div>

          {/* Custom Date Range */}
          <div className="news-filter-group-row">
            <div className="news-filter-group">
              <label htmlFor="filter-date-from" className="news-filter-label">
                From Date
              </label>
              <BaseInput
                id="filter-date-from"
                type="date"
                value={localFilters.date_from || ""}
                onChange={(e) => handleFilterChange("date_from", e.target.value)}
                disabled={loading}
              />
            </div>

            <div className="news-filter-group">
              <label htmlFor="filter-date-to" className="news-filter-label">
                To Date
              </label>
              <BaseInput
                id="filter-date-to"
                type="date"
                value={localFilters.date_to || ""}
                onChange={(e) => handleFilterChange("date_to", e.target.value)}
                max={formatDateForInput(new Date())}
                disabled={loading}
              />
            </div>
          </div>

          {/* Active Filters Summary */}
          {hasActiveFilters && (
            <div className="news-filters-active">
              <span className="news-filters-active-label">Active filters:</span>
              <div className="news-filters-active-list">
                {filters.category && (
                  <span className="news-filter-tag">
                    Category: {filters.category}
                    <button
                      onClick={() => handleFilterChange("category", "")}
                      className="news-filter-tag-remove"
                      aria-label="Remove category filter"
                    >
                      ×
                    </button>
                  </span>
                )}
                {filters.publisher && (
                  <span className="news-filter-tag">
                    Publisher: {filters.publisher}
                    <button
                      onClick={() => handleFilterChange("publisher", "")}
                      className="news-filter-tag-remove"
                      aria-label="Remove publisher filter"
                    >
                      ×
                    </button>
                  </span>
                )}
                {filters.symbol && (
                  <span className="news-filter-tag">
                    Symbol: {filters.symbol}
                    <button
                      onClick={() => handleFilterChange("symbol", "")}
                      className="news-filter-tag-remove"
                      aria-label="Remove symbol filter"
                    >
                      ×
                    </button>
                  </span>
                )}
                {(filters.date_from || filters.date_to) && (
                  <span className="news-filter-tag">
                    Date range
                    <button
                      onClick={() => {
                        const updated = { ...localFilters, date_from: undefined, date_to: undefined };
                        setLocalFilters(updated);
                        onChange(updated);
                      }}
                      className="news-filter-tag-remove"
                      aria-label="Remove date filter"
                    >
                      ×
                    </button>
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
