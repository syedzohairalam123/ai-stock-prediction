/**
 * Phase 18 — Political & Geopolitical Data Mapping / Forecast Visualization.
 *
 * Composes the interactive map, region detail panel, neutral head-to-head view,
 * geopolitical timeline, filtered calendar and source registry into one screen.
 *
 * This screen is informational. It presents externally published measurements
 * with their sources and dates; it does not predict, endorse, rank or recommend
 * anything. The numbers a user can see here only exist because a named external
 * source published them.
 */
import { useMemo, useState } from "react";
import {
  CalendarDays,
  Filter,
  MapPin,
  RefreshCw,
  Search,
  ShieldCheck,
  Table as TableIcon,
} from "lucide-react";
import PoliticalMap, { type MapScope } from "../components/political/PoliticalMap";
import RegionDetailPanel from "../components/political/RegionDetailPanel";
import PoliticalTimeline from "../components/political/PoliticalTimeline";
import HeadToHeadView from "../components/political/HeadToHeadView";
import SourceRegistryPanel from "../components/political/SourceRegistryPanel";
import MeasurementCard from "../components/political/MeasurementCard";
import {
  usePoliticalEvents,
  usePoliticalMeasurements,
  usePoliticalOverview,
  usePoliticalRefresh,
} from "../hooks/usePoliticalQueries";
import {
  CATEGORY_META,
  MEASUREMENT_TYPE_META,
  fmtDate,
  fmtDateTime,
  relativeTime,
  type MeasurementType,
} from "../lib/political";

const MEASUREMENT_TYPE_OPTIONS: MeasurementType[] = ["POLL", "FORECAST", "MODEL", "HISTORICAL_RESULT"];

