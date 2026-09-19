/**
 * SuggestedPrompts — context-aware questions for the current page (spec J).
 *
 * Prompts come from the backend builder, with a local fallback so the empty
 * state is never blank when the backend cannot be reached. Selecting a prompt
 * sends it immediately — the user never has to copy text into the composer.
 */

import { useEffect, useState } from 'react';
import { Lightbulb, Sparkles } from 'lucide-react';
import { AIContext, getSuggestedPrompts } from '../../lib/aiService';
import { getLocalPrompts } from '../../hooks/useAIContext';
import { useAIStore } from '../../store/useAIStore';

interface SuggestedPromptsProps {
  context: AIContext;
  onSelect: (prompt: string) => void;
  /** `rail` renders a single scrollable row above the composer. */
  variant?: 'cards' | 'rail';
}

export function SuggestedPrompts({ context, onSelect, variant = 'cards' }: SuggestedPromptsProps) {
  const [prompts, setPrompts] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const aiAvailable = useAIStore((state) => state.aiStatus?.available !== false);
  const routeKey = `${context.route}|${context.symbol ?? ''}|${context.entity_type ?? ''}`;

  useEffect(() => {
    let cancelled = false;
    const fallback = getLocalPrompts(context);

    setLoading(true);
    getSuggestedPrompts(context)
      .then((remote) => {
        if (cancelled) return;
        setPrompts(remote.length > 0 ? remote.slice(0, 5) : fallback);
      })
      .catch(() => {
        if (!cancelled) setPrompts(fallback);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  if (prompts.length === 0) {
    if (!loading) return null;
    return <div className="ai-shimmer" style={{ padding: '8px 2px' }}>Preparing suggestions…</div>;
  }

  if (variant === 'rail') {
    return (
      <div className="ai-prompts compact" aria-label="Suggested questions">
        {prompts.slice(0, 4).map((prompt) => (
          <button
            key={prompt}
            type="button"
            className="ai-prompt"
            onClick={() => onSelect(prompt)}
            disabled={!aiAvailable}
          >
            <Sparkles aria-hidden />
            {prompt}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="ai-prompts" aria-label="Suggested questions">
      <div className="ai-prompts-head">
        <Lightbulb aria-hidden style={{ width: 12, height: 12 }} />
        Suggested for this page
      </div>
      {prompts.map((prompt) => (
        <button
          key={prompt}
          type="button"
          className="ai-prompt"
          onClick={() => onSelect(prompt)}
          disabled={!aiAvailable}
        >
          <Sparkles aria-hidden />
          <span>{prompt}</span>
        </button>
      ))}
    </div>
  );
}

export default SuggestedPrompts;
