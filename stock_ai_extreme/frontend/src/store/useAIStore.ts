/**
 * AI Assistant Store (Phase 10)
 *
 * One store for the whole assistant surface: panel visibility, the active
 * conversation, message list, streaming lifecycle, voice state and the retry
 * target. Keeping this in one place is what lets every chat component read the
 * same truth instead of each holding its own copy.
 */

import { create } from 'zustand';
import { AIStatus, ChatError, Conversation, Message, StreamStatus } from '../lib/aiService';

export type VoiceStatus = 'idle' | 'listening' | 'processing' | 'unsupported';
export type StreamingStatus = StreamStatus | 'idle';

export interface AIAssistantState {
  // ---- UI ----
  isPanelOpen: boolean;
  isExpanded: boolean;
  isHistoryDrawerOpen: boolean;

  // ---- Conversation ----
  currentConversationId: number | null;
  conversations: Conversation[];
  messages: Message[];
  contextSnapshot: Record<string, any> | null;

  // ---- Streaming ----
  streamingStatus: StreamingStatus;
  streamingContent: string;
  streamingError: ChatError | null;
  /** Abort handle for the in-flight answer ("Stop generating"). */
  cancelStream: (() => void) | null;
  /** Question to re-ask when the user taps Retry. */
  retryQuestion: string | null;

  // ---- Service status ----
  aiStatus: AIStatus | null;
  isLoadingStatus: boolean;

  // ---- Voice ----
  voiceStatus: VoiceStatus;
  voiceError: string | null;

  // ---- UI actions ----
  togglePanel: () => void;
  openPanel: () => void;
  closePanel: () => void;
  toggleExpanded: () => void;
  setExpanded: (expanded: boolean) => void;
  toggleHistoryDrawer: () => void;
  setHistoryDrawer: (open: boolean) => void;

  // ---- Conversation actions ----
  setCurrentConversation: (id: number | null) => void;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversation: (id: number, updates: Partial<Conversation>) => void;
  removeConversation: (id: number) => void;
  setContextSnapshot: (snapshot: Record<string, any> | null) => void;

  // ---- Message actions ----
  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  updateMessage: (id: number, updates: Partial<Message>) => void;
  removeMessagesFrom: (id: number) => void;
  clearMessages: () => void;
  startNewConversation: () => void;

  // ---- Streaming actions ----
  setStreamingStatus: (status: StreamingStatus) => void;
  setStreamingContent: (content: string) => void;
  appendStreamingContent: (chunk: string) => void;
  setStreamingError: (error: ChatError | null) => void;
  setCancelStream: (cancel: (() => void) | null) => void;
  setRetryQuestion: (question: string | null) => void;
  resetStreaming: () => void;

  // ---- Status actions ----
  setAIStatus: (status: AIStatus) => void;
  setLoadingStatus: (loading: boolean) => void;

  // ---- Voice actions ----
  setVoiceStatus: (status: VoiceStatus) => void;
  setVoiceError: (error: string | null) => void;

  // ---- Reset ----
  resetAll: () => void;
}

const PANEL_STORAGE_KEY = 'nm.ai.panelOpen';

