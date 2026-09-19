/**
 * StreamingIndicator — "thinking" state for an in-flight answer (spec L).
 *
 * Deliberately quiet: three dots and a word. The chat never shows a spinner
 * that cannot end, because the parent always resolves streaming to a terminal
 * state (complete, cancelled or error).
 */

interface StreamingIndicatorProps {
  label?: string;
}

export function StreamingIndicator({ label = 'Reading market context' }: StreamingIndicatorProps) {
  return (
    <div className="ai-thinking" role="status" aria-live="polite">
      <span className="ai-dots" aria-hidden>
        <i />
        <i />
        <i />
      </span>
      <span>{label}…</span>
    </div>
  );
}

export default StreamingIndicator;
