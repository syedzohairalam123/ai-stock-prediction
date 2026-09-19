/**
 * useChat — the assistant conversation engine (Phase 10)
 *
 * Owns the full lifecycle of a question:
 *   send → optimistic user message → context → stream → persisted answer
 * plus the two recovery paths the UI must always offer: Stop generating and
 * Retry (spec L / V). Components only render; they never touch the network.
 */

import { useCallback, useMemo, useRef } from 'react';
import {
  AIContext,
  ChatError,
  Citation,
  Message,
  createConversation,
  getConversation,
  makeChatError,
  streamChatMessage,
} from '../lib/aiService';
import { useAIStore } from '../store/useAIStore';

export interface UseChatResult {
  messages: Message[];
  status: ReturnType<typeof useAIStore.getState>['streamingStatus'];
  streamingContent: string;
  error: ChatError | null;
  isStreaming: boolean;
  canRetry: boolean;
  send: (question: string) => void;
  stop: () => void;
  retry: () => void;
  clear: () => void;
}

const generateMessageId = () => -Math.floor(Date.now() + Math.random() * 1000);

export function useChat(context: AIContext): UseChatResult {
  // Context is read at send time so a route change never sends stale context.
  const contextRef = useRef(context);
  contextRef.current = context;

  const busyRef = useRef(false);

  const store = useAIStore;
  const messages = useAIStore((state) => state.messages);
  const status = useAIStore((state) => state.streamingStatus);
  const streamingContent = useAIStore((state) => state.streamingContent);
  const error = useAIStore((state) => state.streamingError);
  const retryQuestion = useAIStore((state) => state.retryQuestion);

  const isStreaming = status === 'thinking' || status === 'streaming';

  const systemPromptFor = useCallback((question: string): Message => {
    return {
      id: generateMessageId(),
      role: 'user',
      content: question,
      context_used: {},
      citations: [],
      created_at: new Date().toISOString(),
      pending: true,
    };
  }, []);

  /** Ask the assistant. `optimisticUserMessage` is false when retrying. */
  const runQuestion = useCallback(
    (question: string, appendUserMessage: boolean) => {
      const state = store.getState();
      const currentContext = contextRef.current;

      if (!question.trim() || busyRef.current) return;

      // Without a configured provider there is nothing to stream — surface the
      // setup problem immediately instead of showing an endless spinner.
      const aiStatus = state.aiStatus;
      if (aiStatus && aiStatus.available === false) {
        state.setStreamingError(
          makeChatError('unavailable', {
            message:
              aiStatus.message ||
              'The assistant is not configured yet. Add an AI provider key on the backend to enable it.',
            retryable: false,
          })
        );
        state.setStreamingStatus('error');
        return;
      }

      busyRef.current = true;
      state.setRetryQuestion(question);
      state.setStreamingError(null);
      state.setStreamingContent('');
      state.setStreamingStatus('thinking');

      if (appendUserMessage) {
        state.addMessage(systemPromptFor(question));
      }

      const startedAt = Date.now();

      const startStream = (conversationId: number | null) => {
        const cancel = streamChatMessage(
          {
            question,
            conversation_id: conversationId ?? undefined,
            context: currentContext,
            temperature: 0.4,
            stream: true,
          },
          {
            onStatus: (next) => {
              const live = store.getState();
              if (next === 'thinking') live.setStreamingStatus('thinking');
              else if (next === 'streaming') live.setStreamingStatus('streaming');
            },
            onChunk: (chunk) => {
              const live = store.getState();
              live.appendStreamingContent(chunk);
              if (live.streamingStatus !== 'streaming') live.setStreamingStatus('streaming');
            },
            onComplete: (payload) => {
              const live = store.getState();
              const content = (payload.full_content || live.streamingContent || '').trim();

              if (!content) {
                live.setStreamingStatus('error');
                live.setStreamingError(makeChatError('empty_response'));
                live.setStreamingContent('');
                busyRef.current = false;
                return;
              }

              const resolvedId = payload.conversation_id ?? live.currentConversationId;
              if (resolvedId) live.setCurrentConversation(resolvedId);

              live.addMessage({
                id: payload.message_id ?? generateMessageId(),
                role: 'assistant',
                content,
                context_used: currentContext as unknown as Record<string, any>,
                citations: (payload.citations ?? []) as Citation[],
                model: payload.model,
                processing_time_ms: payload.processing_time_ms ?? Date.now() - startedAt,
                token_usage: payload.usage ?? null,
                created_at: new Date().toISOString(),
              });

              // The optimistic user bubble is now persisted server-side.
              live.messages
                .filter((message) => message.pending)
                .forEach((message) => live.updateMessage(message.id, { pending: false }));

              live.setStreamingStatus('idle');
              live.setStreamingContent('');
              live.setStreamingError(null);
              busyRef.current = false;

              if (resolvedId) void refreshConversationMeta(resolvedId);
            },
            onError: (chatError) => {
              const live = store.getState();
              const partial = live.streamingContent.trim();

              if (chatError.category === 'aborted') {
                // Preserve what was already generated so a stop never loses text.
                if (partial) {
                  live.addMessage({
                    id: generateMessageId(),
                    role: 'assistant',
                    content: partial,
                    context_used: currentContext as unknown as Record<string, any>,
                    citations: [],
                    model: undefined,
                    processing_time_ms: Date.now() - startedAt,
                    created_at: new Date().toISOString(),
                    stopped: true,
                  });
                  live.setStreamingStatus('idle');
                  live.setStreamingContent('');
                  live.setStreamingError(null);
                } else {
                  // Nothing had been generated yet. Going silently idle here read
                  // as "the assistant is not replying" — surface the stop instead
                  // so the thread always explains itself and offers a retry.
                  live.setStreamingStatus('error');
                  live.setStreamingError(makeChatError('aborted', { retryable: true }));
                }
              } else {
                live.setStreamingStatus('error');
                live.setStreamingError(chatError);
                live.setStreamingContent('');
              }

              busyRef.current = false;
            },
          }
        );

        store.getState().setCancelStream(cancel);
      };

      const conversationId = state.currentConversationId;
      if (conversationId) {
        startStream(conversationId);
        return;
      }

      // First turn of a new conversation: create it so the server can title it.
      void (async () => {
        try {
          const conversation = await createConversation(undefined, currentContext as unknown as Record<string, any>);
          const live = store.getState();
          live.setCurrentConversation(conversation.id);
          live.addConversation(conversation);
          live.setContextSnapshot(currentContext as unknown as Record<string, any>);
          startStream(conversation.id);
        } catch (conversationError: any) {
          const live = store.getState();
          live.setStreamingStatus('error');
          live.setStreamingError(
            makeChatError('backend', {
              message:
                conversationError?.message ||
                'Could not start a conversation. The assistant backend did not respond.',
            })
          );
          busyRef.current = false;
        }
      })();
    },
    [store, systemPromptFor]
  );

  const refreshConversationMeta = useCallback(
    async (conversationId: number) => {
      try {
        const conversation = await getConversation(conversationId);
        store.getState().updateConversation(conversationId, {
          title: conversation.title,
          updated_at: conversation.updated_at,
          stats: conversation.stats,
        });
      } catch {
        // Title refresh is cosmetic — the answer is already on screen.
      }
    },
    [store]
  );

  const send = useCallback(
    (question: string) => {
      runQuestion(question.trim(), true);
    },
    [runQuestion]
  );

  const stop = useCallback(() => {
    const state = store.getState();
    state.cancelStream?.();
    state.setCancelStream(null);
    busyRef.current = false;
  }, [store]);

  /**
   * Retry re-asks the previous question: the failed answer is dropped first so
   * the thread never accumulates duplicate answers.
   */
  const retry = useCallback(() => {
    const state = store.getState();
    if (busyRef.current) return;

    const question =
      state.retryQuestion ??
      [...state.messages].reverse().find((message) => message.role === 'user')?.content;
    if (!question) return;

    const lastMessage = state.messages[state.messages.length - 1];
    if (lastMessage && lastMessage.role === 'assistant') {
      state.removeMessagesFrom(lastMessage.id);
    }

    runQuestion(question, false);
  }, [runQuestion, store]);

  const clear = useCallback(() => {
    store.getState().startNewConversation();
  }, [store]);

  const canRetry = useMemo(
    () => Boolean(retryQuestion) || messages.some((message) => message.role === 'user'),
    [retryQuestion, messages]
  );

  return { messages, status, streamingContent, error, isStreaming, canRetry, send, stop, retry, clear };
}
