/**
 * Phase 20 — `PriceInput` (spec §5/§12).
 *
 * The reference price readout (always shown) and, for LIMIT simulations, the
 * limit price the hypothetical condition is tested against. The "use observed"
 * shortcut copies the real observed value rather than inventing one.
 */
import { Crosshair, Target } from "lucide-react";
import {
  formatPaperNumber,
  referenceColumnLabel,
  type PaperQuoteMode,
} from "../../lib/paperTrading";

interface PriceInputProps {
  referencePrice: number | null;
  referenceLabel?: string;
  quoteMode: PaperQuoteMode;
  orderType: "MARKET" | "LIMIT";
  limitPrice: string;
  onLimitChange: (value: string) => void;
  onUseObserved: () => void;
  stale: boolean;
  disabled?: boolean;
  error?: string | null;
}

export default function PriceInput({
  referencePrice,
  referenceLabel,
  quoteMode,
  orderType,
  limitPrice,
  onLimitChange,
  onUseObserved,
  stale,
  disabled,
  error,
}: PriceInputProps) {
  const isForecast = quoteMode === "PROBABILITY";
  return (
    <div className="paper-field">
      <div className="paper-reference">
        <span className="paper-reference-label">
          <Crosshair size={12} aria-hidden /> {referenceLabel || referenceColumnLabel(quoteMode)}
        </span>
        <span className={`paper-reference-value${stale ? " stale" : ""}`}>
          {referencePrice === null ? (
            <span title="No usable reference value is available">—</span>
          ) : isForecast ? (
            `${formatPaperNumber(referencePrice, 2)}%`
          ) : (
            formatPaperNumber(referencePrice, 4)
          )}
          {stale && <em> (stale)</em>}
        </span>
      </div>

      {orderType === "LIMIT" && (
        <>
          <div className="paper-field-head">
            <label htmlFor="paper-limit-price">
              {isForecast ? "Probability limit" : "Limit price"}
            </label>
            <span className="paper-field-note">
              <Target size={11} aria-hidden /> hypothetical
            </span>
          </div>
          <div className="paper-amount-row">
            <input
              id="paper-limit-price"
              className={`paper-input${error ? " invalid" : ""}`}
              inputMode="decimal"
              value={limitPrice}
              disabled={disabled}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "paper-limit-error" : undefined}
              onChange={(event) => onLimitChange(event.target.value)}
              placeholder={isForecast ? "e.g. 65" : "e.g. 210.50"}
            />
            <button
              type="button"
              className="paper-quick"
              disabled={disabled || referencePrice === null}
              onClick={onUseObserved}
              title="Copy the observed reference value"
            >
              Use observed
            </button>
          </div>
          {error && (
            <p className="paper-error" id="paper-limit-error" role="alert">
              {error}
            </p>
          )}
          <p className="paper-hint">
            {isForecast
              ? "The simulation is marked REACHED only if the real traded probability touches this level."
              : "The simulation fills only if the real market trades at this level or better."}{" "}
            Nothing is sent anywhere.
          </p>
        </>
      )}
    </div>
  );
}
