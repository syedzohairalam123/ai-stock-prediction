/**
 * Phase 19 §7 — the discovery filter bar.
 *
 * Every filter the spec asks for lives here: category, sub-tag, date, status,
 * source, asset type, plus the NEW/TRENDING modes (mode tabs sit on the page
 * itself) and free-text search over name/symbol/tags.
 *
 * The taxonomy it renders comes from the backend's *live* entity set, so a
 * tag that shows zero entities is never offered as a fake facet, and every
 * count is a real count.
 */
import { useEffect, useState } from "react";
import {
  ENTITY_LABELS,
  type DiscoveryTaxonomy,
  type EntityType,
} from "../../lib/discovery";

export interface DiscoveryFiltersValue {
  category: string | null;
  tag: string | null;
  type: EntityType | null;
  status: string | null;
  source: string | null;
  range: "" | "24h" | "7d" | "30d";
  q: string;
  personalize: boolean;
}

interface DiscoveryFiltersProps {
  value: DiscoveryFiltersValue;
  taxonomy?: DiscoveryTaxonomy;
  preferred: string[];
  onChange: (patch: Partial<DiscoveryFiltersValue>) => void;
  onTogglePreferred: (category: string) => void;
  onClear: () => void;
}

/** Statuses a discoverable entity can honestly carry (§7). */
const STATUS_OPTIONS = ["ACTIVE", "OPEN", "CLOSED", "RESOLVED"];

const ENTITY_TYPE_KEYS: EntityType[] = [
  "stock",
  "index",
  "crypto",
  "commodity",
  "forex",
  "news_topic",
  "forecast_event",
];

const RANGE_LABELS: Record<Exclude<DiscoveryFiltersValue["range"], "">, string> = {
  "24h": "Created in last 24h",
  "7d": "Created in last 7 days",
  "30d": "Created in last 30 days",
};

export default function DiscoveryFilters({
  value,
  taxonomy,
  preferred,
  onChange,
  onTogglePreferred,
  onClear,
}: DiscoveryFiltersProps) {
  const [text, setText] = useState(value.q);

  // Debounced free-text search — the input stays responsive while the feed
  // query waits for typing to settle (spec §16 — search performance).
  useEffect(() => {
    const trimmed = text.trim();
    if (trimmed === value.q) return;
    const timer = setTimeout(() => onChange({ q: trimmed }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  useEffect(() => {
    if (value.q !== text && document.activeElement !== null) {
      // keep the box in sync when the URL drives a change (e.g. clear-all)
      if (value.q === "") setText("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.q]);

  const tags = taxonomy?.tags ?? [];
  const sources = Array.from(new Set((taxonomy?.sources ?? []).map((s) => s.source))).sort();

  return (
    <div className="disc-filters" role="search">
      <div className="disc-filter-row disc-filter-cats">
        <button
          type="button"
          className={`disc-cat-chip ${value.category === null ? "active" : ""}`}
          onClick={() => onChange({ category: null })}
        >
          All categories
        </button>
        {(taxonomy?.categories ?? []).map((category) => (
          <span key={category.name} className="disc-cat-wrap">
            <button
              type="button"
              className={`disc-cat-chip ${value.category === category.name ? "active" : ""}`}
              onClick={() =>
                onChange({ category: value.category === category.name ? null : category.name })
              }
              title={`${category.count} entities in ${category.name}`}
            >
              {category.name}
              <em>{category.count}</em>
            </button>
            <button
              type="button"
              className={`disc-star ${preferred.includes(category.name) ? "on" : ""}`}
              onClick={() => onTogglePreferred(category.name)}
              aria-label={`${preferred.includes(category.name) ? "Unpin" : "Pin"} ${category.name} for personalization`}
              title="Pin this category — used only when personalization is on"
            >
              {preferred.includes(category.name) ? "★" : "☆"}
            </button>
          </span>
        ))}
      </div>

      <div className="disc-filter-row disc-filter-controls">
        <label className="disc-field disc-field-search">
          <span className="sr-only">Search entities</span>
          <input
            type="search"
            value={text}
            placeholder="Search name, symbol or tag…"
            onChange={(event) => setText(event.target.value)}
            maxLength={120}
          />
        </label>

        <label className="disc-field">
          <span>Tag</span>
          <select
            value={value.tag ?? ""}
            onChange={(event) => onChange({ tag: event.target.value || null })}
          >
            <option value="">Any tag</option>
            {tags.map((tag) => (
              <option key={tag.name} value={tag.name}>
                {tag.name} ({tag.count})
              </option>
            ))}
          </select>
        </label>

        <label className="disc-field">
          <span>Asset type</span>
          <select
            value={value.type ?? ""}
            onChange={(event) =>
              onChange({ type: (event.target.value || null) as EntityType | null })
            }
          >
            <option value="">All types</option>
            {ENTITY_TYPE_KEYS.map((type) => (
              <option key={type} value={type}>
                {ENTITY_LABELS[type]}
              </option>
            ))}
          </select>
        </label>

        <label className="disc-field">
          <span>Status</span>
          <select
            value={value.status ?? ""}
            onChange={(event) => onChange({ status: event.target.value || null })}
          >
            <option value="">Any status</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>

        <label className="disc-field">
          <span>Source</span>
          <select
            value={value.source ?? ""}
            onChange={(event) => onChange({ source: event.target.value || null })}
          >
            <option value="">Any source</option>
            {sources.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </label>

        <label className="disc-field">
          <span>Date</span>
          <select
            value={value.range}
            onChange={(event) =>
              onChange({ range: event.target.value as DiscoveryFiltersValue["range"] })
            }
          >
            <option value="">Any time</option>
            {(Object.keys(RANGE_LABELS) as Array<keyof typeof RANGE_LABELS>).map((key) => (
              <option key={key} value={key}>
                {RANGE_LABELS[key]}
              </option>
            ))}
          </select>
        </label>

        <label className="disc-toggle" title="Boost only your explicit signals: watchlist, entities you opened, pinned categories.">
          <input
            type="checkbox"
            checked={value.personalize}
            onChange={(event) => onChange({ personalize: event.target.checked })}
          />
          <span>Personalize</span>
        </label>

        <button type="button" className="disc-clear" onClick={onClear}>
          Clear filters
        </button>
      </div>
    </div>
  );
}
