/**
 * Phase 18 — one sourced measurement, rendered with full provenance.
 *
 * A card can only exist for a measurement the backend actually received from a
 * named source, so it always has a type badge, a source, a measurement date and
 * a retrieval date. Uncertainty is shown **only** when the source supplied it.
 */
import {
  MEASUREMENT_TYPE_META,
  activityLabel,
  fmtDate,
  fmtPct,
  relativeTime,
  uncertaintyLabel,
  type ForecastMeasurement,
} from "../../lib/political";

interface Props {
  measurement: ForecastMeasurement;
  /** Highlight the numeric share? Used in head-to-head view. */
  emphasis?: boolean;
}

export default function MeasurementCard({ measurement, emphasis }: Props) {
  const typeMeta = MEASUREMENT_TYPE_META[measurement.measurement_type];
  const uncertainty = uncertaintyLabel(measurement.uncertainty);
  const activity = activityLabel(measurement.activity);

  return (
    <article className="political-measurement">
      <div className="political-measurement-top">
        <div>
          <h4>{measurement.candidate_or_outcome}</h4>
          <div className="political-measurement-type-row">
            <span className={`political-type-badge ${measurement.measurement_type.toLowerCase()}`}>
              {typeMeta.label}
            </span>
            {!measurement.is_current && <span className="political-type-badge muted">not current</span>}
          </div>
        </div>
        <div className={emphasis ? "political-measurement-value emphasis" : "political-measurement-value"}>
          {fmtPct(measurement.probability)}
        </div>
      </div>

      <dl className="political-provenance">
        <div>
          <dt>Source</dt>
          <dd>
            {measurement.source_url ? (
              <a href={measurement.source_url} target="_blank" rel="noopener noreferrer">
                {measurement.source}
              </a>
            ) : (
              measurement.source
            )}
          </dd>
        </div>
        <div>
          <dt>Type</dt>
          <dd>{typeMeta.label} — {typeMeta.blurb}</dd>
        </div>
        <div>
          <dt>Measured</dt>
          <dd>
            {fmtDate(measurement.measured_at)} <span className="dim">({relativeTime(measurement.measured_at)})</span>
          </dd>
        </div>
        <div>
          <dt>Retrieved</dt>
          <dd>{fmtDate(measurement.retrieved_at)}</dd>
        </div>
        {measurement.methodology && (
          <div>
            <dt>Methodology</dt>
            <dd>{measurement.methodology}</dd>
          </div>
        )}
        {measurement.sample_size !== null && (
          <div>
            <dt>Sample / volume</dt>
            <dd>{measurement.sample_size.toLocaleString()}</dd>
          </div>
        )}
        {measurement.population && (
          <div>
            <dt>Population</dt>
            <dd>{measurement.population}</dd>
          </div>
        )}
        {uncertainty && (
          <div>
            <dt>Uncertainty</dt>
            <dd>{uncertainty}</dd>
          </div>
        )}
        {!uncertainty && (
          <div>
            <dt>Uncertainty</dt>
            <dd className="dim">Not published by the source.</dd>
          </div>
        )}
        {activity && (
          <div>
            <dt>Activity</dt>
            <dd>{activity}</dd>
          </div>
        )}
        {measurement.notes && (
          <div>
            <dt>Note</dt>
            <dd className="dim">{measurement.notes}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}
