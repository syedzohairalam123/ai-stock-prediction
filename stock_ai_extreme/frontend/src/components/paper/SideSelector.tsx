/**
 * Phase 20 — `SideSelector` (spec §4 and §14).
 *
 * Two vocabularies, never mixed:
 *   * price instruments → PAPER BUY / PAPER SELL
 *   * forecast events   → YES / NO informational selection
 *
 * The label always says "PAPER"; there is no button here that could be mistaken
 * for a real order.
 */
import { sideOptionsFor, type PaperQuoteMode, type PaperSide } from "../../lib/paperTrading";

interface SideSelectorProps {
  value: PaperSide;
  onChange: (side: PaperSide) => void;
  quoteMode: PaperQuoteMode;
  disabled?: boolean;
}

export default function SideSelector({ value, onChange, quoteMode, disabled }: SideSelectorProps) {
  const options = sideOptionsFor(quoteMode);
  const groupLabel = quoteMode === "PROBABILITY" ? "Forecast selection" : "Paper direction";

  return (
    <div className="paper-field">
      <div className="paper-field-head">
        <label id="paper-side-label">{groupLabel}</label>
        <span className="paper-field-note">simulation only</span>
      </div>
      <div className="paper-segmented" role="radiogroup" aria-labelledby="paper-side-label">
        {options.map((option) => {
          const active = value === option.value;
          const tone = option.value === "SELL" || option.value === "NO" ? "short" : "long";
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={option.hint}
              title={option.hint}
              disabled={disabled}
              className={`paper-segment ${tone}${active ? " active" : ""}`}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      <p className="paper-hint">
        {options.find((o) => o.value === value)?.hint ?? "Choose a direction."}
      </p>
    </div>
  );
}
