/**
 * MessageList — the assistant thread (spec A / B / U / V).
 *
 * Renders, in order: the welcome state (capabilities + suggested questions),
 * the persisted conversation, the live streaming answer, and — when something
 * fails — an error card that always offers a way forward. Auto-scroll only
 * follows the tail while the reader is already at the bottom, so scrolling back
 * through a long analysis is never yanked away.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  FileText,
  Gauge,
  LineChart,
  Newspaper,
  PieChart,
  Scale,
} from 'lucide-react';
import { AIContext, Message } from '../../lib/aiService';
import { getPageDescription } from '../../hooks/useAIContext';
import { UseChatResult } from '../../hooks/useChat';
import { useAIStore } from '../../store/useAIStore';
import { MarkdownContent } from '../../lib/aiMarkdown';
import { MessageBubble } from './MessageBubble';
import { SuggestedPrompts } from './SuggestedPrompts';
import { StreamingIndicator } from './StreamingIndicator';

interface MessageListProps {
  context: AIContext;
  chat: UseChatResult;
}

const CAPABILITIES = [
  { icon: LineChart, title: 'Stock analysis', desc: 'Price action, trend and what moved it.' },
  { icon: BarChart3, title: 'Index & market', desc: 'KSE100 tone, breadth and drivers.' },
  { icon: Newspaper, title: 'News summaries', desc: 'Headlines distilled, with sources.' },
  { icon: FileText, title: 'Announcements', desc: 'PSX filings in plain language.' },
  { icon: Gauge, title: 'Sentiment', desc: 'How the tape feels, and why.' },
  { icon: PieChart, title: 'Portfolio', desc: 'Exposure, P/L and concentration.' },
  { icon: Scale, title: 'Comparison', desc: 'Two names, side by side, same fields.' },
];

const THINKING_LABELS = [
  'Reading market context',
  'Checking live quotes',
  'Scanning news and filings',
  'Building the analysis',
];

export function MessageList({ context, chat }: MessageListProps) {
  const { messages, streamingContent, status, error, isStreaming } = chat;
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [thinkingLabel, setThinkingLabel] = useState(THINKING_LABELS[0]);

  const isExpanded = useAIStore((state) => state.isExpanded);
  const setStreamingError = useAIStore((state) => state.setStreamingError);
  const setStreamingStatus = useAIStore((state) => state.setStreamingStatus);
  const setHistoryDrawer = useAIStore((state) => state.setHistoryDrawer);
  const aiAvailable = useAIStore((state) => state.aiStatus?.available !== false);

  const scrollToEnd = useCallback((behavior: ScrollBehavior = 'smooth') => {
    endRef.current?.scrollIntoView({ behavior, block: 'end' });
    setAtBottom(true);
  }, []);

  // Follow the tail only when the reader is already there.
  useEffect(() => {
    if (atBottom) {
      endRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
    }
  }, [messages.length, streamingContent, status, atBottom]);

  // Rotate the "thinking" label so a slow first token still feels alive.
  useEffect(() => {
    if (status !== 'thinking') {
      setThinkingLabel(THINKING_LABELS[0]);
      return;
    }
    let index = 0;
    const timer = window.setInterval(() => {
      index = (index + 1) % THINKING_LABELS.length;
      setThinkingLabel(THINKING_LABELS[index]);
    }, 2600);
    return () => window.clearInterval(timer);
  }, [status]);

  const handleScroll = () => {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    setAtBottom(distance < 80);
  };

  const handleRetry = useCallback(
    (_message: Message) => {
      chat.retry();
    },
    [chat]
  );

  const isEmpty = messages.length === 0 && status === 'idle';

  return (
    <div
      className={`ai-thread${isExpanded ? ' wide-inner' : ''}`}
      ref={scrollRef}
      onScroll={handleScroll}
      aria-live="polite"
      aria-busy={isStreaming}
    >
      {isEmpty && (
        <div className="ai-empty">
          <span className="ai-orb pulse" aria-hidden>
            NM
          </span>
          <h3 className="ai-empty-title">Market assistant</h3>
          <p className="ai-empty-sub">
            I answer from what this app actually holds — live quotes, stored news, PSX
            announcements, sentiment and your portfolio — and I label what is fact versus
            interpretation. You are on <b>{getPageDescription(context)}</b>.
          </p>

          <div className="ai-caps">
            {CAPABILITIES.map((capability) => (
              <div className="ai-cap" key={capability.title}>
                <capability.icon aria-hidden />
                <div>
                  <b>{capability.title}</b>
                  <span>{capability.desc}</span>
                </div>
              </div>
            ))}
          </div>

          <SuggestedPrompts context={context} onSelect={chat.send} />
        </div>
      )}

      {messages.map((message, index) => (
        <MessageBubble
          key={message.id}
          message={message}
          onRetry={handleRetry}
          canRetry={
            message.role === 'assistant' &&
            index === messages.length - 1 &&
            !isStreaming &&
            aiAvailable
          }
        />
      ))}

      {status === 'thinking' && (
        <div className="ai-msg assistant">
          <span className="ai-orb pulse" aria-hidden>
            NM
          </span>
          <div className="ai-msg-col">
            <div className="ai-bubble">
              <StreamingIndicator label={thinkingLabel} />
            </div>
          </div>
        </div>
      )}

      {status === 'streaming' && (
        <div className="ai-msg assistant">
          <span className="ai-orb pulse" aria-hidden>
            NM
          </span>
          <div className="ai-msg-col">
            <div className="ai-bubble">
              {streamingContent ? (
                <>
                  <MarkdownContent text={streamingContent} />
                  <span className="ai-caret" aria-hidden />
                </>
              ) : (
                <StreamingIndicator label="Writing the answer" />
              )}
            </div>
          </div>
        </div>
      )}

      {status === 'error' && error && (
        <div className="ai-error" role="alert">
          <div className="ai-error-head">
            <AlertTriangle aria-hidden />
            {error.category === 'unavailable' ? 'Assistant not configured' : 'Could not answer'}
          </div>
          <p className="ai-error-body">
            {error.message}
            {error.requestId ? ` (request ${error.requestId})` : ''}
          </p>
          <div className="ai-error-actions">
            {error.retryable ? (
              <button type="button" className="ai-btn pri sm" onClick={chat.retry}>
                Retry
              </button>
            ) : null}
            {error.category === 'unavailable' ? (
              <button
                type="button"
                className="ai-btn sm"
                onClick={() => setHistoryDrawer(false)}
                title="AI keys live on the backend — set AI_PROVIDER and the matching key, then restart the API."
              >
                Backend setup
              </button>
            ) : null}
            <button
              type="button"
              className="ai-btn sm"
              onClick={() => {
                setStreamingStatus('idle');
                setStreamingError(null);
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {!atBottom && (messages.length > 0 || isStreaming) && (
        <button type="button" className="ai-jump" onClick={() => scrollToEnd('smooth')}>
          Jump to latest
        </button>
      )}

      <div ref={endRef} />
    </div>
  );
}

export default MessageList;
