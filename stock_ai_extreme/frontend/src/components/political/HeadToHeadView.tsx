/**
 * Phase 18 — neutral head-to-head view (spec §10).
 *
 * Sourced numbers side by side, grouped by source and ordered by source then
 * measurement date. There is deliberately no "winner", "best candidate" or
 * "recommended" column — the response model does not contain those fields, so
 * the UI cannot invent one.
 */
import { Scale } from "lucide-react";
import { useHeadToHead } from "../../hooks/usePoliticalQueries";
import MeasurementCard from "./MeasurementCard";
import { MEASUREMENT_TYPE_META, fmtDateTime } from "../../lib/political";

interface Props {
  electionId?: string;
  regionId?: string;
}

export default function HeadToHeadView({ electionId, regionId }: Props) {
  const query = useHeadToHead(electionId, regionId);

  if (!electionId && !regionId) {
    return (
      <section className="political-headtohead panel" aria-label="Head to head">
        <h2><Scale size={15} aria-hidden /> Head-to-head comparison</h2>
        <div className="market-state" role="status">
          <strong>Pick an election or region</strong>
          <span>Select an election from the filter bar to compare the sourced measurements side by side.</span>
        </div>
      </section>
    );
  }

  return (
    <section className="political-headtohead panel" aria-label="Head to head">
      <div className="political-headtohead-head">
        <div>
          <h2><Scale size={15} aria-hidden /> Head-to-head comparison</h2>
          <p className="dim">{query.data?.note ?? "Side-by-side sourced measurements only."}</p>
        </div>
      </div>

      {query.isLoading && <div className="skeleton" style={{ height: 140 }} />}

      {query.isError && (
        <div className="market-state" role="status">
          <strong>No sourced measurements</strong>
          <span>
            {(query.error as Error)?.message ?? "No source has published a measurement for this selection."}
          </span>
        </div>
      )}

      {query.data && query.data.rows.length === 0 && (
        <div className="market-state" role="status">
          <strong>No sourced measurements</strong>
          <span>This selection has no measurements from any external source.</span>
        </div>
      )}

      {query.data && Object.keys(query.data.grouped_by_source).length > 0 && (
        <div className="political-headtohead-groups">
          {Object.entries(query.data.grouped_by_source).map(([source, rows]) => (
            <section key={source} className="political-source-group">
              <header>
                <h3>{source}</h3>
                <span className="dim">{rows.length} measurement{rows.length === 1 ? "" : "s"}</span>
              </header>
              <div className="political-headtohead-grid">
                {rows.map((row) => (
                  <MeasurementCard key={row.id} measurement={row} emphasis />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {query.data && (
        <footer className="political-headtohead-foot dim">
          <p>{query.data.disclaimer}</p>
          <p>
            Measurement families stay separate:{" "}
            {Object.values(MEASUREMENT_TYPE_META).map((meta) => meta.label).join(" · ")}.
            {query.data.retrieval?.generated_at ? ` Assembled ${fmtDateTime(query.data.retrieval.generated_at)}.` : ""}
          </p>
        </footer>
      )}
    </section>
  );
}
