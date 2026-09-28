/**
 * Phase 20 — `AmountControls` (spec §6).
 *
 * Quick simulated-value buttons (+$1 / +$5 / +$10 / +$100) plus manual input.
 * These are **simulated quantity/value inputs only** — there is no payment
 * integration, no card, and no money movement anywhere behind them.
 */
import { Coins, Minus, Plus } from "lucide-react";
import { QUICK_AMOUNTS, type PaperAmountMode } from "../../lib/paperTrading";

interface AmountControlsProps {
  amount: string;
  onChange: (value: string) => void;
  onAdd: (delta: number) => void;
  amountMode: PaperAmountMode;
  onModeChange: (mode: PaperAmountMode) => void;
  currency?: string | null;
  quantityPrecision: number;
  disabled?: boolean;
  error?: string | null;
}

export default function AmountControls({
  amount,
  onChange,
  onAdd,
  amountMode,
  onModeChange,
  currency,
  quantityPrecision,
  disabled,
  error,
}: AmountControlsProps) {
  const unit = amountMode === "NOTIONAL" ? currency || "value" : "units";

  return (
    <div className="paper-field">
      <div className="paper-field-head">
        <label htmlFor="paper-amount">Simulated {amountMode === "NOTIONAL" ? "amount" : "quantity"}</label>
        <span className="paper-field-note">
          <Coins size={11} aria-hidden /> not real money
        </span>
      </div>

      <div className="paper-segmented small" role="radiogroup" aria-label="Amount input mode">
        <button
          type="button"
          role="radio"
          aria-checked={amountMode === "NOTIONAL"}
          className={`paper-segment neutral${amountMode === "NOTIONAL" ? " active" : ""}`}
          disabled={disabled}
          onClick={() => onModeChange("NOTIONAL")}
        >
          Value
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={amountMode === "QUANTITY"}
          className={`paper-segment neutral${amountMode === "QUANTITY" ? " active" : ""}`}
          disabled={disabled}
          onClick={() => onModeChange("QUANTITY")}
        >
          Quantity
        </button>
      </div>

      <div className="paper-amount-row">
        <button
          type="button"
          className="paper-step"
          aria-label="Decrease simulated amount"
          disabled={disabled}
          onClick={() => onAdd(-1)}
        >
          <Minus size={14} aria-hidden />
        </button>
        <input
          id="paper-amount"
          className={`paper-input${error ? " invalid" : ""}`}
          inputMode="decimal"
          value={amount}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "paper-amount-error" : undefined}
          onChange={(event) => onChange(event.target.value)}
          placeholder={amountMode === "NOTIONAL" ? "0.00" : `0.${"0".repeat(Math.min(quantityPrecision, 4))}`}
        />
        <button
          type="button"
          className="paper-step"
          aria-label="Increase simulated amount"
          disabled={disabled}
          onClick={() => onAdd(1)}
        >
          <Plus size={14} aria-hidden />
        </button>
      </div>

      <div className="paper-quick-amounts" role="group" aria-label="Quick simulated amounts">
        {QUICK_AMOUNTS.map((value) => (
          <button
            key={value}
            type="button"
            className="paper-quick"
            disabled={disabled}
            onClick={() => onAdd(value)}
            aria-label={`Add ${value} to the simulated ${amountMode === "NOTIONAL" ? "amount" : "quantity"}`}
          >
            +{value}
          </button>
        ))}
        <button
          type="button"
          className="paper-quick ghost"
          disabled={disabled}
          onClick={() => onChange("")}
          aria-label="Clear the simulated amount"
        >
          Clear
        </button>
      </div>

      {error && (
        <p className="paper-error" id="paper-amount-error" role="alert">
          {error}
        </p>
      )}
      <p className="paper-hint">
        Simulated {amountMode === "NOTIONAL" ? "notional value" : "quantity"} in {unit}. Nothing is charged,
        transferred or wagered.
      </p>
    </div>
  );
}
