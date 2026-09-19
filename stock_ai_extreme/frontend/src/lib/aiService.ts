/**
 * AI Service Layer (Phase 10)
 *
 * The single frontend entry point for the AI Financial Assistant. All model
 * traffic goes through the backend (`/api/ai/*`) — no provider key ever reaches
 * the browser (spec W).
 *
 * Responsibilities
 *   - typed request/response models
 *   - a real Server-Sent Events reader (event + data pairing, multi-line data,
 *     cancellation, keep-alive comments)
 *   - honest error classification so the UI can always offer an action
 *     (spec V: never leave the chat loading forever)
 */

import apiClient from './axios';

// ---------------------------------------------------------------------------
// Endpoint resolution
// ---------------------------------------------------------------------------

/**
 * `VITE_API_URL` holds a bare origin in this project (`http://127.0.0.1:8000`,
 * see `.env`) and is left unset in setups that go through the `/api` dev
 * proxy — so the `/api` prefix is ours to add. A base that already ends in
 * `/api` is accepted as well and never doubled.
 *
 * Every AI route must go through `aiUrl()`: resolving them straight against
 * `apiClient`'s baseURL silently drops the prefix and turns each assistant call
 * into a 404.
 */
const API_ORIGIN = (() => {
  const configured = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '');
  return configured.endsWith('/api') ? configured.slice(0, -4) : configured;
})();

