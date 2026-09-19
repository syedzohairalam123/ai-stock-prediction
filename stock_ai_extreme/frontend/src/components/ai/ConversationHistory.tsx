/**
 * ConversationHistory — the assistant's left drawer (spec N).
 *
 * New / open / rename / delete for every stored conversation, plus search and
 * day grouping. Renames are optimistic-then-confirmed; deletes ask once, in
 * place, instead of firing a browser confirm dialog.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Check,
  MessageCircle,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import {
  Conversation,
  deleteConversation,
  getConversationMessages,
  listConversations,
  updateConversationTitle,
} from '../../lib/aiService';
import { formatDayGroup, formatRelativeTime } from '../../utils/dateFormat';
import { useAIStore } from '../../store/useAIStore';

interface ConversationHistoryProps {
  onClose: () => void;
}

export function ConversationHistory({ onClose }: ConversationHistoryProps) {
  const conversations = useAIStore((state) => state.conversations);
  const setConversations = useAIStore((state) => state.setConversations);
  const setCurrentConversation = useAIStore((state) => state.setCurrentConversation);
  const setMessages = useAIStore((state) => state.setMessages);
  const removeConversation = useAIStore((state) => state.removeConversation);
  const updateConversation = useAIStore((state) => state.updateConversation);
  const startNewConversation = useAIStore((state) => state.startNewConversation);
  const currentConversationId = useAIStore((state) => state.currentConversationId);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listConversations();
      setConversations(result.conversations ?? []);
    } catch (error: any) {
      setLoadError(error?.message || 'Could not load conversation history.');
    } finally {
      setLoading(false);
    }
  }, [setConversations]);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = needle
      ? conversations.filter((conversation) =>
          (conversation.title || '').toLowerCase().includes(needle)
        )
      : conversations;

    return filtered.reduce<Array<{ label: string; items: Conversation[] }>>((groups, conversation) => {
      const label = formatDayGroup(conversation.updated_at);
      const existing = groups.find((group) => group.label === label);
      if (existing) existing.items.push(conversation);
      else groups.push({ label, items: [conversation] });
      return groups;
    }, []);
  }, [conversations, query]);

  const handleOpen = async (conversation: Conversation) => {
    setOpenError(null);
    setCurrentConversation(conversation.id);
    setMessages([]);
    try {
      const result = await getConversationMessages(conversation.id);
      setMessages(result.messages ?? []);
      onClose();
    } catch (error: any) {
      setOpenError(error?.message || 'Could not open that conversation.');
    }
  };

  const handleRenameSave = async (conversation: Conversation) => {
    const title = renameValue.trim();
    setRenamingId(null);
    if (!title || title === conversation.title) return;

    const previous = conversation.title;
    updateConversation(conversation.id, { title });
    try {
      await updateConversationTitle(conversation.id, title);
    } catch {
      updateConversation(conversation.id, { title: previous }); // revert on failure
      setOpenError('Rename failed — the title was restored.');
    }
  };

  const handleDelete = async (conversation: Conversation) => {
    setConfirmingDeleteId(null);
    try {
      await deleteConversation(conversation.id);
      removeConversation(conversation.id);
    } catch (error: any) {
      setOpenError(error?.message || 'Could not delete that conversation.');
    }
  };

  const handleNewChat = () => {
    startNewConversation();
    onClose();
  };

  return (
    <aside className="ai-drawer" aria-label="Conversation history">
      <div className="ai-drawer-head">
        <span className="ai-drawer-title">Conversations</span>
        <button
          type="button"
          className="ai-icon-btn"
          onClick={() => void load()}
          title="Refresh list"
          aria-label="Refresh conversation list"
        >
          <RefreshCw aria-hidden />
        </button>
        <button
          type="button"
          className="ai-icon-btn"
          onClick={onClose}
          title="Close history"
          aria-label="Close history"
        >
          <X aria-hidden />
        </button>
      </div>

      <div className="ai-drawer-search">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search conversations…"
          aria-label="Search conversations"
        />
      </div>

      {openError && (
        <div className="ai-notice" role="alert">
          <AlertTriangle aria-hidden />
          <span>{openError}</span>
        </div>
      )}

      <div className="ai-drawer-body">
        {loading && <div className="ai-state">Loading conversations…</div>}

        {!loading && loadError && (
          <div className="ai-state">
            <AlertTriangle aria-hidden />
            <div>{loadError}</div>
            <button type="button" className="ai-btn sm" onClick={() => void load()} style={{ marginTop: 10 }}>
              Try again
            </button>
          </div>
        )}

        {!loading && !loadError && conversations.length === 0 && (
          <div className="ai-state">
            <MessageCircle aria-hidden />
            <div>No saved conversations yet. Ask something and it will be stored here.</div>
          </div>
        )}

        {!loading && !loadError && conversations.length > 0 && grouped.length === 0 && (
          <div className="ai-state">No conversation matches “{query}”.</div>
        )}

        {grouped.map((group) => (
          <div key={group.label}>
            <div className="ai-group-label">{group.label}</div>
            {group.items.map((conversation) => {
              const active = conversation.id === currentConversationId;
              const renaming = renamingId === conversation.id;
              const confirming = confirmingDeleteId === conversation.id;

              return (
                <div
                  key={conversation.id}
                  className={`ai-conv${active ? ' active' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => !renaming && void handleOpen(conversation)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      if (!renaming) void handleOpen(conversation);
                    }
                  }}
                  aria-current={active}
                >
                  <MessageCircle aria-hidden />

                  <div className="ai-conv-main">
                    {renaming ? (
                      <div className="ai-inline-form" onClick={(event) => event.stopPropagation()}>
                        <input
                          value={renameValue}
                          autoFocus
                          onChange={(event) => setRenameValue(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') void handleRenameSave(conversation);
                            if (event.key === 'Escape') setRenamingId(null);
                          }}
                          aria-label="Conversation title"
                        />
                        <button
                          type="button"
                          className="ai-icon-btn"
                          onClick={() => void handleRenameSave(conversation)}
                          title="Save title"
                        >
                          <Check aria-hidden />
                        </button>
                        <button
                          type="button"
                          className="ai-icon-btn"
                          onClick={() => setRenamingId(null)}
                          title="Cancel rename"
                        >
                          <X aria-hidden />
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="ai-conv-title">{conversation.title || 'Untitled conversation'}</div>
                        <div className="ai-conv-meta">
                          <span>{formatRelativeTime(conversation.updated_at)}</span>
                          {conversation.stats?.total_messages ? (
                            <span>{conversation.stats.total_messages} msgs</span>
                          ) : null}
                        </div>
                      </>
                    )}

                    {confirming && (
                      <div className="ai-inline-form" onClick={(event) => event.stopPropagation()}>
                        <span style={{ fontSize: 11.5, color: 'var(--text2)' }}>Delete this?</span>
                        <button
                          type="button"
                          className="ai-btn sm"
                          onClick={() => void handleDelete(conversation)}
                        >
                          Yes
                        </button>
                        <button
                          type="button"
                          className="ai-btn sm"
                          onClick={() => setConfirmingDeleteId(null)}
                        >
                          No
                        </button>
                      </div>
                    )}
                  </div>

                  {!renaming && !confirming && (
                    <span className="ai-conv-actions">
                      <button
                        type="button"
                        className="ai-icon-btn"
                        title="Rename conversation"
                        aria-label="Rename conversation"
                        onClick={(event) => {
                          event.stopPropagation();
                          setRenamingId(conversation.id);
                          setRenameValue(conversation.title || '');
                        }}
                      >
                        <Pencil aria-hidden />
                      </button>
                      <button
                        type="button"
                        className="ai-icon-btn"
                        title="Delete conversation"
                        aria-label="Delete conversation"
                        onClick={(event) => {
                          event.stopPropagation();
                          setConfirmingDeleteId(conversation.id);
                        }}
                      >
                        <Trash2 aria-hidden />
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div className="ai-drawer-foot">
        <button type="button" className="ai-btn pri full" onClick={handleNewChat}>
          <Plus aria-hidden />
          New conversation
        </button>
      </div>
    </aside>
  );
}

export default ConversationHistory;
