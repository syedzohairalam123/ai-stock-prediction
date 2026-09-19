/**
 * Phase 12 — AI Assistant widget (spec §3, §4 AI_ASSISTANT).
 *
 * An *embedded* assistant: the same live pipeline the Phase-10 rail uses
 * (`useChat` + `useAIContext` through the backend API), rendered inside the
 * widget frame instead of a docked rail. The chat shares the global store's
 * conversation deliberately — the widget and the rail are two views of the
 * same assistant, so an answer started in one continues in the other.
 */
import { useAIContext } from "../../../hooks/useAIContext";
import { useChat } from "../../../hooks/useChat";
import { getAIStatus } from "../../../lib/aiService";
import { getPseSessionStatus } from "../../../utils/marketHours";
import { useAIStore } from "../../../store/useAIStore";
import { ChatHeader } from "../../ai/ChatHeader";
import { ContextIndicator } from "../../ai/ContextIndicator";
import { MessageList } from "../../ai/MessageList";
import { ChatComposer } from "../../ai/ChatComposer";
import { useEffect } from "react";

export default function AIAssistantWidget() {
  const context = useAIContext();
  const chat = useChat(context);

  const isPanelOpen = useAIStore((state) => state.isPanelOpen);
  const isExpanded = useAIStore((state) => state.isExpanded);
  const setAIStatus = useAIStore((state) => state.setAIStatus);
  const aiStatus = useAIStore((state) => state.aiStatus);

  // Keep provider status fresh in the widget too (the rail refreshes on open;
  // the widget refreshes on mount and whenever the rail closes).
  useEffect(() => {
    if (isPanelOpen) return;
    let cancelled = false;
    getAIStatus().then((status) => {
      if (!cancelled) setAIStatus(status);
    });
    return () => {
      cancelled = true;
    };
  }, [isPanelOpen, setAIStatus]);

  const marketStatus = getPseSessionStatus();

  return (
    <div className="ws-widget-body ws-ai-widget">
      <div className="ai-panel">
        <ChatHeader
          context={context}
          onClose={() => {
            /* embedded: the widget frame owns closing, not the store */
          }}
          onToggleHistory={() => {
            /* history drawer is a rail surface; embedded hides it */
          }}
          onNewChat={() => chat.clear()}
          isExpanded={isExpanded}
          onToggleExpand={() => {
            /* embedded: expansion is the host widget's maximize control */
          }}
          hasConversation={chat.messages.length > 0}
        />
        <ContextIndicator context={context} marketStatus={marketStatus} />
        {aiStatus?.unreachable && (
          <p className="ws-ai-unreachable" role="status">
            Assistant backend unreachable — start the API to chat.
          </p>
        )}
        <MessageList context={context} chat={chat} />
        <ChatComposer context={context} chat={chat} />
      </div>
    </div>
  );
}
