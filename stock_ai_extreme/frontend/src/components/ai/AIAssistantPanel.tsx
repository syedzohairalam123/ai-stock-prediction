/**
 * AIAssistantPanel — the assistant itself (spec B / C / Z).
 *
 * Desktop : a docked right rail for the chat, with an optional expanded mode
 *           for reading a long analysis without a cramped column.
 * Tablet  : the same rail, narrower.
 * Mobile  : a full-screen sheet with a keyboard-safe composer.
 *
 * The panel owns the two live objects every child needs — the current view
 * context and the chat session — and passes them down. It never talks to the
 * AI provider directly; everything goes through the backend API.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useAIContext } from '../../hooks/useAIContext';
import { useChat } from '../../hooks/useChat';
import { getAIStatus } from '../../lib/aiService';
import { getPseSessionStatus } from '../../utils/marketHours';
import { useAIStore } from '../../store/useAIStore';
import { ChatHeader } from './ChatHeader';
import { ContextIndicator } from './ContextIndicator';
import { MessageList } from './MessageList';
import { ChatComposer } from './ChatComposer';
import { ConversationHistory } from './ConversationHistory';

const MOBILE_QUERY = '(max-width: 900px)';

export function AIAssistantPanel() {
  const isPanelOpen = useAIStore((state) => state.isPanelOpen);
  const isExpanded = useAIStore((state) => state.isExpanded);
  const isHistoryDrawerOpen = useAIStore((state) => state.isHistoryDrawerOpen);
  const currentConversationId = useAIStore((state) => state.currentConversationId);
  const messages = useAIStore((state) => state.messages);
  const openPanel = useAIStore((state) => state.openPanel);
  const closePanel = useAIStore((state) => state.closePanel);
  const toggleExpanded = useAIStore((state) => state.toggleExpanded);
  const setHistoryDrawer = useAIStore((state) => state.setHistoryDrawer);
  const toggleHistoryDrawer = useAIStore((state) => state.toggleHistoryDrawer);
  const startNewConversation = useAIStore((state) => state.startNewConversation);
  const setAIStatus = useAIStore((state) => state.setAIStatus);
  const setExpanded = useAIStore((state) => state.setExpanded);

  const dockRef = useRef<HTMLDivElement>(null);

  const context = useAIContext();
  const chat = useChat(context);

  // Tracked reactively so a rotated phone or a resized window switches layout
  // without leaving a stray backdrop behind.
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
  );

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const onChange = (event: MediaQueryListEvent) => setIsMobile(event.matches);
    media.addEventListener('change', onChange);
    setIsMobile(media.matches);
    return () => media.removeEventListener('change', onChange);
  }, []);

  // Prefer the backend's own reading of market state for the last answer; fall
  // back to this device's session clock before the first answer arrives.
  const marketStatus = useMemo(() => {
    const latest = [...messages]
      .reverse()
      .find((message) => message.role === 'assistant' && message.context_used?.market_status);
    return (latest?.context_used?.market_status as string | undefined) ?? getPseSessionStatus();
  }, [messages]);

  // Refresh provider status whenever the panel opens — a key added on the
  // backend should show up without a full page reload.
  useEffect(() => {
    if (!isPanelOpen) return;
    let cancelled = false;
    getAIStatus().then((status) => {
      if (!cancelled) setAIStatus(status);
    });
    return () => {
      cancelled = true;
    };
  }, [isPanelOpen, setAIStatus]);

  // Lock page scroll behind the mobile sheet.
  useEffect(() => {
    if (!isPanelOpen) return;
    const media = window.matchMedia(MOBILE_QUERY);
    const apply = () => {
      document.body.style.overflow = isPanelOpen && media.matches ? 'hidden' : '';
    };
    apply();
    media.addEventListener('change', apply);
    return () => {
      media.removeEventListener('change', apply);
      document.body.style.overflow = '';
    };
  }, [isPanelOpen]);

  // Keep the composer above the on-screen keyboard (spec Z).
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport || !isPanelOpen) return;

    const onViewportChange = () => {
      const keyboardOpen = window.innerHeight - viewport.height > 120;
      dockRef.current?.classList.toggle('keyboard', keyboardOpen);
    };

    viewport.addEventListener('resize', onViewportChange);
    onViewportChange();
    return () => viewport.removeEventListener('resize', onViewportChange);
  }, [isPanelOpen]);

  // Escape closes the innermost surface first: drawer → expanded → panel.
  useEffect(() => {
    if (!isPanelOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (isHistoryDrawerOpen) setHistoryDrawer(false);
      else if (isExpanded) setExpanded(false);
      else closePanel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [closePanel, isExpanded, isHistoryDrawerOpen, isPanelOpen, setExpanded, setHistoryDrawer]);

  if (!isPanelOpen) {
    return (
      <button
        type="button"
        className="ai-launcher"
        onClick={openPanel}
        title="Open the market assistant"
      >
        <span className="ai-orb pulse" aria-hidden>
          NM
        </span>
        Ask the assistant
        <span className="ai-launcher-nudge" aria-hidden />
      </button>
    );
  }

  const showBackdrop = isHistoryDrawerOpen || (isExpanded && !isMobile);

  return (
    <>
      {showBackdrop && (
        <button
          type="button"
          className="ai-backdrop"
          aria-label="Close overlay"
          onClick={() => {
            if (isHistoryDrawerOpen) setHistoryDrawer(false);
            else setExpanded(false);
          }}
        />
      )}

      <div
        className={`ai-dock${isExpanded ? ' wide' : ''}`}
        ref={dockRef}
        role="complementary"
        aria-label="AI market assistant"
      >
        <div className="ai-panel">
          <ChatHeader
            context={context}
            onClose={closePanel}
            onToggleHistory={toggleHistoryDrawer}
            onNewChat={() => startNewConversation()}
            isExpanded={isExpanded}
            onToggleExpand={toggleExpanded}
            hasConversation={messages.length > 0 || currentConversationId !== null}
          />

          <ContextIndicator context={context} marketStatus={marketStatus} />

          <MessageList context={context} chat={chat} />

          <ChatComposer context={context} chat={chat} />
        </div>
      </div>

      {isHistoryDrawerOpen && (
        <ConversationHistory onClose={() => setHistoryDrawer(false)} />
      )}
    </>
  );
}

/** Floating launcher, exported for layouts that want to place it themselves. */
export function AIAssistantLauncher() {
  const isPanelOpen = useAIStore((state) => state.isPanelOpen);
  const openPanel = useAIStore((state) => state.openPanel);

  if (isPanelOpen) return null;

  return (
    <button type="button" className="ai-launcher" onClick={openPanel} title="Open the market assistant">
      <span className="ai-orb pulse" aria-hidden>
        NM
      </span>
      Ask the assistant
      <span className="ai-launcher-nudge" aria-hidden />
    </button>
  );
}

export default AIAssistantPanel;
