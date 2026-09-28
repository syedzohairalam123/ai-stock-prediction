/**
 * Phase 20 — `SimulationButton` (spec §27).
 *
 * Two guarantees:
 *   * It never says "order" — the verb is always SIMULATE.
 *   * It can never leave the panel stuck in SUBMITTING: the label reflects a
 *     bounded state and the caller clears it on both success and failure.
 */
import { Loader2, PlayCircle } from "lucide-react";

interface SimulationButtonProps {
  onClick: () => void;
  submitting: boolean;
  disabled?: boolean;
  label?: string;
  /** Blocked because there is no usable quote at all. */
  blockedReason?: string | null;
}

export default function SimulationButton({
  onClick,
  submitting,
  disabled,
  label = "Run paper simulation",
  blockedReason,
}: SimulationButtonProps) {
  const isDisabled = disabled || submitting || Boolean(blockedReason);

  return (
    <div className="paper-submit">
      <button
        type="button"
        className={`paper-submit-button${submitting ? " busy" : ""}`}
        onClick={onClick}
        disabled={isDisabled}
        aria-busy={submitting}
      >
        {submitting ? (
          <>
            <Loader2 size={15} className="paper-spin" aria-hidden /> SUBMITTING…
          </>
        ) : (
          <>
            <PlayCircle size={15} aria-hidden /> {label}
          </>
        )}
      </button>
      <p className="paper-submit-note">
        {blockedReason
          ? blockedReason
          : "Records a hypothetical scenario in this app only. No order is placed and no funds move."}
      </p>
    </div>
  );
}