function readPanelPreference(): boolean {
  try {
    return window.localStorage.getItem(PANEL_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function writePanelPreference(open: boolean): void {
  try {
    window.localStorage.setItem(PANEL_STORAGE_KEY, open ? '1' : '0');
  } catch {
    /* storage disabled — preference is simply not remembered */
  }
}

export const useAIStore = create<AIAssistantState>((set, get) => ({
  // ---- UI ----
  isPanelOpen: typeof window === 'undefined' ? false : readPanelPreference(),
  isExpanded: false,
  isHistoryDrawerOpen: false,

  // ---- Conversation ----
  currentConversationId: null,
  conversations: [],
  messages: [],
  contextSnapshot: null,

  // ---- Streaming ----
  streamingStatus: 'idle',
  streamingContent: '',
  streamingError: null,
  cancelStream: null,
  retryQuestion: null,

  // ---- Status ----
  aiStatus: null,
  isLoadingStatus: false,

  // ---- Voice ----
  voiceStatus: 'idle',
  voiceError: null,

  // ---- UI actions ----
  togglePanel: () => {
    const next = !get().isPanelOpen;
    writePanelPreference(next);
    set({ isPanelOpen: next, isHistoryDrawerOpen: next ? get().isHistoryDrawerOpen : false });
  },
  openPanel: () => {
    writePanelPreference(true);
    set({ isPanelOpen: true });
  },
  closePanel: () => {
    writePanelPreference(false);
    set({ isPanelOpen: false, isHistoryDrawerOpen: false, isExpanded: false });
  },
  toggleExpanded: () => set((state) => ({ isExpanded: !state.isExpanded })),
  setExpanded: (expanded) => set({ isExpanded: expanded }),
  toggleHistoryDrawer: () => set((state) => ({ isHistoryDrawerOpen: !state.isHistoryDrawerOpen })),
  setHistoryDrawer: (open) => set({ isHistoryDrawerOpen: open }),

  // ---- Conversation actions ----
  setCurrentConversation: (id) => set({ currentConversationId: id }),

  setConversations: (conversations) => set({ conversations }),

  addConversation: (conversation) =>
    set((state) => ({
      conversations: [conversation, ...state.conversations.filter((c) => c.id !== conversation.id)],
    })),

  updateConversation: (id, updates) =>
    set((state) => ({
      conversations: state.conversations.map((conversation) =>
        conversation.id === id ? { ...conversation, ...updates } : conversation
      ),
    })),

  removeConversation: (id) =>
    set((state) => ({
      conversations: state.conversations.filter((conversation) => conversation.id !== id),
      currentConversationId: state.currentConversationId === id ? null : state.currentConversationId,
      messages: state.currentConversationId === id ? [] : state.messages,
    })),

  setContextSnapshot: (snapshot) => set({ contextSnapshot: snapshot }),

  // ---- Message actions ----
  setMessages: (messages) => set({ messages }),

  addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),

  updateMessage: (id, updates) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id ? { ...message, ...updates } : message
      ),
    })),

  /** Drop a message and everything after it (used when retrying an answer). */
  removeMessagesFrom: (id) =>
    set((state) => {
      const index = state.messages.findIndex((message) => message.id === id);
      return index === -1 ? state : { messages: state.messages.slice(0, index) };
    }),

  clearMessages: () => set({ messages: [] }),

  startNewConversation: () =>
    set({
      currentConversationId: null,
      messages: [],
      streamingStatus: 'idle',
      streamingContent: '',
      streamingError: null,
      retryQuestion: null,
      cancelStream: null,
      contextSnapshot: null,
    }),

  // ---- Streaming actions ----
  setStreamingStatus: (status) => set({ streamingStatus: status }),
  setStreamingContent: (content) => set({ streamingContent: content }),
  appendStreamingContent: (chunk) =>
    set((state) => ({ streamingContent: state.streamingContent + chunk })),
  setStreamingError: (error) => set({ streamingError: error }),
  setCancelStream: (cancel) => set({ cancelStream: cancel }),
  setRetryQuestion: (question) => set({ retryQuestion: question }),
  resetStreaming: () =>
    set({
      streamingStatus: 'idle',
      streamingContent: '',
      streamingError: null,
      cancelStream: null,
    }),

  // ---- Status actions ----
  setAIStatus: (status) => set({ aiStatus: status }),
  setLoadingStatus: (loading) => set({ isLoadingStatus: loading }),

  // ---- Voice actions ----
  setVoiceStatus: (status) => set({ voiceStatus: status }),
  setVoiceError: (error) => set({ voiceError: error }),

  // ---- Reset ----
  resetAll: () =>
    set({
      isExpanded: false,
      isHistoryDrawerOpen: false,
      currentConversationId: null,
      conversations: [],
      messages: [],
      contextSnapshot: null,
      streamingStatus: 'idle',
      streamingContent: '',
      streamingError: null,
      cancelStream: null,
      retryQuestion: null,
      voiceStatus: 'idle',
      voiceError: null,
    }),
}));

/** Selector hooks — narrow subscriptions keep long chats cheap to re-render. */
export const useIsPanelOpen = () => useAIStore((state) => state.isPanelOpen);
export const useIsExpanded = () => useAIStore((state) => state.isExpanded);
export const useIsHistoryDrawerOpen = () => useAIStore((state) => state.isHistoryDrawerOpen);
export const useCurrentConversationId = () => useAIStore((state) => state.currentConversationId);
export const useConversations = () => useAIStore((state) => state.conversations);
export const useMessages = () => useAIStore((state) => state.messages);
export const useStreamingStatus = () => useAIStore((state) => state.streamingStatus);
export const useStreamingContent = () => useAIStore((state) => state.streamingContent);
export const useStreamingError = () => useAIStore((state) => state.streamingError);
export const useAIStatus = () => useAIStore((state) => state.aiStatus);
export const useVoiceStatus = () => useAIStore((state) => state.voiceStatus);
