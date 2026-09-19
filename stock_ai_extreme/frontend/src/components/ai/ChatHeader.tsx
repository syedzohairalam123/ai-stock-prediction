/**
 * ChatHeader — the assistant's title bar (spec B).
 *
 * Shows what the assistant is attached to, whether the provider is live, and
 * the four actions a chat surface needs: new conversation, history, expand /
 * collapse and close.
 */

import { History, Maximize2, Minimize2, Plus, X } from 'lucide-react';
import { AIContext } from '../../lib/aiService';
import { getPageDescription } from '../../hooks/useAIContext';
import { useAIStore } from '../../store/useAIStore';

interface ChatHeaderProps {
  context: AIContext;
  onClose: () => void;
  onToggleHistory: () => void;
  onNewChat: () => void;
  isExpanded: boolean;
  onToggleExpand: () => void;
  hasConversation: boolean;
}

export function ChatHeader({
  context,
  onClose,
  onToggleHistory,
  onNewChat,
  isExpanded,
  onToggleExpand,
  hasConversation,
}: ChatHeaderProps) {
  const aiStatus = useAIStore((state) => state.aiStatus);

  const unreachable = aiStatus?.unreachable === true;
  const available = aiStatus?.available !== false;
  const dotClass = aiStatus === null ? 'ai-dot' : available ? 'ai-dot live' : 'ai-dot off';
  // "Not configured" (a reachable API without a key) and "unreachable" (no API
  // at all) are different problems and read differently.
  const statusText = aiStatus === null
    ? 'Checking assistant…'
    : unreachable
      ? 'Backend unreachable'
      : available
        ? `Live${aiStatus.model ? ` · ${aiStatus.model}` : ''}`
        : 'Provider not configured';

  return (
    <div className="ai-head">
      <span className={`ai-orb${available ? ' pulse' : ''}`} aria-hidden>
        NM
      </span>

      <div className="ai-head-text">
        <div className="ai-title">Market Assistant</div>
        <div className="ai-sub">
          <span className={dotClass} aria-hidden />
          <span>{statusText}</span>
          <span aria-hidden>·</span>
          <span title={context.route}>{getPageDescription(context)}</span>
        </div>
      </div>

      <div className="ai-head-actions">
        <button
          type="button"
          className="ai-icon-btn"
          onClick={onNewChat}
          disabled={!hasConversation}
          title="New conversation"
          aria-label="New conversation"
        >
          <Plus aria-hidden />
        </button>

        <button
          type="button"
          className="ai-icon-btn"
          onClick={onToggleHistory}
          title="Conversation history"
          aria-label="Conversation history"
        >
          <History aria-hidden />
        </button>

        <button
          type="button"
          className="ai-icon-btn"
          onClick={onToggleExpand}
          aria-pressed={isExpanded}
          title={isExpanded ? 'Collapse to the side rail' : 'Expand for a focused read'}
          aria-label={isExpanded ? 'Collapse panel' : 'Expand panel'}
        >
          {isExpanded ? <Minimize2 aria-hidden /> : <Maximize2 aria-hidden />}
        </button>

        <button
          type="button"
          className="ai-icon-btn"
          onClick={onClose}
          title="Close assistant"
          aria-label="Close assistant"
        >
          <X aria-hidden />
        </button>
      </div>
    </div>
  );
}

export default ChatHeader;
