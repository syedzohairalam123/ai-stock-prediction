/**
 * Phase 20 — entry points for the ticket.
 *
 *   * `QuickOrderButton` — a compact button for page headers ("Trade / simulate")
 *   * `QuickOrderFab`    — a floating launcher available on every page
 *
 * Both are labelled PAPER so nothing in the UI implies a real order can be
 * placed from here.
 */
import { Receipt } from "lucide-react";
import { usePaperOrderStore } from "../../store/usePaperOrderStore";
import type { PaperContextInput } from "../../hooks/usePaperContextSync";

interface TriggerProps {
  context?: Partial<PaperContextInput>;
  label?: string;
  className?: string;
  title?: string;
}

export function QuickOrderButton({ context, label = "Paper ticket", className = "", title }: TriggerProps) {
  const openPanel = usePaperOrderStore((state) => state.openPanel);
  const togglePanel = usePaperOrderStore((state) => state.togglePanel);
  const isOpen = usePaperOrderStore((state) => state.isOpen);

  return (
    <button
      type="button"
      className={`paper-trigger ${className}`.trim()}
      onClick={() => (isOpen && !context ? togglePanel() : openPanel(context))}
      title={title ?? "Open the paper simulation ticket"}
    >
      <span className="paper-trigger-badge">PAPER</span>
      <Receipt size={14} aria-hidden />
      {label}
    </button>
  );
}

export default function QuickOrderFab() {
  const openPanel = usePaperOrderStore((state) => state.openPanel);
  const closePanel = usePaperOrderStore((state) => state.closePanel);
  const isOpen = usePaperOrderStore((state) => state.isOpen);

  return (
    <button
      type="button"
      className={`paper-fab${isOpen ? " active" : ""}`}
      aria-label={isOpen ? "Close the paper simulation ticket" : "Open the paper simulation ticket"}
      aria-pressed={isOpen}
      onClick={() => (isOpen ? closePanel() : openPanel())}
    >
      <Receipt size={16} aria-hidden />
      <span>Paper</span>
    </button>
  );
}
