/**
 * Phase 18 — interactive political/geopolitical choropleth.
 *
 * Geometry comes from Plotly's bundled authoritative topojson (Natural Earth /
 * US Census derived), addressed by USPS state code or country name — the app
 * never draws borders itself and never downloads a hand-made shapefile.
 *
 * The fill colour encodes **data availability** (AVAILABLE / NO_DATA /
 * OUTDATED / CONTESTED / RESOLVED) — never a party, candidate or outcome.
 * A region with no current sourced data is neutral grey, exactly as the spec
 * requires.
 */
import { useMemo } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout, PlotMouseEvent } from "plotly.js";
import {
  REGION_STATE_META,
  REGION_STATE_ORDER,
  fmtDateTime,
  regionStateColor,
  type PoliticalRegion,
  type RegionDataState,
  type RegionStateDetail,
} from "../../lib/political";

export type MapScope = "US" | "WORLD";

interface Props {
  regions: PoliticalRegion[];
  regionStates: RegionStateDetail[];
  scope: MapScope;
  onScopeChange: (scope: MapScope) => void;
  selectedRegionId: string | null;
  onSelectRegion: (regionId: string | null) => void;
  generatedAt?: string | null;
  loading?: boolean;
}

interface MapDatum {
  region: PoliticalRegion;
  detail: RegionStateDetail | undefined;
  state: RegionDataState;
  location: string;
}

const plotConfig = {
  responsive: true,
  displaylogo: false,
  scrollZoom: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d", "toImage"] as never[],
};

