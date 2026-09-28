/**
 * Phase 20 — `OrderTypeSelector` (spec §5).
 *
 * Educational order-type UI. Selecting a type explains what it means and what
 * the simulation will actually do with it — it never implies a real order was
 * routed anywhere.
 */
import { BookOpen, Zap } from "lucide-react";
import type { PaperOrderType, PaperQuoteMode } from "../../lib/paperTrading";

interface OrderTypeSelectorProps {
  value: PaperOrderType;
  onChange: (orderType: PaperOrderType) => void;
  quoteMode: PaperQuoteMode;
  disabled?: boolean;
}

function explanation(orderType: PaperOrderType, quoteMode: PaperQuoteMode): string {
  if (orderType === "MARKET") {
    return (
      "Anchored to the value observed right now. The simulation records the fill at that " +
      "reference — no exchange is contacted."
    );
  }
  return quoteMode === "PROBABILITY"
    ? "Becomes REACHED only when the real traded probability actually touches your limit level."
    : "Fills only when the real market trades at your limit price or better. Subsequent real observations are checked afterwards.";
}

export default function OrderTypeSelector({ value, onChange, quoteMode, disabled }: OrderTypeSelectorProps) {
  const options: PaperOrderType[] = ["MARKET", "LIMIT"];

  return (
    <div className="paper-field">
      <div className="paper-field-head">
        <label id="paper-order-type-label">Order type</label>
        <span className="paper-field-note">educational</span>
      </div>
      <div className="paper-segmented" role="radiogroup" aria-labelledby="paper-order-type-label">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            className={`paper-segment neutral${value === option ? " active" : ""}`}
            disabled={disabled}
            onClick={() => onChange(option)}
          >
            {option === "MARKET" ? <Zap size={13} aria-hidden /> : <BookOpen size={13} aria-hidden />} {option}
          </button>
        ))}
      </div>
      <p className="paper-hint">{explanation(value, quoteMode)}</p>
    </div>
  );
}
