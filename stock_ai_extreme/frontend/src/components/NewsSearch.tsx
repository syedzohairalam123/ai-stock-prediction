/**
 * Phase 8 — News Search Component
 * 
 * Search headlines, companies, tickers, publishers, and keywords
 * with debouncing to prevent excessive API calls.
 */

import { useState, useEffect, useRef } from "react";
import BaseInput from "./BaseInput";

interface NewsSearchProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  debounceMs?: number;
  loading?: boolean;
}

export default function NewsSearch({
  value,
  onChange,
  placeholder = "Search news, companies, tickers...",
  debounceMs = 300,
  loading,
}: NewsSearchProps) {
  const [localValue, setLocalValue] = useState(value);
  const debounceTimeout = useRef<NodeJS.Timeout | null>(null);

  // Update local value when prop changes
  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  // Debounced search
  useEffect(() => {
    // Clear existing timeout
    if (debounceTimeout.current) {
      clearTimeout(debounceTimeout.current);
    }

    // Set new timeout
    debounceTimeout.current = setTimeout(() => {
      if (localValue !== value) {
        onChange(localValue);
      }
    }, debounceMs);

    // Cleanup
    return () => {
      if (debounceTimeout.current) {
        clearTimeout(debounceTimeout.current);
      }
    };
  }, [localValue, debounceMs]); // Exclude value and onChange to prevent infinite loop

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setLocalValue(e.target.value);
  };

  const handleClear = () => {
    setLocalValue("");
    onChange("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      handleClear();
    }
  };

  return (
    <div className="news-search" role="search">
      <div className="news-search-input-wrapper">
        <svg
          className="news-search-icon"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>

        <BaseInput
          type="search"
          value={localValue}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={loading}
          className="news-search-input"
          aria-label="Search news articles"
        />

        {loading && (
          <div className="news-search-spinner" aria-label="Searching">
            <svg
              className="spinner"
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
          </div>
        )}

        {localValue && !loading && (
          <button
            onClick={handleClear}
            className="news-search-clear"
            aria-label="Clear search"
            type="button"
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
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>

      {localValue && (
        <div className="news-search-hints">
          <span className="news-search-hint-label">Search tips:</span>
          <ul className="news-search-hint-list">
            <li>Use company names like "Oil & Gas Development"</li>
            <li>Search by ticker like "OGDC" or "HBL"</li>
            <li>Try keywords like "earnings" or "dividend"</li>
            <li>Press ESC to clear search</li>
          </ul>
        </div>
      )}
    </div>
  );
}
