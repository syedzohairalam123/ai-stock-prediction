/**
 * Phase 11 — indicators panel (spec §8, §14).
 *
 * Toggling, retuning (period / standard-deviation multiplier), recolouring and
 * removing overlays. Any change goes straight to the store, so the chart updates
 * on the next render — the panel recomputes nothing itself.
 *
 * An indicator the current dataset cannot support (VWAP on daily bars, or a
 * series with no volume at all) is shown with the engine's own reason instead of
 * silently drawing nothing (spec §12, §29).
 */
import { useState } from "react";
import { Plus, RotateCcw, Trash2 } from "lucide-react";
import type { ChartInstance, IndicatorConfig, IndicatorType } from "../../lib/charting/types";
import type { IndicatorUnavailable } from "../../lib/charting/indicators";
import { indicatorLabel } from "../../lib/charting/indicators";

interface IndicatorMenuProps {
  instance: ChartInstance;
  unavailable: IndicatorUnavailable[];
  onToggle: (indicatorId: string) => void;
  onUpdate: (indicatorId: string, patch: Partial<IndicatorConfig>) => void;
  onAdd: (type: IndicatorType, period: number) => void;
  onRemove: (indicatorId: string) => void;
  onReset: () => void;
}

export default function IndicatorMenu({
  instance,
  unavailable,
  onToggle,
  onUpdate,
  onAdd,
  onRemove,
  onReset,
}: IndicatorMenuProps) {
  const [newType, setNewType] = useState<IndicatorType>("SMA");
  const [newPeriod, setNewPeriod] = useState(200);

  const reasonFor = (id: string) => unavailable.find((entry) => entry.indicatorId === id)?.reason ?? null;
  const enabledCount = instance.indicators.filter((i) => i.enabled).length;

  return (
    <div className="chart-pop-body">
      <div className="chart-pop-head">
        <span>Indicators</span>
        <span className="chart-pop-count">{enabledCount} on</span>
      </div>

      <ul className="chart-ind-list">
        {instance.indicators.map((indicator) => {
          const reason = reasonFor(indicator.id);
          return (
            <li key={indicator.id} className={`chart-ind-row${indicator.enabled ? " on" : ""}`}>
              <label className="chart-ind-main">
                <input
                  type="checkbox"
                  checked={indicator.enabled}
                  onChange={() => onToggle(indicator.id)}
                  aria-label={`Toggle ${indicatorLabel(indicator)}`}
                />
                <input
                  type="color"
                  className="chart-ind-color"
                  value={normalizeHex(indicator.color)}
                  onChange={(event) => onUpdate(indicator.id, { color: event.target.value })}
                  aria-label={`${indicatorLabel(indicator)} colour`}
                  title="Line colour"
                />
                <span className="chart-ind-name">{indicatorLabel(indicator)}</span>
              </label>

              <div className="chart-ind-controls">
                {indicator.type !== "VWAP" && (
                  <label className="chart-ind-field" title="Look-back period">
                    <span className="chart-sr">Period for</span>
                    <input
                      type="number"
                      min={1}
                      max={400}
                      value={indicator.period}
                      onChange={(event) => {
                        const period = Number(event.target.value);
                        if (!Number.isFinite(period)) return;
                        onUpdate(indicator.id, { period: Math.max(1, Math.min(400, Math.floor(period))) });
                      }}
                      aria-label={`${indicatorLabel(indicator)} period`}
                    />
                  </label>
                )}
                {indicator.type === "BB" && (
                  <label className="chart-ind-field" title="Standard-deviation multiplier">
                    <span className="chart-sr">Std dev</span>
                    <input
                      type="number"
                      min={0.5}
                      max={5}
                      step={0.5}
                      value={indicator.stdDev ?? 2}
                      onChange={(event) => {
                        const sd = Number(event.target.value);
                        if (!Number.isFinite(sd)) return;
                        onUpdate(indicator.id, { stdDev: Math.max(0.5, Math.min(5, sd)) });
                      }}
                      aria-label={`${indicatorLabel(indicator)} standard deviation multiplier`}
                    />
                  </label>
                )}
                <button
                  type="button"
                  className="chart-icon-btn tiny"
                  onClick={() => onRemove(indicator.id)}
                  title="Remove indicator"
                  aria-label={`Remove ${indicatorLabel(indicator)}`}
                >
                  <Trash2 size={13} />
                </button>
              </div>

              {indicator.enabled && reason && (
                <p className="chart-ind-note" role="status">
                  {reason}
                </p>
              )}
            </li>
          );
        })}
      </ul>

      <div className="chart-pop-section">
        <span className="chart-pop-section-title">Add another</span>
        <div className="chart-ind-add">
          <select
            value={newType}
            onChange={(event) => setNewType(event.target.value as IndicatorType)}
            aria-label="Indicator type to add"
          >
            <option value="SMA">SMA</option>
            <option value="EMA">EMA</option>
            <option value="BB">Bollinger Bands</option>
          </select>
          <input
            type="number"
            min={1}
            max={400}
            value={newPeriod}
            onChange={(event) => setNewPeriod(Number(event.target.value))}
            aria-label="Period for the new indicator"
          />
          <button
            type="button"
            className="chart-btn"
            onClick={() => {
              onAdd(newType, Number.isFinite(newPeriod) ? newPeriod : 20);
            }}
          >
            <Plus size={13} />
            <span className="chart-btn-label">Add</span>
          </button>
        </div>
      </div>

      <div className="chart-pop-footer">
        <button type="button" className="chart-btn ghost" onClick={onReset}>
          <RotateCcw size={13} />
          <span className="chart-btn-label">Reset to defaults</span>
        </button>
      </div>
    </div>
  );
}

/** `<input type="color">` only accepts `#rrggbb`. */
function normalizeHex(color: string): string {
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#5E9FE8";
}