export function aiUrl(path: string): string {
  return `${API_ORIGIN}/api${path.startsWith('/') ? path : `/${path}`}`;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type EntityType = 'stock' | 'index';

/** Everything the browser knows about what the user is looking at. */
export interface AIContext {
  route: string;
  symbol?: string;
  entity_type?: EntityType;
  timeframe?: string;
  include_news?: boolean;
  include_announcements?: boolean;
  include_sentiment?: boolean;
  include_portfolio?: boolean;
  user_id?: string;
}

export interface ChatRequest {
  question: string;
  conversation_id?: number;
  context?: AIContext;
  temperature?: number;
  stream?: boolean;
}

export interface ChatResponse {
  conversation_id: number;
  message_id: number;
  content: string;
  model: string;
  usage?: TokenUsage;
  processing_time_ms: number;
  context_used: Record<string, any>;
  citations?: Citation[];
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/**
 * A source the answer leaned on. The backend builds these from the context it
 * actually sent — a citation the app cannot attribute never appears (spec T).
 */
export interface Citation {
  kind: string;
  title: string;
  source?: string | null;
  published_at?: string | null;
  url?: string | null;
  symbol?: string | null;
  detail?: string | null;
}

export interface Message {
  id: number;
  role: 'user' | 'assistant' | 'system';
  content: string;
  context_used: Record<string, any>;
  citations: Citation[];
  token_usage?: TokenUsage | null;
  model?: string | null;
  processing_time_ms?: number | null;
  created_at: string;
  /** Local-only flags (never sent to or read from the backend). */
  pending?: boolean;
  failed?: boolean;
  /** True when the user stopped generation part-way through (spec L). */
  stopped?: boolean;
}

export interface Conversation {
  id: number;
  title: string;
  context_snapshot: Record<string, any>;
  created_at: string;
  updated_at: string;
  stats?: {
    total_messages: number;
    user_messages: number;
    assistant_messages: number;
    total_tokens: number;
  };
}

export interface AIStatus {
  available: boolean;
  provider?: string;
  model?: string;
  streaming_enabled?: boolean;
  voice_enabled?: boolean;
  max_conversation_messages?: number;
  error?: string;
  message?: string;
  /** Local-only: why the status could not be read. */
  status_error?: string;
  /**
   * Local-only: the backend itself could not be reached, as opposed to a
   * reachable backend that has no provider key. The two need different UI copy.
   */
  unreachable?: boolean;
}

export interface AgentTask {
  id: number;
  conversation_id: number | null;
  task_type: string;
  agent_name: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  input_params: Record<string, any>;
  result: Record<string, any> | null;
  error: string | null;
  execution_time_ms: number | null;
  created_at: string;
  completed_at: string | null;
}

/** Stream lifecycle as the UI understands it (spec L). */
export type StreamStatus = 'thinking' | 'streaming' | 'complete' | 'cancelled' | 'error';

export type ChatErrorCategory =
  | 'unavailable'
  | 'rate_limit'
  | 'timeout'
  | 'network'
  | 'backend'
  | 'empty_response'
  | 'aborted'
  | 'unknown';

export interface ChatError {
  category: ChatErrorCategory;
  message: string;
  /** True when offering the user a Retry button makes sense. */
  retryable: boolean;
  status?: number;
  requestId?: string;
}

export interface StreamComplete {
  conversation_id?: number;
  message_id?: number;
  full_content: string;
  model?: string;
  processing_time_ms?: number;
  usage?: TokenUsage | null;
  citations?: Citation[];
  stopped?: boolean;
}

export interface StreamHandlers {
  onStatus?: (status: StreamStatus, detail?: string) => void;
  onChunk?: (chunk: string) => void;
  onComplete?: (payload: StreamComplete) => void;
  onError?: (error: ChatError) => void;
}

// ---------------------------------------------------------------------------
// Error classification (spec V)
// ---------------------------------------------------------------------------

const CATEGORY_MESSAGES: Record<ChatErrorCategory, string> = {
  unavailable:
    'The assistant is not configured on this server yet. Add an AI provider key and restart the backend.',
  rate_limit: 'The AI provider is rate-limiting requests. Wait a moment, then retry.',
  timeout: 'The assistant took too long to answer. Retry, or ask a narrower question.',
  network: 'Could not reach the backend. Check your connection and retry.',
  backend: 'The assistant hit an error while answering. Retrying usually clears it.',
  empty_response: 'The assistant returned an empty answer. Retry to generate a new one.',
  aborted: 'Generation stopped.',
  unknown: 'Something went wrong while generating the answer. Retry to try again.',
};

export function makeChatError(
  category: ChatErrorCategory,
  overrides: Partial<ChatError> = {}
): ChatError {
  return {
    category,
    message: overrides.message || CATEGORY_MESSAGES[category],
    retryable: category !== 'aborted' && category !== 'unavailable',
    ...overrides,
  };
}

/** Map an HTTP failure onto an actionable category. */
export function classifyHttpError(status: number, detail?: string): ChatError {
  const hint = (detail || '').toLowerCase();
  if (status === 429) return makeChatError('rate_limit', { status });
  if (status === 504 || status === 408 || hint.includes('timeout') || hint.includes('timed out')) {
    return makeChatError('timeout', { status });
  }
  if (status === 401 || status === 403 || hint.includes('api key') || hint.includes('not configured')) {
    return makeChatError('unavailable', { status });
  }
  if (status >= 500) {
    return makeChatError('backend', { status, message: detail || undefined });
  }
  if (status === 400 || status === 422) {
    return makeChatError('backend', { status, message: detail || undefined, retryable: false });
  }
  return makeChatError('unknown', { status, message: detail || undefined });
}

/** Map a thrown fetch/axios error onto an actionable category. */
export function classifyThrownError(error: any): ChatError {
  const message: string = error?.message || '';
  if (error?.name === 'AbortError' || /aborted/i.test(message)) {
    return makeChatError('aborted', { message: CATEGORY_MESSAGES.aborted });
  }
  if (/timeout|ECONNABORTED|timed out/i.test(message)) return makeChatError('timeout');
  if (/network|failed to fetch|load failed|ECONNREFUSED/i.test(message)) return makeChatError('network');
  if (/not configured|api key/i.test(message)) return makeChatError('unavailable');
  return makeChatError('unknown', { message: message || CATEGORY_MESSAGES.unknown });
}

// ---------------------------------------------------------------------------
// Streaming (Server-Sent Events)
// ---------------------------------------------------------------------------

/** Parse one SSE block ("event: x\ndata: {...}") into its event type + payload. */
function parseSseBlock(block: string): { event: string; data: any } | null {
  let event = 'message';
  const dataLines: string[] = [];

  for (const rawLine of block.split('\n')) {
    const line = rawLine.trimEnd();
    if (!line || line.startsWith(':')) continue;

    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) return null;

  const payload = dataLines.join('\n');
  if (payload === '[DONE]') return { event: 'done', data: null };

  try {
    return { event, data: JSON.parse(payload) };
  } catch {
    return { event, data: { content: payload } };
  }
}

/**
 * Stream an assistant answer over SSE.
 *
 * The backend endpoint is a POST that accepts JSON and answers with
 * `text/event-stream`, so we read the body ourselves instead of using
 * EventSource (which cannot POST).
 *
 * Returns an abort function — the caller's "Stop generating" button (spec L).
 */
export function streamChatMessage(request: ChatRequest, handlers: StreamHandlers): () => void {
  const controller = new AbortController();
  let finished = false;

  const finish = (fn: () => void) => {
    if (finished) return;
    finished = true;
    fn();
  };

  void (async () => {
    try {
      const response = await fetch(aiUrl('/ai/stream'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ ...request, stream: true }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        let detail = text;
        try {
          detail = JSON.parse(text)?.detail ?? text;
        } catch {
          /* keep raw text */
        }
        const error = classifyHttpError(response.status, detail);
        finish(() => handlers.onError?.(error));
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        finish(() => handlers.onError?.(makeChatError('backend', { message: 'Streaming is unavailable in this browser.' })));
        return;
      }

      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      // Read until the stream closes. `buffer` keeps the trailing partial block.
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() ?? '';

        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (!parsed) continue;
          const { event, data } = parsed;

          if (event === 'status') {
            const status = (data?.status || 'thinking') as StreamStatus;
            handlers.onStatus?.(status, data?.detail);
          } else if (event === 'chunk') {
            if (typeof data?.content === 'string' && data.content.length > 0) {
              handlers.onChunk?.(data.content);
            }
          } else if (event === 'complete') {
            finish(() =>
              handlers.onComplete?.({
                conversation_id: data?.conversation_id,
                message_id: data?.message_id,
                full_content: typeof data?.full_content === 'string' ? data.full_content : '',
                model: data?.model,
                processing_time_ms: data?.processing_time_ms,
                usage: data?.usage ?? null,
                citations: Array.isArray(data?.citations) ? data.citations : [],
                stopped: Boolean(data?.stopped),
              })
            );
            return;
          } else if (event === 'error') {
            const category = (data?.category || 'backend') as ChatErrorCategory;
            finish(() =>
              handlers.onError?.(
                makeChatError(category, {
                  message: data?.error || data?.message,
                  status: data?.status,
                  requestId: data?.request_id,
                  retryable: data?.retryable !== false && category !== 'unavailable',
                })
              )
            );
            return;
          }
        }
      }

      // The stream ended without a `complete` event. An abort does not always
      // surface as a thrown AbortError — depending on timing Chrome can end the
      // read loop with `done: true` instead — so a self-initiated stop must be
      // recognised here too, otherwise the partial answer is misclassified as a
      // backend failure and thrown away.
      finish(() =>
        handlers.onError?.(
          controller.signal.aborted
            ? makeChatError('aborted')
            : makeChatError('backend', {
                message: 'The response stream ended early. Retry to generate the full answer.',
              })
        )
      );
    } catch (error: any) {
      if (error?.name === 'AbortError' || controller.signal.aborted) {
        finish(() => handlers.onError?.(makeChatError('aborted')));
        return;
      }
      finish(() => handlers.onError?.(classifyThrownError(error)));
    }
  })();

  return () => {
    // Abort only. The AbortError path below is what delivers the single
    // `aborted` event that resets the UI — marking the stream finished here
    // would swallow it and leave the chat stuck on "Stop generating" forever.
    controller.abort();
  };
}

