/**
 * Phase 18 — region detail panel.
 *
 * Shows everything the selected region's sources actually published, grouped by
 * measurement family so a poll can never be read as a certified result. When
 * sources disagree the panel keeps **both** and says so (spec §19); it never
 * picks a winner.
 */
import { AlertTriangle, Landmark, Layers, X } from "lucide-react";
import { usePoliticalRegionDetail } from "../../hooks/usePoliticalQueries";
import MeasurementCard from "./MeasurementCard";
import {
  CATEGORY_META,
  MEASUREMENT_TYPE_META,
  REGION_STATE_META,
  fmtDate,
  fmtDateTime,
  relativeTime,
  type MeasurementType,
} from "../../lib/political";

interface Props {
  regionId: string | null;
  electionId?: string;
  onClose: () => void;
}

const TYPE_ORDER: MeasurementType[] = ["POLL", "FORECAST", "MODEL", "HISTORICAL_RESULT"];

export default function RegionDetailPanel({ regionId, electionId, onClose }: Props) {
  const query = usePoliticalRegionDetail(regionId, electionId);

  if (!regionId) {
    return (
      <aside className="political-detail panel" aria-label="Region detail">
        <div className="political-detail-empty" role="status">
          <Layers size={20} aria-hidden />
          <p>Select a region on the map or from the region list to see its sourced detail.</p>
          <span className="dim">No number is shown until a real source provides one.</span>
        </div>
      </aside>
    );
  }

  return (
    <aside className="political-detail panel" aria-label="Region detail" aria-live="polite">
      <div className="political-detail-head">
        <div>
          <span className="political-detail-eyebrow">Region detail</span>
          <h2>{query.data?.region.name ?? regionId}</h2>
        </div>
        <button type="button" className="political-detail-close" onClick={onClose} aria-label="Close region detail">
          <X size={16} aria-hidden />
        </button>
      </div>

      {query.isLoading && <div className="skeleton" style={{ height: 180 }} />}

      {query.isError && (
        <div className="market-state market-state-error" role="alert">
          <strong>Region detail unavailable</strong>
          <span>{(query.error as Error)?.message ?? "The backend could not serve this region."}</span>
        </div>
      )}

      {query.data && (
        <>
          <div className="political-detail-status">
            <span
              className="political-state-badge"
              style={{ borderColor: REGION_STATE_META[query.data.state.state].color, color: REGION_STATE_META[query.data.state.state].color }}
            >
              {REGION_STATE_META[query.data.state.state].label}
            </span>
            <span className="dim">{query.data.state.reason ?? REGION_STATE_META[query.data.state.state].blurb}</span>
          </div>

          <dl className="political-region-meta">
            <div>
              <dt>Country</dt>
              <dd>{query.data.region.country_name}</dd>
            </div>
            {query.data.region.state_code && (
              <div>
                <dt>State code</dt>
                <dd>{query.data.region.state_code}</dd>
              </div>
            )}
            <div>
              <dt>Geometry</dt>
              <dd>
                {query.data.region.geometry.location_mode}
                {query.data.region.geometry.reference_url && (
                  <>
                    {" · "}
                    <a href={query.data.region.geometry.reference_url} target="_blank" rel="noopener noreferrer">
                      source
                    </a>
                  </>
                )}
              </dd>
            </div>
            <div>
              <dt>Population context</dt>
              <dd>
                {query.data.region.population_context?.population !== null && query.data.region.population_context?.population !== undefined
                  ? `${query.data.region.population_context.population.toLocaleString()}`
                  : <span className="dim">{query.data.region.population_context?.note ?? "not provided by any source"}</span>}
                {query.data.region.population_context?.population !== null
                  && query.data.region.population_context?.population !== undefined
                  && query.data.region.population_context?.source && (
                    <span className="dim">
                      {" "}· {query.data.region.population_context.source}
                      {query.data.region.population_context.as_of ? ` (${query.data.region.population_context.as_of})` : ""}
                    </span>
                  )}
              </dd>
            </div>
            <div>
              <dt>Last sourced measurement</dt>
              <dd>
                {query.data.state.last_measurement_at
                  ? <>{fmtDateTime(query.data.state.last_measurement_at)} <span className="dim">({relativeTime(query.data.state.last_measurement_at)})</span></>
                  : <span className="dim">none</span>}
              </dd>
            </div>
          </dl>

          {query.data.measurements.sources_disagree && (
            <div className="political-conflict" role="status">
              <AlertTriangle size={15} aria-hidden />
              <div>
                <strong>Sources disagree</strong>
                <p>{query.data.measurements.conflict_note}</p>
              </div>
            </div>
          )}

          <div className="political-measurements">
            <h3>
              Sourced measurements{" "}
              <span className="dim">({query.data.measurements.measurements.length})</span>
            </h3>

            {query.data.measurements.measurements.length === 0 && (
              <div className="market-state" role="status">
                <strong>No current sourced measurement</strong>
                <span>
                  No external source currently provides data for this region. No value is estimated
                  or substituted.
                </span>
              </div>
            )}

            {TYPE_ORDER.map((type) => {
              // Historical results arrive in their own `historical` channel —
              // they are folded in here so a certified past outcome is visible,
              // still clearly labelled as HISTORICAL_RESULT rather than a poll.
              const rows = type === "HISTORICAL_RESULT"
                ? (query.data!.historical ?? [])
                : (query.data!.measurements.by_type[type] ?? []);
              if (rows.length === 0) return null;
              return (
                <section key={type} className="political-type-group">
                  <header>
                    <span className={`political-type-badge ${type.toLowerCase()}`}>
                      {MEASUREMENT_TYPE_META[type].label}
                    </span>
                    <span className="dim">{MEASUREMENT_TYPE_META[type].blurb}</span>
                  </header>
                  {type === "HISTORICAL_RESULT" && rows.length > 8 && (
                    <p className="dim political-historical-note">
                      Showing the {Math.min(12, rows.length)} most recent of {rows.length} historical records.
                    </p>
                  )}
                  {rows.slice(0, type === "HISTORICAL_RESULT" ? 12 : rows.length).map((measurement) => (
                    <MeasurementCard key={measurement.id} measurement={measurement} emphasis={type !== "HISTORICAL_RESULT"} />
                  ))}
                </section>
              );
            })}
          </div>

          {query.data.events.length > 0 && (
            <div className="political-events">
              <h3><Landmark size={14} aria-hidden /> Calendar events ({query.data.events.length})</h3>
              <ul>
                {query.data.events.map((event) => (
                  <li key={event.id}>
                    <span className={`political-category-chip ${event.category.toLowerCase()}`}>
                      {CATEGORY_META[event.category].icon} {CATEGORY_META[event.category].label}
                    </span>
                    <div>
                      <strong>{event.name}</strong>
                      <div className="dim">
                        {event.election_date ? fmtDate(event.election_date) : "date unavailable"}
                        {event.election_date_basis ? ` · ${event.election_date_basis}` : ""}
                      </div>
                      <div className="dim">Source: {event.source}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {query.data.timeline.length > 0 && (
            <div className="political-events">
              <h3>Coverage timeline ({query.data.timeline.length})</h3>
              <ul>
                {query.data.timeline.map((event) => (
                  <li key={event.id}>
                    <div>
                      {event.url ? (
                        <a href={event.url} target="_blank" rel="noopener noreferrer">{event.title}</a>
                      ) : (
                        <strong>{event.title}</strong>
                      )}
                      <div className="dim">
                        {fmtDateTime(event.timestamp)} · {event.source}
                        {event.location ? ` · ${event.location}` : ""}
                        {event.classification_basis === "RULE_BASED" ? " · category rule-based" : ""}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="political-detail-disclaimer dim">
            {query.data.measurements.disclaimer} Assembled {fmtDateTime(query.data.retrieval.generated_at)}.
          </p>
        </>
      )}
    </aside>
  );
}
