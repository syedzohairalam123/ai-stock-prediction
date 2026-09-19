/**
 * Phase 11 — price-level tools (spec §19, §20).
 *
 * Two halves in one popover: the five quick tools that arm the chart for
 * placement, and the list of levels already placed (editable price, label,
 * visibility, lock, delete). Editing a price here is the precise alternative to
 * dragging the line, and both write the same `price` field — so the line stays
 * attached to its level through every zoom (spec §21).
 */
import { Eye, EyeOff, Lock, Plus, Ruler, Trash2, Unlock } from "lucide-react";
import type { CSSProperties } from "react";
import type { ChartInstance, PriceLevel, PriceLevelType } from "../../lib/charting/types";
import { PRICE_LEVEL_META, priceLevelDisplayText, priceLevelMeta, sortPriceLevels } from "../../lib/charting/drawings";

interface PriceLevelMenuProps {
  instance: ChartInstance;
  armedType: PriceLevelType | null;
  selectedId: string | null;
  lastClose: number | null;
  onArm: (type: PriceLevelType | null) => void;
  /** Place a level without a chart click (quick "at last price"). */
  onPlace: (type: PriceLevelType, price: number) => void;
  onSelect: (id: string | null) => void;
  onUpdate: (levelId: string, patch: Partial<PriceLevel>) => void;
  onDelete: (levelId: string) => void;
  onClear: () => void;
}

export default function PriceLevelMenu({
  instance,
  armedType,
  selectedId,
  lastClose,
  onArm,
  onPlace,
  onSelect,
  onUpdate,
  onDelete,
  onClear,
}: PriceLevelMenuProps) {
  const levels = sortPriceLevels(instance.priceLevels);
  const armed = armedType ? priceLevelMeta(armedType) : null;

  return (
    <div className="chart-pop-body">
      <div className="chart-pop-head">
        <span>Price levels</span>
        <span className="chart-pop-count">{levels.length} placed</span>
      </div>

      <div className="chart-level-tools">
        {PRICE_LEVEL_META.map((meta) => (
          <button
            key={meta.type}
            type="button"
            className={`chart-level-tool${armedType === meta.type ? " on" : ""}`}
            style={{ "--level-color": meta.color } as CSSProperties}
            onClick={() => onArm(armedType === meta.type ? null : meta.type)}
            aria-pressed={armedType === meta.type}
            title={meta.hint}
          >
            <span className="chart-level-dot" aria-hidden="true" />
            {meta.label}
          </button>
        ))}
      </div>

      {armed ? (
        <p className="chart-pop-hint" role="status">
          <Ruler size={12} /> {armed.hint}. Press Escape to disarm.
        </p>
      ) : (
        <p className="chart-pop-hint">
          <Ruler size={12} /> Pick a tool, then click the chart to place the level.
        </p>
      )}

      {armed && armedType && lastClose !== null && (
        <div className="chart-pop-section">
          <span className="chart-pop-section-title">Quick action</span>
          <button type="button" className="chart-btn ghost wide" onClick={() => onPlace(armedType, lastClose)}>
            <Plus size={13} />
            <span className="chart-btn-label">
              Place {armed.label.toLowerCase()} at last price ({lastClose.toFixed(2)})
            </span>
          </button>
        </div>
      )}

      {levels.length === 0 ? (
        <p className="chart-pop-empty">No levels yet. Place support, resistance, entry, stop or target lines.</p>
      ) : (
        <ul className="chart-level-list">
          {levels.map((level) => {
            const meta = priceLevelMeta(level.type);
            const selected = selectedId === level.id;
            return (
              <li
                key={level.id}
                className={`chart-level-row${selected ? " on" : ""}`}
                onClick={() => onSelect(selected ? null : level.id)}
                title={`${priceLevelDisplayText(level)} — shown on the chart at this price`}
              >
                <span className="chart-level-badge" style={{ color: meta.color, borderColor: meta.color }}>
                  {meta.short}
                </span>
                <input
                  className="chart-level-input"
                  value={level.label}
                  onChange={(event) => onUpdate(level.id, { label: event.target.value })}
                  onClick={(event) => event.stopPropagation()}
                  aria-label={`Label for ${meta.label}`}
                  title={`Rename this level (the price is shown after the name on the chart)`}
                />
                <input
                  className="chart-level-price num"
                  type="number"
                  step={0.01}
                  value={Number(level.price.toFixed(4))}
                  onChange={(event) => {
                    const price = Number(event.target.value);
                    if (Number.isFinite(price) && price > 0) onUpdate(level.id, { price });
                  }}
                  onClick={(event) => event.stopPropagation()}
                  aria-label={`Price for ${meta.label}`}
                  title="Edit price"
                />
                <button
                  type="button"
                  className="chart-icon-btn tiny"
                  onClick={(event) => {
                    event.stopPropagation();
                    onUpdate(level.id, { visible: !level.visible });
                  }}
                  aria-label={level.visible ? `Hide ${meta.label}` : `Show ${meta.label}`}
                  title={level.visible ? "Hide" : "Show"}
                >
                  {level.visible ? <Eye size={13} /> : <EyeOff size={13} />}
                </button>
                <button
                  type="button"
                  className={`chart-icon-btn tiny${level.locked ? " on" : ""}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    onUpdate(level.id, { locked: !level.locked });
                  }}
                  aria-label={level.locked ? `Unlock ${meta.label}` : `Lock ${meta.label}`}
                  title={level.locked ? "Unlock (allow drag)" : "Lock (block drag)"}
                >
                  {level.locked ? <Lock size={13} /> : <Unlock size={13} />}
                </button>
                <button
                  type="button"
                  className="chart-icon-btn tiny"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(level.id);
                  }}
                  aria-label={`Delete ${meta.label}`}
                  title="Delete"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {levels.length > 0 && (
        <div className="chart-pop-footer">
          <button type="button" className="chart-btn ghost" onClick={onClear}>
            <Trash2 size={13} />
            <span className="chart-btn-label">Clear all levels</span>
          </button>
        </div>
      )}
    </div>
  );
}