export default function PoliticalMap({
  regions,
  regionStates,
  scope,
  onScopeChange,
  selectedRegionId,
  onSelectRegion,
  generatedAt,
  loading,
}: Props) {
  const detailById = useMemo(
    () => new Map(regionStates.map((s) => [s.region_id, s])),
    [regionStates],
  );

  const data = useMemo<MapDatum[]>(() => {
    const wanted: PoliticalRegion["region_type"][] =
      scope === "US" ? ["STATE", "DISTRICT"] : ["COUNTRY"];
    return regions
      .filter((region) => wanted.includes(region.region_type))
      .map((region) => {
        const detail = detailById.get(region.id);
        const location = region.geometry.location_key ?? region.state_code ?? region.name;
        return {
          region,
          detail,
          state: (detail?.state ?? "NO_DATA") as RegionDataState,
          location,
        };
      })
      .filter((datum) => Boolean(datum.location));
  }, [regions, detailById, scope]);

  // `location` (state code / country name) -> region id, for click handling.
  const locationToRegion = useMemo(() => {
    const map = new Map<string, MapDatum>();
    for (const datum of data) map.set(datum.location, datum);
    return map;
  }, [data]);

  // Discrete colorscale: each data-state gets one solid band, no interpolation.
  const colorscale = useMemo(() => {
    const colors = REGION_STATE_ORDER.map((state) => regionStateColor(state));
    const n = colors.length;
    return colors.flatMap((color, index) => [
      [index / n, color] as [number, string],
      [(index + 1) / n, color] as [number, string],
    ]);
  }, []);

  const locations = data.map((d) => d.location);
  const z = data.map((d) => REGION_STATE_ORDER.indexOf(d.state));
  const text = data.map((d) => d.region.name);
  const customdata = data.map((d) => [
    d.region.name,
    REGION_STATE_META[d.state].label,
    d.detail?.election_id ? `Election: ${d.detail.election_id}` : "Election: not specified",
    d.detail?.last_measured_by ? `Last measured by: ${d.detail.last_measured_by}` : "Last measured by: —",
    d.detail?.last_measurement_at ? `Measured: ${fmtDateTime(d.detail.last_measurement_at)}` : "Measured: no sourced date",
    d.detail?.reason ?? REGION_STATE_META[d.state].blurb,
  ]);

  const trace = useMemo<Data>(
    () => ({
      type: "choropleth",
      locationmode: scope === "US" ? "USA-states" : "country names",
      locations,
      z,
      text,
      customdata,
      colorscale,
      zmin: -0.5,
      zmax: REGION_STATE_ORDER.length - 0.5,
      showscale: false,
      marker: { line: { color: "rgba(15,23,42,.85)", width: 0.7 } },
      hovertemplate:
        "<b>%{customdata[0]}</b><br>" +
        "Data state: <b>%{customdata[1]}</b><br>" +
        "%{customdata[2]}<br>" +
        "%{customdata[3]}<br>" +
        "%{customdata[4]}<br>" +
        "<i>%{customdata[5]}</i>" +
        "<extra></extra>",
    } as Data),
    [locations, z, text, customdata, colorscale, scope],
  );

  // Selected region is outlined so the detail panel has a visible anchor even
  // when its fill colour is the neutral "no data" grey.
  const outlineTrace = useMemo<Data | null>(() => {
    const selected = data.find((d) => d.region.id === selectedRegionId);
    if (!selected) return null;
    return {
      type: "choropleth",
      locationmode: scope === "US" ? "USA-states" : "country names",
      locations: [selected.location],
      z: [REGION_STATE_ORDER.indexOf(selected.state)],
      colorscale,
      zmin: -0.5,
      zmax: REGION_STATE_ORDER.length - 0.5,
      showscale: false,
      marker: { line: { color: "#e6edf7", width: 2.4 } },
      hovertemplate: "<b>%{text}</b><extra></extra>",
      text: [selected.region.name],
    } as Data;
  }, [data, selectedRegionId, scope, colorscale]);

  const layout = useMemo<Partial<Layout>>(
    () => ({
      uirevision: `political-${scope}`,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#9daed1", size: 11 },
      margin: { t: 4, l: 4, r: 4, b: 4 },
      dragmode: "pan",
      geo: {
        scope: scope === "US" ? "usa" : "world",
        projection: { type: scope === "US" ? "albers usa" : "natural earth" },
        bgcolor: "rgba(8,14,26,.35)",
        showland: true,
        landcolor: "#131c30",
        showlakes: true,
        lakecolor: "#0b1220",
        showcountries: scope === "WORLD",
        countrycolor: "rgba(120,140,175,.25)",
        showsubunits: scope === "US",
        subunitcolor: "rgba(120,140,175,.18)",
        showframe: false,
        coastlinecolor: "rgba(120,140,175,.25)",
      },
    }),
    [scope],
  );

  const handleClick = (event: Readonly<PlotMouseEvent>) => {
    const point = event?.points?.[0];
    if (!point) return;
    const location = (point as { location?: string }).location;
    if (!location) return;
    const datum = locationToRegion.get(location);
    if (datum) onSelectRegion(datum.region.id === selectedRegionId ? null : datum.region.id);
  };

  return (
    <section className="political-map panel" aria-label="Political data map">
      <div className="political-map-head">
        <div>
          <h2>Geographic data map</h2>
          <p className="dim">
            Shading shows data <strong>availability</strong>, never a party or candidate.
            {generatedAt ? ` Assembled ${fmtDateTime(generatedAt)}.` : ""}
          </p>
        </div>
        <div className="political-scope-tabs" role="tablist" aria-label="Map scope">
          {(["US", "WORLD"] as MapScope[]).map((s) => (
            <button
              key={s}
              role="tab"
              aria-selected={scope === s}
              className={scope === s ? "active" : ""}
              onClick={() => onScopeChange(s)}
            >
              {s === "US" ? "United States" : "World"}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="skeleton skeleton-chart" style={{ height: 460 }} />}

      {!loading && data.length === 0 && (
        <div className="market-state" role="status">
          <strong>No regions available</strong>
          <span>The backend returned no geographic regions for this scope.</span>
        </div>
      )}

      {!loading && data.length > 0 && (
        <div className="political-map-canvas">
          <Plot
            data={outlineTrace ? [trace, outlineTrace] : [trace]}
            layout={layout}
            config={plotConfig}
            style={{ width: "100%", height: 460 }}
            useResizeHandler
            onClick={handleClick}
          />
        </div>
      )}

      <ul className="political-legend" aria-label="Data state legend">
        {REGION_STATE_ORDER.map((state) => (
          <li key={state}>
            <span
              className="political-legend-swatch"
              style={{ background: REGION_STATE_META[state].color }}
              aria-hidden
            />
            <span className="political-legend-label">{REGION_STATE_META[state].label}</span>
            <span className="dim political-legend-blurb">{REGION_STATE_META[state].blurb}</span>
          </li>
        ))}
      </ul>

      <p className="political-map-hint dim">
        Hover for source and measurement date · click a region to open its sourced detail panel ·
        scroll to zoom, drag to pan.
      </p>
    </section>
  );
}