export default function PoliticalPage() {
  const [scope, setScope] = useState<MapScope>("US");
  const [electionId, setElectionId] = useState<string>("");
  const [selectedRegionId, setSelectedRegionId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [measurementType, setMeasurementType] = useState<MeasurementType | "ALL">("ALL");
  const [sourceId, setSourceId] = useState<string>("ALL");
  const [upcomingOnly, setUpcomingOnly] = useState(false);

  const overview = usePoliticalOverview(electionId || undefined);
  const refresh = usePoliticalRefresh();

  const events = usePoliticalEvents({ upcomingOnly });
  const measurements = usePoliticalMeasurements({
    electionId: electionId || undefined,
    regionId: selectedRegionId ?? undefined,
    measurementType: measurementType === "ALL" ? undefined : measurementType,
    sourceId: sourceId === "ALL" ? undefined : sourceId,
  });

  const regions = overview.data?.regions ?? [];
  const regionStates = overview.data?.region_states ?? [];
  const sources = overview.data?.sources ?? [];
  const electionIds = overview.data?.election_ids ?? [];

  const countryOptions = useMemo(() => {
    const set = new Set<string>();
    for (const event of events.data?.events ?? []) set.add(event.country);
    for (const source of sources) void source;
    return Array.from(set).sort();
  }, [events.data, sources]);

  const searchResults = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return [];
    return regions
      .filter((region) =>
        region.name.toLowerCase().includes(term) ||
        (region.state_code ?? "").toLowerCase() === term ||
        (region.country_name ?? "").toLowerCase().includes(term),
      )
      .slice(0, 12);
  }, [regions, search]);

  const selectedRegion = useMemo(
    () => regions.find((region) => region.id === selectedRegionId) ?? null,
    [regions, selectedRegionId],
  );

  const chooseRegion = (regionId: string) => {
    setSelectedRegionId(regionId);
    setSearch("");
    const region = regions.find((item) => item.id === regionId);
    if (region) setScope(region.region_type === "COUNTRY" ? "WORLD" : "US");
  };

  const providerHealth = overview.data?.retrieval.providers ?? [];

  return (
    <section className="political-page">
      <header className="political-page-head">
        <div>
          <p className="political-eyebrow">Phase 18 · informational · neutral</p>
          <h1>Political &amp; Geopolitical Data Map</h1>
          <span className="dim">
            Externally sourced measurements only. Percentages are quoted verbatim from the named
            sources, which may include polls, forecasters, models/markets and certified historical
            results — these are never merged into a single number.
          </span>
        </div>
        <div className="political-page-head-actions">
          <button
            type="button"
            className="political-refresh"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            <RefreshCw size={15} className={refresh.isPending ? "political-spin" : ""} aria-hidden />
            {refresh.isPending ? "Refreshing…" : "Refresh sources"}
          </button>
          <span className="political-snapshot-time dim">
            {overview.data
              ? `Data assembled ${fmtDateTime(overview.data.generated_at)} · ${relativeTime(overview.data.generated_at)}`
              : "loading data timestamp…"}
          </span>
        </div>
      </header>

      <div className="political-neutrality-banner" role="note">
        <ShieldCheck size={16} aria-hidden />
        <div>
          <strong>Neutrality notice</strong>
          <p>
            {overview.data?.neutrality?.statement ??
              "This module presents externally published measurements only. It does not predict elections, endorse or rank candidates, infer user preferences or recommend any political outcome."}
          </p>
          <p className="dim">
            {overview.data?.neutrality?.map_colours ??
              "Map shading encodes data availability states, never parties or candidates."}
          </p>
        </div>
      </div>

      <div className="political-filterbar panel" aria-label="Filters">
        <span className="political-filter-title"><Filter size={14} aria-hidden /> Filters</span>

        <label>
          Election
          <select value={electionId} onChange={(event) => setElectionId(event.target.value)}>
            <option value="">All elections</option>
            {electionIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>

        <label>
          Measurement type
          <select value={measurementType} onChange={(event) => setMeasurementType(event.target.value as MeasurementType | "ALL")}>
            <option value="ALL">All measurement types</option>
            {MEASUREMENT_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>{MEASUREMENT_TYPE_META[type].label}</option>
            ))}
          </select>
        </label>

        <label>
          Source
          <select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>
            <option value="ALL">All sources</option>
            {sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
          </select>
        </label>

        {countryOptions.length > 0 && (
          <span className="political-country-note dim">Calendar countries: {countryOptions.join(", ")}</span>
        )}

        <label className="political-check">
          <input type="checkbox" checked={upcomingOnly} onChange={(event) => setUpcomingOnly(event.target.checked)} />
          Upcoming events only
        </label>

        {refresh.isError && (
          <span className="political-filter-error" role="alert">
            Refresh failed: {(refresh.error as Error)?.message}
          </span>
        )}
      </div>

      {overview.isError && (
        <div className="market-state market-state-error" role="alert">
          <strong>Political data service unavailable</strong>
          <span>
            {(overview.error as Error)?.message ?? "The backend did not respond."} The map cannot show
            data that was not retrieved, so nothing is substituted.
          </span>
        </div>
      )}

      <div className="political-workspace">
        <div className="political-map-column">
          <div className="political-region-search">
            <Search size={15} aria-hidden />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search a state, region or country…"
              aria-label="Search regions"
            />
            {searchResults.length > 0 && (
              <ul className="political-region-search-results">
                {searchResults.map((region) => (
                  <li key={region.id}>
                    <button type="button" onClick={() => chooseRegion(region.id)}>
                      <MapPin size={13} aria-hidden />
                      <span>{region.name}</span>
                      <span className="dim">{region.state_code ?? region.country_name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <PoliticalMap
            regions={regions}
            regionStates={regionStates}
            scope={scope}
            onScopeChange={setScope}
            selectedRegionId={selectedRegionId}
            onSelectRegion={(id) => (id ? chooseRegion(id) : setSelectedRegionId(null))}
            generatedAt={overview.data?.generated_at}
            loading={overview.isLoading}
          />

          {providerHealth.length > 0 && (
            <div className="political-provider-strip" aria-label="Provider status">
              {providerHealth.map((report) => (
                <span
                  key={report.provider_id}
                  className={`political-provider-pill ${report.ok ? "ok" : "down"}`}
                  title={report.error ?? "Source healthy"}
                >
                  {report.provider_id}: {report.ok ? `${report.items} items` : "unavailable"}
                </span>
              ))}
            </div>
          )}
        </div>

        <RegionDetailPanel
          regionId={selectedRegionId}
          electionId={electionId || undefined}
          onClose={() => setSelectedRegionId(null)}
        />
      </div>

      <HeadToHeadView
        electionId={electionId || undefined}
        regionId={selectedRegionId ?? undefined}
      />

      <section className="political-calendar panel" aria-label="Election calendar">
        <div className="political-calendar-head">
          <h2><CalendarDays size={15} aria-hidden /> Election &amp; event calendar</h2>
          <span className="dim">
            {events.data ? `${events.data.events.length} events` : "loading"} · official calendar rows
            from the Federal Election Commission
          </span>
        </div>

        {events.isLoading && <div className="skeleton" style={{ height: 100 }} />}
        {events.isError && (
          <div className="market-state market-state-error" role="alert">
            <strong>Calendar unavailable</strong>
            <span>{(events.error as Error)?.message ?? "The election calendar source did not respond."}</span>
          </div>
        )}
        {events.data && events.data.events.length === 0 && (
          <div className="market-state" role="status">
            <strong>No events match</strong>
            <span>The source returned no calendar rows for this filter.</span>
          </div>
        )}
        {events.data && events.data.events.length > 0 && (
          <div className="political-table-wrap">
            <table className="political-table">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Category</th>
                  <th scope="col">Jurisdiction</th>
                  <th scope="col">Date</th>
                  <th scope="col">Status</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {events.data.events.map((event) => (
                  <tr key={event.id}>
                    <td>{event.name}</td>
                    <td>
                      <span className={`political-category-chip ${event.category.toLowerCase()}`}>
                        {CATEGORY_META[event.category].icon} {CATEGORY_META[event.category].label}
                      </span>
                    </td>
                    <td>{event.jurisdiction ?? event.country}</td>
                    <td>{event.election_date ? fmtDate(event.election_date) : <span className="dim">date unavailable</span>}</td>
                    <td>{event.status}</td>
                    <td>
                      {event.source_url ? (
                        <a href={event.source_url} target="_blank" rel="noopener noreferrer">{event.source}</a>
                      ) : event.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="political-measurements-browser panel" aria-label="Sourced measurements">
        <div className="political-measurements-browser-head">
          <h2><TableIcon size={15} aria-hidden /> Sourced measurements</h2>
          <span className="dim">
            {measurements.data
              ? `${measurements.data.measurements.length} measurements · types: ${Object.keys(measurements.data.by_type).join(", ") || "none"}`
              : "loading"}
          </span>
        </div>

        {measurements.isLoading && <div className="skeleton" style={{ height: 120 }} />}
        {measurements.isError && (
          <div className="market-state market-state-error" role="alert">
            <strong>Measurements unavailable</strong>
            <span>{(measurements.error as Error)?.message ?? "No source responded for this filter."}</span>
          </div>
        )}
        {measurements.data && measurements.data.measurements.length === 0 && (
          <div className="market-state" role="status">
            <strong>No sourced measurements</strong>
            <span>No external source published a measurement matching this filter. Nothing is invented.</span>
          </div>
        )}
        {measurements.data && measurements.data.measurements.length > 0 && (
          <div className="political-measurements-browser-groups">
            {MEASUREMENT_TYPE_OPTIONS.map((type) => {
              const rows = measurements.data!.by_type[type] ?? [];
              if (rows.length === 0) return null;
              return (
                <section key={type} className="political-type-group">
                  <header>
                    <span className={`political-type-badge ${type.toLowerCase()}`}>
                      {MEASUREMENT_TYPE_META[type].label}
                    </span>
                    <span className="dim">{rows.length} {MEASUREMENT_TYPE_META[type].blurb.toLowerCase()}</span>
                  </header>
                  <div className="political-measurements-browser-grid">
                    {rows.slice(0, 24).map((measurement) => (
                      <MeasurementCard key={measurement.id} measurement={measurement} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </section>

      <PoliticalTimeline
        onSelectRegion={(regionId) => chooseRegion(regionId)}
        selectedRegionId={selectedRegionId}
      />

      <SourceRegistryPanel />

      <footer className="political-page-foot dim">
        {overview.data?.disclaimer ??
          "Informational visualization of externally published political data. This application does not predict elections, endorse candidates or recommend any political outcome."}
      </footer>
    </section>
  );
}
