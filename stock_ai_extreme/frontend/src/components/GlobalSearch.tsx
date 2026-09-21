import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, Layers, Hash } from 'lucide-react';
import { POPULAR_SEARCHES, searchGlobal, searchGlobalSmart, type SearchResult, type SearchSource } from '../lib/searchService';

interface GlobalSearchProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function GlobalSearch({ isOpen, onClose }: GlobalSearchProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  // Phase 13 — which layer answered (exact local / server BM25 / local fuzzy).
  const [source, setSource] = useState<SearchSource | null>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  /** Guards against a slow server response overwriting a newer query's results. */
  const requestRef = useRef(0);

  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
      setSource(null);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  const handleSearch = (searchQuery: string) => {
    setQuery(searchQuery);
    setIsLoading(true);
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;

    // Brief debounce keeps the autocomplete from thrashing while typing; the
    // exact local matcher is instant, so it renders immediately. Only when it
    // finds nothing do we consult the ranked layers (server BM25, then the
    // local BK-tree), and a stale response is discarded.
    setTimeout(() => {
      if (requestRef.current !== requestId) return;
      const exact = searchGlobal(searchQuery);
      setResults(exact);
      setSelectedIndex(0);
      setIsLoading(false);

      if (exact.length > 0 || !searchQuery.trim()) {
        setSource(exact.length > 0 ? "LOCAL_EXACT" : null);
        return;
      }

      void searchGlobalSmart(searchQuery).then((smart) => {
        if (requestRef.current !== requestId) return;
        setResults(smart.results);
        setSource(smart.results.length > 0 ? smart.source : null);
      });
    }, 120);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && results.length > 0) {
      e.preventDefault();
      handleSelectResult(results[selectedIndex]);
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  const handleSelectResult = (result: SearchResult) => {
    // Navigate to the right page based on result type
    const routeMap = {
      stock: `/stock/${result.symbol}`,
      sector: `/market?sector=${result.symbol}`,
      index: `/index/${result.symbol}`,
    };
    onClose();
    navigate(routeMap[result.type]);
  };

  const getTypeIcon = (type: SearchResult['type']) => {
    switch (type) {
      case 'stock':
        return <TrendingUp size={16} />;
      case 'sector':
        return <Layers size={16} />;
      case 'index':
        return <Hash size={16} />;
      default:
        return <Search size={16} />;
    }
  };

  const getTypeColor = (type: SearchResult['type']) => {
    switch (type) {
      case 'stock':
        return 'text-green-500';
      case 'sector':
        return 'text-purple-500';
      case 'index':
        return 'text-orange-500';
      default:
        return 'text-gray-500';
    }
  };

  if (!isOpen) return null;

  return (
    <div className="global-search-overlay" onClick={onClose}>
      <div className="global-search-container" ref={searchRef} onClick={(e) => e.stopPropagation()}>
        <div className="global-search-header">
          <Search className="global-search-icon" />
          <input
            type="text"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search stocks, companies, sectors, indices..."
            className="global-search-input"
            autoFocus
          />
          <button onClick={onClose} className="global-search-close">
            <X size={20} />
          </button>
        </div>

        <div className="global-search-content">
          {isLoading ? (
            <div className="global-search-loading">
              <div className="global-search-spinner" />
              <span>Searching...</span>
            </div>
          ) : query && results.length === 0 ? (
            <div className="global-search-empty">
              <Search size={48} className="global-search-empty-icon" />
              <p>No results found for "{query}"</p>
              <p className="global-search-empty-hint">Try searching for KEL, OGDC, TRG, or Banking Sector</p>
            </div>
          ) : !query ? (
            <div className="global-search-hints">
              <p className="global-search-hints-title">Popular Searches</p>
              <div className="global-search-hints-list">
                {POPULAR_SEARCHES.map((result) => (
                  <button
                    key={result.id}
                    onClick={() => handleSelectResult(result)}
                    className="global-search-hint-item"
                  >
                    {getTypeIcon(result.type)}
                    <span className="global-search-hint-symbol">{result.symbol}</span>
                    <span className="global-search-hint-name">{result.name}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="global-search-results">
              {(source === 'SERVER_BM25' || source === 'LOCAL_FUZZY') && (
                <div className="global-search-source" role="status">
                  {source === 'SERVER_BM25' ? 'Ranked matches (server)' : 'Approximate matches (typo tolerance)'}
                </div>
              )}
              {results.map((result, index) => (
                <button
                  key={result.id}
                  onClick={() => handleSelectResult(result)}
                  className={`global-search-result-item ${index === selectedIndex ? 'selected' : ''}`}
                >
                  <div className={`global-search-result-icon ${getTypeColor(result.type)}`}>
                    {getTypeIcon(result.type)}
                  </div>
                  <div className="global-search-result-info">
                    <div className="global-search-result-symbol">{result.symbol}</div>
                    <div className="global-search-result-name">
                      {result.name}
                      {result.sector ? ` · ${result.sector}` : ''}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="global-search-footer">
          <div className="global-search-shortcuts">
            <span className="global-search-shortcut">↑↓</span> Navigate
            <span className="global-search-shortcut">↵</span> Select
            <span className="global-search-shortcut">esc</span> Close
          </div>
        </div>
      </div>
    </div>
  );
}