// ---------------------------------------------------------------------------
// Non-streaming chat (fallback + API completeness)
// ---------------------------------------------------------------------------

export async function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  try {
    const response = await apiClient.post(aiUrl('/ai/chat'), { ...request, stream: false });
    return response.data;
  } catch (error: any) {
    throw Object.assign(new Error(error?.message || 'Chat failed'), classifyThrownError(error));
  }
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

export async function listConversations(
  userId?: string,
  page = 1,
  pageSize = 30
): Promise<{ conversations: Conversation[]; total: number; page: number; page_size: number }> {
  const params: Record<string, any> = { page, page_size: pageSize };
  if (userId) params.user_id = userId;

  const response = await apiClient.get(aiUrl('/ai/conversations'), { params });
  return response.data;
}

export async function createConversation(
  title?: string,
  contextSnapshot?: Record<string, any>
): Promise<Conversation> {
  const response = await apiClient.post(aiUrl('/ai/conversations'), {
    title,
    context_snapshot: contextSnapshot,
  });
  return response.data;
}

export async function getConversation(conversationId: number): Promise<Conversation> {
  const response = await apiClient.get(aiUrl(`/ai/conversations/${conversationId}`));
  return response.data;
}

export async function updateConversationTitle(conversationId: number, newTitle: string): Promise<void> {
  await apiClient.put(aiUrl(`/ai/conversations/${conversationId}`), { title: newTitle });
}

export async function deleteConversation(conversationId: number): Promise<void> {
  await apiClient.delete(aiUrl(`/ai/conversations/${conversationId}`));
}

export async function getConversationMessages(
  conversationId: number
): Promise<{ conversation_id: number; messages: Message[] }> {
  const response = await apiClient.get(aiUrl(`/ai/conversations/${conversationId}/messages`));
  return response.data;
}

// ---------------------------------------------------------------------------
// Prompts, status, agent tasks
// ---------------------------------------------------------------------------

export async function getSuggestedPrompts(context: AIContext): Promise<string[]> {
  try {
    const response = await apiClient.post(aiUrl('/ai/suggested-prompts'), { context });
    return Array.isArray(response.data?.prompts) ? response.data.prompts : [];
  } catch {
    // Prompts are a convenience — the UI falls back to local context prompts.
    return [];
  }
}

export async function getAIStatus(): Promise<AIStatus> {
  try {
    const response = await apiClient.get(aiUrl('/ai/status'));
    return response.data;
  } catch (error: any) {
    // A backend that cannot be reached is not a backend without a key: telling
    // the user to set AI_PROVIDER when the API is simply down sends them off in
    // the wrong direction, so the two get different UI copy.
    const classified = classifyThrownError(error);
    const backendDown = classified.category === 'network' || classified.category === 'timeout';
    return {
      available: false,
      unreachable: backendDown || undefined,
      error: backendDown ? 'Assistant backend unreachable' : 'Failed to check AI status',
      message: backendDown
        ? 'Could not reach the assistant backend. The rest of the terminal keeps working.'
        : 'Could not read assistant status from the backend.',
      status_error: error?.message,
    };
  }
}

export async function listAgentTasks(conversationId?: number, limit = 50): Promise<AgentTask[]> {
  const params: Record<string, any> = { limit };
  if (conversationId) params.conversation_id = conversationId;

  const response = await apiClient.get(aiUrl('/ai/agent-tasks'), { params });
  return response.data?.tasks ?? [];
}
