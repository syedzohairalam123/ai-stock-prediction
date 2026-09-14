import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X, TrendingUp, Building2, Layers, Hash } from 'lucide-react';
import { INDICES, STOCKS } from '../lib/psxMarket';

interface SearchResult {
  id: string;
  type: 'stock' | 'company' | 'sector' | 'index';
  symbol: string;
  name: string;
  sub?: string;
}

interface GlobalSearchProps {
  isOpen: boolean;
  onClose: () => void;
}

// Real PSX search universe, built from the single source of truth in
// `lib/psxMarket.ts` (same tickers the market/movers/screener pages use).
// Stocks/companies open the live stock dashboard; sectors/indices open their
// dedicated pages. No fabricated quote values are shown here — only symbols
// and names, so the search never displays a made-up price.
const searchUniverse: SearchResult[] = [
  ...STOCKS.map((s) => ({
    id: `stock-${s.symbol}`,
    type: 'stock' as const,
    symbol: s.symbol,
    name: s.name,
    sub: s.sector,
  })),
  ...INDICES.map((ix) => ({
    id: `index-${ix.symbol}`,
    type: 'index' as const,
    symbol: ix.symbol,
    name: ix.name,
  })),
  ...[...new Set(STOCKS.map((s) => s.sector))].map((sector) => ({
    id: `sector-${sector}`,
    type: 'sector' as const,
    symbol: sector,
    name: `${sector} sector`,
  })),
];

const POPULAR = ['OGDC', 'LUCK', 'HBL', 'MEBL', 'SYS', 'PSO']
  .map((sym) => searchUniverse.find((r) => r.type === 'stock' && r.symbol === sym))
  .filter((r): r is SearchResult => Boolean(r));

export default function GlobalSearch({ isOpen, onClose }: GlobalSearchProps) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
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

  // Client-side filter over the real PSX universe. Results are capped so a
  // single-letter query ("S") can't render a wall of rows.
  const filterUniverse = useMemo(
    () => (q: string) => {
      const needle = q.trim().toLowerCase();
      if (!needle) return [];
      return searchUniverse
        .filter(
          (item) =>
            item.symbol.toLowerCase().includes(needle) ||
            item.name.toLowerCase().includes(needle)
        )
        .slice(0, 40);
    },
    []
  );

  const handleSearch = (searchQuery: string) => {
    setQuery(searchQuery);
    setIsLoading(true);

    // Brief debounce keeps the autocomplete from thrashing while typing; the
    // search itself is local and instant, so this is presentation only.
    setTimeout(() => {
      setResults(filterUniverse(searchQuery));
      setSelectedIndex(0);
      setIsLoading(false);
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
      company: `/stock/${result.symbol}`,
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
      case 'company':
        return <Building2 size={16} />;
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
      case 'company':
        return 'text-blue-500';
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
                {POPULAR.map((result) => (
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
                      {result.sub ? ` · ${result.sub}` : ''}
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