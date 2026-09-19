/**
 * AI Context Builder (frontend half of spec D)
 *
 * The single source of truth for *what the user is looking at*. Every AI
 * component reads context from here — no component builds its own context.
 *
 * What it reads
 *   - the current route (page type)
 *   - the symbol/index in the URL, or the globally selected ticker
 *   - the timeframe in the query string
 *   - which data families that page can legitimately supply (news,
 *     announcements, sentiment, portfolio)
 *
 * What it never does
 *   - it carries no portfolio *content* — the backend decides what private
 *     data is included and only when the request needs it (spec E)
 */

import { useLocation } from 'react-router-dom';
import { useMemo } from 'react';
import { AIContext, EntityType } from '../lib/aiService';
import { useTickerStore } from '../store/useStore';

export type PageType =
  | 'market_overview'
  | 'stock_detail'
  | 'index_detail'
  | 'portfolio'
  | 'watchlist'
  | 'news'
  | 'announcements'
  | 'sentiment'
  | 'screener'
  | 'compare'
  | 'forex_commodities'
  | 'other';

const INDEX_SYMBOLS = new Set([
  'KSE100',
  'KSE30',
  'KSEALL',
  'ALLSHR',
  'KMI30',
  'KMIALLSHR',
  'PSXDIV20',
  'BKTI',
  'OGTI',
]);

function pageTypeForRoute(path: string): PageType {
  if (path === '/' || path.startsWith('/market') || path.startsWith('/home')) return 'market_overview';
  if (path.startsWith('/stock/')) return 'stock_detail';
  if (path.startsWith('/index/')) return 'index_detail';
  if (path.startsWith('/portfolio')) return 'portfolio';
  if (path.startsWith('/watchlist')) return 'watchlist';
  if (path.startsWith('/announcements')) return 'announcements';
  if (path.startsWith('/news')) return 'news';
  if (path.startsWith('/sentiment')) return 'sentiment';
  if (path.startsWith('/screener')) return 'screener';
  if (path.startsWith('/compare')) return 'compare';
  if (path.startsWith('/forex')) return 'forex_commodities';
  return 'other';
}

/** Normalize a raw path into a context object (exported for tests/reuse). */
export function buildContextFromLocation(
  path: string,
  search: string,
  fallbackTicker?: string
): AIContext {
  const params = new URLSearchParams(search);
  const context: AIContext = { route: path };
  const pageType = pageTypeForRoute(path);
  const timeframe = params.get('timeframe') || params.get('range') || params.get('interval') || undefined;

  const routeSymbol =
    path.split('/stock/')[1]?.split('/')[0] || path.split('/index/')[1]?.split('/')[0];

  if (routeSymbol) {
    const symbol = decodeURIComponent(routeSymbol).toUpperCase();
    const isIndex = pageType === 'index_detail' || INDEX_SYMBOLS.has(symbol);
    context.symbol = symbol;
    context.entity_type = isIndex ? 'index' : 'stock';
    context.timeframe = timeframe || '1D';
    context.include_news = true;
    context.include_sentiment = true;
    context.include_announcements = !isIndex;
  } else if (pageType === 'portfolio') {
    context.include_portfolio = true;
    context.include_news = true;
  } else if (pageType === 'watchlist') {
    context.include_news = true;
    context.include_sentiment = true;
  } else if (pageType === 'news') {
    context.include_news = true;
    context.include_sentiment = true;
  } else if (pageType === 'announcements') {
    context.include_announcements = true;
    context.include_news = true;
  } else if (pageType === 'sentiment') {
    context.include_sentiment = true;
    context.include_news = true;
  } else if (pageType === 'market_overview' || pageType === 'screener' || pageType === 'compare') {
    context.include_news = true;
    context.include_sentiment = true;
    if (pageType === 'screener' && fallbackTicker) {
      context.symbol = fallbackTicker.toUpperCase();
      context.entity_type = 'stock';
      context.timeframe = timeframe;
    }
  }

  return context;
}

export function useAIContext(): AIContext {
  const location = useLocation();
  const currentTicker = useTickerStore((state) => state.currentTicker);

  return useMemo(
    () => buildContextFromLocation(location.pathname, location.search, currentTicker),
    [location.pathname, location.search, currentTicker]
  );
}

export function getPageType(context: AIContext): PageType {
  return pageTypeForRoute(context.route);
}

