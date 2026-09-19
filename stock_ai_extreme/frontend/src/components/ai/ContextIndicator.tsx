/**
 * ContextIndicator — what the assistant can currently see (spec C / E / T).
 *
 * Chips summarize the active context; expanding them spells out the exact data
 * families that will be attached to the next question. Nothing private is
 * implied here: the backend still decides what is actually sent, and portfolio
 * content only ever travels when the request needs it.
 */

import { useState } from 'react';
import { BarChart3, ChevronRight, Database, Info, TrendingUp } from 'lucide-react';
import { AIContext } from '../../lib/aiService';
import { describeContext } from '../../hooks/useAIContext';

interface ContextIndicatorProps {
  context: AIContext;
  marketStatus?: string | null;
  /** Compact mode hides the "Active context" label (used in tight layouts). */
  compact?: boolean;
}

const TONE_ICONS: Record<string, typeof TrendingUp> = {
  stock: TrendingUp,
  index: BarChart3,
};

export function ContextIndicator({ context, marketStatus, compact = false }: ContextIndicatorProps) {
  const [expanded, setExpanded] = useState(false);
  const facts = describeContext(context, marketStatus);

  if (facts.length === 0) return null;

  return (
    <>
      <div className="ai-context">
        {!compact && <span className="ai-context-label">Context</span>}

        {facts.map((fact) => {
          const Icon = TONE_ICONS[fact.tone ?? ''] ?? (fact.id === 'data' ? Database : null);
          return (
            <span key={fact.id} className={`ai-chip ${fact.tone ?? ''}`} title={`${fact.label}${fact.value ? `: ${fact.value}` : ''}`}>
              {Icon ? <Icon aria-hidden /> : null}
              {fact.value ? (
                <>
                  {fact.label}: <b>{fact.value}</b>
                </>
              ) : (
                <b>{fact.label}</b>
              )}
            </span>
          );
        })}

        <button
          type="button"
          className="ai-chip-btn"
          onClick={() => setExpanded((open) => !open)}
          aria-expanded={expanded}
          title="Show exactly which data will be sent with your question"
        >
          <Info aria-hidden style={{ width: 12, height: 12 }} />
          {expanded ? 'Hide detail' : 'What is sent'}
          <ChevronRight
            aria-hidden
            style={{ width: 12, height: 12, transform: expanded ? 'rotate(90deg)' : undefined }}
          />
        </button>
      </div>

      {expanded && (
        <div className="ai-context-detail">
          <strong>Attached to your next question</strong>
          <ul>
            <li>
              <b>Page:</b> {context.route}
            </li>
            {context.symbol && (
              <li>
                <b>{context.entity_type === 'index' ? 'Index' : 'Stock'}:</b> {context.symbol}
                {context.timeframe ? ` · timeframe ${context.timeframe}` : ''}
              </li>
            )}
            <li>
              <b>Live market data:</b> quote, previous close and day change for the selected
              {context.entity_type === 'index' ? ' index' : ' symbol'}
            </li>
            {context.include_news && (
              <li>
                <b>News:</b> recent headlines relevant to this page (stored articles first, then the
                provider's headline feed)
              </li>
            )}
            {context.include_announcements && (
              <li>
                <b>Announcements:</b> recent PSX filings for the selected symbol
              </li>
            )}
            {context.include_sentiment && (
              <li>
                <b>Sentiment:</b> headline-derived sentiment score and label
              </li>
            )}
            {context.include_portfolio && (
              <li>
                <b>Portfolio:</b> your holdings, cost basis and P/L — included only because you are
                on a portfolio page
              </li>
            )}
          </ul>
          <p className="ai-note">
            The backend rebuilds this context per request and ignores anything the page does not
            legitimately have. Answers are analysis, not advice, and you will always see which
            sources an answer used.
          </p>
        </div>
      )}
    </>
  );
}

export default ContextIndicator;
