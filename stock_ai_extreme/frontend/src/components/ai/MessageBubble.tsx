/**
 * MessageBubble — one turn in the assistant thread (spec T / U).
 *
 * Assistant answers render through the safe markdown renderer, list the sources
 * they used behind an expandable panel, and offer Copy / Retry. Numbers and
 * signed percentages keep tabular figures and direction colour so a financial
 * answer stays readable at a glance.
 */

import { useState } from 'react';
import { Check, Copy, FileText, Newspaper, RefreshCw, Sigma, User } from 'lucide-react';
import { Citation, Message } from '../../lib/aiService';
import { formatClockTime } from '../../utils/dateFormat';
import { MarkdownContent } from '../../lib/aiMarkdown';

interface MessageBubbleProps {
  message: Message;
  onRetry?: (message: Message) => void;
  canRetry?: boolean;
}

const SOURCE_ICONS: Record<string, typeof Newspaper> = {
  news: Newspaper,
  announcement: FileText,
  quote: Sigma,
  market: Sigma,
  sentiment: Sigma,
};

function sourceIcon(kind: string) {
  const key = kind.toLowerCase();
  if (key.includes('news')) return SOURCE_ICONS.news;
  if (key.includes('announce')) return SOURCE_ICONS.announcement;
  return SOURCE_ICONS.quote;
}

function citeKey(citation: Citation, index: number): string {
  return `${citation.kind}-${citation.title}-${index}`;
}

/** Group citations by kind so the panel reads like a source list, not a dump. */
function groupCitations(citations: Citation[]): Record<string, Citation[]> {
  return citations.reduce<Record<string, Citation[]>>((groups, citation) => {
    const key = citation.kind || 'source';
    groups[key] = groups[key] ? [...groups[key], citation] : [citation];
    return groups;
  }, {});
}

/** One-line summary of the context actually attached to an answer. */
function summariseContext(contextUsed: Record<string, any> | undefined): string | null {
  if (!contextUsed || Object.keys(contextUsed).length === 0) return null;

  const parts: string[] = [];
  const symbol = contextUsed.symbol;
  if (symbol) parts.push(symbol);

  const stock = contextUsed.stock_context ?? contextUsed.index_context;
  if (stock?.recent_news?.length) parts.push(`${stock.recent_news.length} news items`);
  if (stock?.recent_announcements?.length) {
    parts.push(`${stock.recent_announcements.length} announcements`);
  }
  if (stock?.sentiment?.label) parts.push(`sentiment ${stock.sentiment.label}`);
  if (contextUsed.portfolio_context && !contextUsed.portfolio_context.error) {
    parts.push(`${contextUsed.portfolio_context.positions_count ?? 0} positions`);
  }
  if (contextUsed.market_context?.indices) {
    parts.push(`market indices (${Object.keys(contextUsed.market_context.indices).join(', ')})`);
  }
  if (contextUsed.market_status) parts.push(`market ${contextUsed.market_status}`);

  return parts.length > 0 ? parts.join(' · ') : null;
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return Promise.reject(new Error('Clipboard unavailable'));
}

export function MessageBubble({ message, onRetry, canRetry = false }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const contextSummary = summariseContext(message.context_used);
  const grouped = groupCitations(message.citations ?? []);

  const handleCopy = async () => {
    try {
      await copyText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <article className={`ai-msg ${isUser ? 'user' : 'assistant'}`}>
      <span className={`ai-orb${isUser ? '' : ' pulse'}`} aria-hidden>
        {isUser ? <User /> : 'NM'}
      </span>

      <div className="ai-msg-col">
        <div className="ai-bubble">
          {isUser ? (
            <p style={{ whiteSpace: 'pre-wrap' }}>{message.content}</p>
          ) : (
            <MarkdownContent text={message.content} />
          )}
        </div>

        {message.stopped && (
          <div className="ai-msg-meta">
            <span>Generation stopped — partial answer</span>
          </div>
        )}

        {!isUser && Object.keys(grouped).length > 0 && (
          <details className="ai-src">
            <summary>
              <FileText aria-hidden />
              Sources used ({message.citations.length})
            </summary>
            <div className="ai-src-body">
              {Object.entries(grouped).map(([kind, citations]) => {
                const Icon = sourceIcon(kind);
                return (
                  <div key={kind}>
                    <div className="ai-src-note" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Icon aria-hidden style={{ width: 12, height: 12 }} />
                      {kind.toUpperCase()}
                    </div>
                    {citations.map((citation, index) => (
                      <div className="ai-src-item" key={citeKey(citation, index)}>
                        <b>{citation.title}</b>
                        {citation.source ? <span className="ai-src-tag">{citation.source}</span> : null}
                        <div>
                          {citation.symbol ? `${citation.symbol} · ` : ''}
                          {citation.published_at ? `${citation.published_at}` : ''}
                          {citation.detail ? ` · ${citation.detail}` : ''}
                        </div>
                        {citation.url && /^https?:\/\//i.test(citation.url) && (
                          <a href={citation.url} target="_blank" rel="noopener noreferrer nofollow">
                            Open source
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}
              <div className="ai-src-note">
                Sources are the records this answer was built from. Nothing outside this list was
                used, and no link here was invented by the model.
              </div>
            </div>
          </details>
        )}

        {!isUser && contextSummary && (
          <details className="ai-src">
            <summary>
              <Sigma aria-hidden />
              Context used
            </summary>
            <div className="ai-src-body">
              <div className="ai-src-item">{contextSummary}</div>
              {message.context_used?.timestamp ? (
                <div className="ai-src-note">Context built at {message.context_used.timestamp}</div>
              ) : null}
            </div>
          </details>
        )}

        <div className="ai-msg-meta">
          <span>{formatClockTime(message.created_at)}</span>
          {!isUser && message.model ? <span>{message.model}</span> : null}
          {!isUser && message.processing_time_ms ? (
            <span>{(message.processing_time_ms / 1000).toFixed(1)}s</span>
          ) : null}
          {!isUser && message.token_usage?.total_tokens ? (
            <span>{message.token_usage.total_tokens} tok</span>
          ) : null}

          <span className="ai-msg-actions">
            <button type="button" className="ai-act" onClick={handleCopy} title="Copy answer">
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            {!isUser && canRetry && onRetry ? (
              <button
                type="button"
                className="ai-act"
                onClick={() => onRetry(message)}
                title="Ask the same question again"
              >
                <RefreshCw aria-hidden />
                Retry
              </button>
            ) : null}
          </span>
        </div>
      </div>
    </article>
  );
}

export default MessageBubble;