/** Short, human label for the page the user is on. */
export function getPageDescription(context: AIContext): string {
  const entityType: EntityType | undefined = context.entity_type;
  if (context.symbol && entityType === 'index') return `${context.symbol} index`;
  if (context.symbol && entityType === 'stock') return `${context.symbol}`;

  switch (getPageType(context)) {
    case 'market_overview':
      return 'Market overview';
    case 'portfolio':
      return 'Portfolio';
    case 'watchlist':
      return 'Watchlist';
    case 'news':
      return 'News desk';
    case 'announcements':
      return 'Announcements';
    case 'sentiment':
      return 'Sentiment';
    case 'screener':
      return 'Screener';
    case 'compare':
      return 'Comparison';
    case 'forex_commodities':
      return 'Forex & commodities';
    default:
      return 'Neural Market';
  }
}

export interface ContextFact {
  id: string;
  label: string;
  value?: string;
  tone?: 'stock' | 'index' | 'on' | 'off';
}

/**
 * Flatten the context into the chips the UI shows above the thread, so the
 * user can always see exactly what the assistant was told.
 */
export function describeContext(
  context: AIContext,
  marketStatus?: string | null
): ContextFact[] {
  const facts: ContextFact[] = [
    { id: 'page', label: getPageDescription(context) },
  ];

  if (context.symbol) {
    facts.push({
      id: 'symbol',
      label: context.entity_type === 'index' ? 'Index' : 'Stock',
      value: context.symbol,
      tone: context.entity_type === 'index' ? 'index' : 'stock',
    });
  }

  if (context.timeframe) {
    facts.push({ id: 'timeframe', label: 'Timeframe', value: context.timeframe });
  }

  if (marketStatus) {
    const open = marketStatus === 'OPEN';
    facts.push({
      id: 'market',
      label: 'Market',
      value: marketStatus,
      tone: open ? 'on' : 'off',
    });
  }

  const families: string[] = [];
  if (context.include_news) families.push('news');
  if (context.include_announcements) families.push('announcements');
  if (context.include_sentiment) families.push('sentiment');
  if (context.include_portfolio) families.push('portfolio');

  if (families.length > 0) {
    facts.push({ id: 'data', label: 'Data', value: families.join(' · ') });
  }

  return facts;
}

/**
 * Local prompt fallbacks that mirror the backend PromptBuilder. Used when the
 * backend cannot be reached, so suggestions are never simply missing.
 */
export function getLocalPrompts(context: AIContext): string[] {
  const symbol = context.symbol;
  switch (getPageType(context)) {
    case 'stock_detail':
      return symbol
        ? [
            `Explain today's move in ${symbol}`,
            `Analyse the current trend in ${symbol}`,
            `Summarise recent news about ${symbol}`,
            `What do the latest announcements mean for ${symbol}?`,
            `Compare ${symbol} with KSE100`,
          ]
        : [];
    case 'index_detail':
      return symbol
        ? [
            `Analyse ${symbol} performance today`,
            `What is driving the ${symbol} move?`,
            'Which sectors contributed most?',
            'Explain the current market sentiment',
          ]
        : [];
    case 'portfolio':
      return [
        'Which holding contributes most to my P/L?',
        'Show my largest exposure',
        'Summarise my portfolio concentration',
        'Which positions are underwater?',
      ];
    case 'watchlist':
      return [
        'Which names on my watchlist moved most today?',
        'Any notable news on my watchlist today?',
        'Which watchlist names look weakest?',
      ];
    case 'news':
      return [
        "Summarise today's top financial news",
        'What are the major market themes?',
        'Which stocks are mentioned most in the news?',
      ];
    case 'announcements':
      return [
        'Summarise the latest PSX announcements',
        'Are any announcements materially price-sensitive?',
        'Which companies reported corporate actions?',
      ];
    case 'sentiment':
      return [
        'Explain the current market sentiment',
        'Which stocks have the strongest sentiment?',
        'How has sentiment changed recently?',
      ];
    case 'compare':
      return ['Compare HBL and MEBL', 'Compare OGDC and PPL', 'Compare LUCK and ENGRO'];
    default:
      return [
        "What is driving today's market?",
        'Which sectors are strongest today?',
        "Summarise today's market tone",
        'What are the top movers?',
      ];
  }
}
