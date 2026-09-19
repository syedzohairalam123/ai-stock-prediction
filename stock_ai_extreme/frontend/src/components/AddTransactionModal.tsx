/**
 * Phase 9 — Add Transaction modal (spec F/N).
 *
 * BUY/SELL entry with per-field validation from the shared `finance` engine —
 * including the SELL-vs-holdings guard, which needs the live position size
 * passed in by the parent. No navigation, no silent failures: every rejected
 * input shows a clear message next to its field.
 */

import { useEffect, useMemo, useState } from "react";
import {
  validateTransactionInput,
  formatPkr,
  type Side,
} from "../lib/finance";

interface AddTransactionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
  /** Existing quantity held for `initialSymbol` — powers the SELL guard. */
  availableQuantity?: number;
  /** Symbols already held, offered first in the datalist. */
  heldSymbols?: string[];
  initialSymbol?: string;
  initialType?: Side;
  submit: (input: {
    symbol: string;
    side: Side;
    quantity: string;
    price: string;
    fees: string;
    date: string;
  }) => Promise<void>;
}

export default function AddTransactionModal({
  isOpen,
  onClose,
  onSuccess,
  availableQuantity = 0,
  heldSymbols = [],
  initialSymbol = "",
  initialType = "BUY",
  submit,
}: AddTransactionModalProps) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [side, setSide] = useState<Side>(initialType);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("0");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setSymbol(initialSymbol);
      setSide(initialType);
      setQuantity("");
      setPrice("");
      setFees("0");
      setDate(new Date().toISOString().slice(0, 10));
      setNotes("");
      setErrors({});
      setSubmitError(null);
    }
  }, [isOpen, initialSymbol, initialType]);

  const total = useMemo(() => {
    const q = Number(quantity) || 0;
    const p = Number(price) || 0;
    const f = fees.trim() === "" ? 0 : Number(fees) || 0;
    const subtotal = q * p;
    return { subtotal, total: side === "BUY" ? subtotal + f : subtotal - f };
  }, [quantity, price, fees, side]);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError(null);

    const input = { symbol, side, quantity, price, fees, date };
    const validation = validateTransactionInput(input, availableQuantity);
    setErrors(validation.errors);
    if (!validation.valid) return;

    setBusy(true);
    try {
      await submit(input);
      onSuccess?.();
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to save the transaction. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const err = (k: string) =>
    errors[k] ? (
      <span className="form-error" role="alert">
        {errors[k]}
      </span>
    ) : null;

  return (
    <div className="base-modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="base-modal base-modal-md" role="dialog" aria-modal="true" aria-label="Add transaction">
        <div className="base-modal-header">
          <h2 className="base-modal-title">Add Transaction</h2>
          <button onClick={onClose} className="base-modal-close" aria-label="Close">
            ✕
          </button>
        </div>
        <div className="base-modal-content">
          <form onSubmit={handleSubmit} className="add-transaction-form">
            {/* BUY / SELL toggle */}
            <div className="transaction-type-toggle" role="radiogroup" aria-label="Transaction side">
              <button
                type="button"
                onClick={() => setSide("BUY")}
                className={`transaction-type-btn ${side === "BUY" ? "active buy" : ""}`}
                aria-pressed={side === "BUY"}
              >
                BUY
              </button>
              <button
                type="button"
                onClick={() => setSide("SELL")}
                className={`transaction-type-btn ${side === "SELL" ? "active sell" : ""}`}
                aria-pressed={side === "SELL"}
              >
                SELL
              </button>
            </div>

            {/* Symbol */}
            <div className="form-group">
              <label htmlFor="tx-symbol" className="form-label">
                Stock Symbol *
              </label>
              <input
                id="tx-symbol"
                list="tx-symbol-options"
                className={`base-input base-input-default base-input-md ${errors.symbol ? "base-input-error" : ""}`}
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="e.g. OGDC, HBL, MEBL"
                disabled={busy}
                autoComplete="off"
              />
              <datalist id="tx-symbol-options">
                {heldSymbols.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
              {err("symbol")}
            </div>

            {/* Quantity + Price */}
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="tx-quantity" className="form-label">
                  Quantity *
                </label>
                <input
                  id="tx-quantity"
                  type="number"
                  step="any"
                  min="0"
                  className={`base-input base-input-default base-input-md ${errors.quantity ? "base-input-error" : ""}`}
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="100"
                  disabled={busy}
                />
                {err("quantity")}
                {side === "SELL" && !errors.quantity && availableQuantity > 0 && (
                  <span className="form-hint">You hold {availableQuantity}</span>
                )}
              </div>
              <div className="form-group">
                <label htmlFor="tx-price" className="form-label">
                  Price per Share (PKR) *
                </label>
                <input
                  id="tx-price"
                  type="number"
                  step="any"
                  min="0"
                  className={`base-input base-input-default base-input-md ${errors.price ? "base-input-error" : ""}`}
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="150.50"
                  disabled={busy}
                />
                {err("price")}
              </div>
            </div>

            {/* Fees + Date */}
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="tx-fees" className="form-label">
                  Fees (PKR)
                </label>
                <input
                  id="tx-fees"
                  type="number"
                  step="any"
                  min="0"
                  className={`base-input base-input-default base-input-md ${errors.fees ? "base-input-error" : ""}`}
                  value={fees}
                  onChange={(e) => setFees(e.target.value)}
                  placeholder="0"
                  disabled={busy}
                />
                {err("fees")}
              </div>
              <div className="form-group">
                <label htmlFor="tx-date" className="form-label">
                  Transaction Date *
                </label>
                <input
                  id="tx-date"
                  type="date"
                  className={`base-input base-input-default base-input-md ${errors.date ? "base-input-error" : ""}`}
                  value={date}
                  max={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => setDate(e.target.value)}
                  disabled={busy}
                />
                {err("date")}
              </div>
            </div>

            {/* Notes */}
            <div className="form-group">
              <label htmlFor="tx-notes" className="form-label">
                Notes
              </label>
              <textarea
                id="tx-notes"
                className="form-textarea"
                rows={2}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Optional — why you bought/sold"
                disabled={busy}
              />
            </div>

            {/* Live total */}
            <div className="transaction-summary">
              <div className="transaction-summary-row">
                <span>Subtotal</span>
                <span className="transaction-summary-value">{formatPkr(total.subtotal)}</span>
              </div>
              <div className="transaction-summary-row">
                <span>Fees</span>
                <span className="transaction-summary-value">{formatPkr(fees.trim() === "" ? 0 : Number(fees) || 0)}</span>
              </div>
              <div className="transaction-summary-row total">
                <span>Total {side}</span>
                <span className="transaction-summary-value">{formatPkr(total.total)}</span>
              </div>
            </div>

            {submitError && (
              <div className="form-error-banner" role="alert">
                {submitError}
              </div>
            )}

            <div className="modal-actions">
              <button type="button" className="base-button base-button-secondary base-button-md" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <button type="submit" className="base-button base-button-primary base-button-md" disabled={busy}>
                {busy ? "Saving…" : `Add ${side}`}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
