/**
 * Phase 18 — geopolitical coverage timeline (spec §12).
 *
 * Each entry is external news coverage with its publisher and timestamp, not an
 * assertion by this application. Rule-based categories and locations are
 * labelled as such.
 */
import { useMemo, useState } from "react";
import { Clock } from "lucide-react";
import { usePoliticalTimeline } from "../../hooks/usePoliticalQueries";
import {
  CATEGORY_META,
  fmtDateTime,
  relativeTime,
  type PoliticalCategory,
  type TimelineEvent,
} from "../../lib/political";

interface Props {
  onSelectRegion?: (regionId: string) => void;
  selectedRegionId?: string | null;
}

const HOUR_OPTIONS = [24, 72, 168, 336];
const CATEGORY_OPTIONS: PoliticalCategory[] = [
  "ELECTION", "REFERENDUM", "GOVERNMENT", "POLICY", "INTERNATIONAL", "CONFLICT", "OTHER",
];

export default function PoliticalTimeline({ onSelectRegion, selectedRegionId }: Props) {
  const [hours, setHours] = useState(72);
  const [category, setCategory] = useState<PoliticalCategory | "ALL">("ALL");
  const [regionFiltered, setRegionFiltered] = useState(false);

  const query = usePoliticalTimeline(hours, category === "ALL" ? undefined : category);

  const events = useMemo<TimelineEvent[]>(() => {
    const all = query.data?.events ?? [];
    if (!regionFiltered || !selectedRegionId) return all;
    return all.filter((event) => event.affected_regions.includes(selectedRegionId));
  }, [query.data, regionFiltered, selectedRegionId]);

  return (
    <section className="political-timeline panel" aria-label="Geopolitical timeline">
      <div className="political-timeline-head">
        <div>
          <h2><Clock size={15} aria-hidden /> Geopolitical timeline</h2>
          <p className="dim">
            External coverage from the GDELT DOC 2.0 news index. Categories are rule-based
            keyword labels; locations come from the publisher's own country field.
          </p>
        </div>
        <div className="political-timeline-controls">
          <label>
            <span className="sr-only">Time window</span>
            <select value={hours} onChange={(event) => setHours(Number(event.target.value))}>
              {HOUR_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  Last {option >= 168 ? `${option / 24} days` : `${option} h`}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="sr-only">Category</span>
            <select value={category} onChange={(event) => setCategory(event.target.value as PoliticalCategory | "ALL")}>
              <option value="ALL">All categories</option>
              {CATEGORY_OPTIONS.map((option) => (
                <option key={option} value={option}>{CATEGORY_META[option].label}</option>
              ))}
            </select>
          </label>
          {selectedRegionId && (
            <label className="political-check">
              <input type="checkbox" checked={regionFiltered} onChange={(event) => setRegionFiltered(event.target.checked)} />
              Only this region
            </label>
          )}
        </div>
      </div>

      {query.isLoading && <div className="skeleton" style={{ height: 120 }} />}
      {query.isError && (
        <div className="market-state market-state-error" role="alert">
          <strong>Timeline source unavailable</strong>
          <span>{(query.error as Error)?.message ?? "The coverage index did not respond."}</span>
        </div>
      )}
      {query.data && events.length === 0 && (
        <div className="market-state" role="status">
          <strong>No coverage in this window</strong>
          <span>No external article matched this filter. Nothing is fabricated to fill the gap.</span>
        </div>
      )}

      {events.length > 0 && (
        <ol className="political-timeline-list">
          {events.map((event) => (
            <li key={event.id}>
              <span className="political-timeline-time">
                {fmtDateTime(event.timestamp)}
                <em>{relativeTime(event.timestamp)}</em>
              </span>
              <div className="political-timeline-body">
                <div className="political-timeline-title-row">
                  <span className={`political-category-chip ${event.category.toLowerCase()}`}>
                    {CATEGORY_META[event.category].icon} {CATEGORY_META[event.category].label}
                  </span>
                  {event.classification_basis === "RULE_BASED" && (
                    <span className="political-type-badge muted">rule-based</span>
                  )}
                </div>
                {event.url ? (
                  <a href={event.url} target="_blank" rel="noopener noreferrer">{event.title}</a>
                ) : (
                  <strong>{event.title}</strong>
                )}
                <div className="dim">
                  {event.source}
                  {event.location ? ` · publisher country: ${event.location}` : ""}
                  {event.language ? ` · ${event.language}` : ""}
                </div>
                {event.affected_regions.length > 0 && (
                  <div className="political-region-tags">
                    {event.affected_regions.slice(0, 6).map((regionId) => (
                      <button
                        key={regionId}
                        type="button"
                        className={regionId === selectedRegionId ? "active" : ""}
                        onClick={() => onSelectRegion?.(regionId)}
                        title="Open this region"
                      >
                        {regionId.replace("us-state:", "").replace("country:", "")}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
