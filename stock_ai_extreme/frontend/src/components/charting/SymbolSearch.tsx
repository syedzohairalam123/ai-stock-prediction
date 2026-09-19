/**
 * Phase 11 — the chart's symbol box (spec §24).
 *
 * A combobox over the existing PSX universe (indices first, then tickers) with
 * keyboard support. Suggestions come from the same metadata the rest of the
 * terminal uses, so the chart can never disagree with the Market pages about
 * which symbols exist — and typing an index symbol switches the entity type
 * automatically instead of failing at the data layer.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import type { EntityType } from "../../lib/charting/types";
import { inferEntityType, isValidSymbolFormat, normalizeSymbol, symbolSuggestions } from "../../lib/charting/dataSource";

interface SymbolSearchProps {
  value: string;
  entityType: EntityType;
  entityName: string;
  onCommit: (symbol: string, entityType: EntityType) => void;
  onEntityType: (entityType: EntityType) => void;
  disabled?: boolean;
}

export default function SymbolSearch({
  value,
  entityType,
  entityName,
  onCommit,
  onEntityType,
  disabled = false,
}: SymbolSearchProps) {
  const [query, setQuery] = useState(value);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const wrapper = useRef<HTMLDivElement>(null);

  // Follow the store when the symbol changes elsewhere (mobile switcher, reset).
  useEffect(() => setQuery(value), [value]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (wrapper.current && !wrapper.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const suggestions = useMemo(() => symbolSuggestions(query, 7), [query]);

  const commit = (symbol: string, nextEntityType?: EntityType) => {
    const normalized = normalizeSymbol(symbol);
    if (!normalized || !isValidSymbolFormat(normalized)) return;
    onCommit(normalized, nextEntityType ?? inferEntityType(normalized));
    setOpen(false);
  };

  return (
    <div className="chart-symbol" ref={wrapper}>
      <div className={`chart-symbol-box${open ? " open" : ""}`}>
        <Search size={14} aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setHighlight(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setHighlight((h) => Math.min(h + 1, Math.max(0, suggestions.length - 1)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setHighlight((h) => Math.max(0, h - 1));
            } else if (event.key === "Enter") {
              event.preventDefault();
              const pick = suggestions[highlight];
              if (pick) commit(pick.symbol, pick.entityType);
              else commit(query);
            } else if (event.key === "Escape") {
              setOpen(false);
              setQuery(value);
            }
          }}
          onBlur={() => {
            // Typing a ticker and clicking away should still plot it, but only
            // when the text actually changed — otherwise a stray blur refetches.
            if (normalizeSymbol(query) !== value && isValidSymbolFormat(query)) commit(query);
          }}
          placeholder="Symbol (e.g. OGDC, KSE100)"
          aria-label="Chart symbol"
          aria-autocomplete="list"
          aria-expanded={open}
          role="combobox"
          spellCheck={false}
          disabled={disabled}
        />
        <select
          className="chart-symbol-type"
          value={entityType}
          onChange={(event) => onEntityType(event.target.value as EntityType)}
          aria-label="Instrument type"
          title="Plot the symbol as a stock or as an index"
        >
          <option value="STOCK">Stock</option>
          <option value="INDEX">Index</option>
        </select>
      </div>

      <span className="chart-symbol-name" title={entityName}>
        {entityName}
      </span>

      {open && suggestions.length > 0 && (
        <ul className="chart-symbol-list" role="listbox" aria-label="Symbol suggestions">
          {suggestions.map((suggestion, index) => (
            <li key={`${suggestion.entityType}-${suggestion.symbol}`}>
              <button
                type="button"
                role="option"
                aria-selected={index === highlight}
                className={index === highlight ? "on" : ""}
                onMouseEnter={() => setHighlight(index)}
                onMouseDown={(event) => {
                  // `mousedown` so the click lands before the input's blur.
                  event.preventDefault();
                  commit(suggestion.symbol, suggestion.entityType);
                }}
              >
                <span className="chart-symbol-code">{suggestion.symbol}</span>
                <span className="chart-symbol-desc">{suggestion.name}</span>
                <span className={`chart-symbol-kind ${suggestion.entityType.toLowerCase()}`}>
                  {suggestion.entityType === "INDEX" ? "Index" : "Stock"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
