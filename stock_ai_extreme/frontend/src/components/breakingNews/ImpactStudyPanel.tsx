/**
 * Phase 17 (spec §7, §9, §10) — observed-movement event study.
 *
 * One impact row is an anecdote; this panel is the sample. It renders the
 * aggregate of movement rows the desk has already measured, with the
 * denominator always on screen:
 *
 * * `sample_size` is the number of *measured* observations — a group below the
 *   configured minimum is rendered as "insufficient observations" rather than as
 *   an authoritative average.
 * * Rows that could not be measured are shown separately as
 *   `unavailable_samples`; they are never folded into the mean as 0%.
 * * Every figure is a description of the past ("observed after publication") and
 *   the disclaimer is always visible, because an aggregate invites causal
 *   reading more than a single number does.
 */
import { BarChart3, FlaskConical, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import {
  WINDOW_LABELS,
  fixed,
  formatDateTime,
  signed,
  timeAgo,
  type ImpactStudy,
  type ImpactStudyGroup,
  type ObservedMovementStats,
} from "../../lib/breakingNews";

interface Props {
  study: ImpactStudy | null;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  hours?: number;
}

export default function ImpactStudyPanel({ study, loading = false, error = null, onRefresh, hours }: Props) {
  const overall = study?.overall ?? null;

  return (
    <section className="bn-card bn-study" aria-live="polite">
      <header className="bn-card-head">
        <h3>
          <FlaskConical size={15} aria-hidden /> Observed movement study
        </h3>
        <div className="bn-study-actions">
          {study && (
            <span className="bn-muted">
              {study.measured_samples} measured · {study.unavailable_samples} unavailable · min sample{" "}
              {study.min_sample} · window {study.window ? WINDOW_LABELS[study.window as keyof typeof WINDOW_LABELS] ?? study.window : `${study.hours}h`}
            </span>
          )}
          {onRefresh && (
            <button type="button" className="bn-ghost-btn" onClick={onRefresh} disabled={loading}>
              <RefreshCw size={12} className={loading ? "bn-spin" : undefined} aria-hidden /> Refresh
            </button>
          )}
        </div>
      </header>

      {error && (
        <p className="bn-warning" role="alert">
          {error}
        </p>
      )}
      {loading && !study && <p className="bn-muted">Aggregating stored movement observations…</p>}

      {study && !overall && <p className="bn-muted">The study returned no observations.</p>}

      {study && overall && (
        <>
          {overall.sample_size === 0 ? (
            <p className="bn-muted">
              No measured movement observations in this window. Impact rows only exist where a provider returned real
              timestamped bars on both sides of a publication time, so this panel stays empty until the desk has
              measured something.
            </p>
          ) : (
            <>
              <div className="bn-study-summary">
                <Metric label="Observations" value={String(overall.sample_size)} hint="Measured movements in the sample" />
                <Metric
                  label="Mean move"
                  value={signed(overall.mean_percent, 3, "%")}
                  tone={toneOf(overall.mean_percent)}
                />
                <Metric label="Median move" value={signed(overall.median_percent, 3, "%")} tone={toneOf(overall.median_percent)} />
                <Metric
                  label="Dispersion (σ)"
                  value={overall.stdev_percent === null ? "single observation" : fixed(overall.stdev_percent, 3)}
                  hint="Sample standard deviation; undefined for a single observation"
                />
                <Metric
                  label="Up / down"
                  value={`${overall.up} / ${overall.down}${overall.flat ? ` (${overall.flat} flat)` : ""}`}
                />
                <Metric
                  label="Share up"
                  value={overall.hit_rate_up === null ? "unavailable" : `${(overall.hit_rate_up * 100).toFixed(1)}%`}
                  hint="Share of measured observations with a positive move — a description of this sample, not a probability"
                />
                <Metric label="Mean |move|" value={signed(overall.mean_absolute_percent, 3, "%")} />
                <Metric
                  label="Mean σ of sample"
                  value={overall.mean_realized_volatility_percent === null ? "unavailable" : fixed(overall.mean_realized_volatility_percent, 3)}
                />
              </div>

              {(overall.best || overall.worst) && (
                <div className="bn-study-extremes">
                  {overall.best && (
                    <div className="bn-study-extreme bn-pos">
                      <TrendingUp size={13} aria-hidden />
                      <span className="bn-k">Largest observed gain</span>
                      <span className="bn-v">
                        {signed(overall.best.price_change_percent, 2, "%")} · {overall.best.entity}
                      </span>
                      <span className="bn-muted">
                        {overall.best.observation_window} window · {timeAgo(overall.best.news_published_at)}
                      </span>
                    </div>
                  )}
                  {overall.worst && (
                    <div className="bn-study-extreme bn-neg">
                      <TrendingDown size={13} aria-hidden />
                      <span className="bn-k">Largest observed loss</span>
                      <span className="bn-v">
                        {signed(overall.worst.price_change_percent, 2, "%")} · {overall.worst.entity}
                      </span>
                      <span className="bn-muted">
                        {overall.worst.observation_window} window · {timeAgo(overall.worst.news_published_at)}
                      </span>
                    </div>
                  )}
                </div>
              )}

              <GroupTable
                title="By entity"
                icon={BarChart3}
                groups={study.by_entity}
                minSample={study.min_sample}
                empty="No entity has a measured observation yet."
              />

              <GroupTable
                title="By observation window"
                groups={study.by_window}
                minSample={study.min_sample}
                empty="No observation window has a measured observation yet."
              />

              <p className="bn-note">{study.note}</p>
              <p className="bn-note bn-note-strong">{study.disclaimer}</p>
              <p className="bn-muted">
                Computed {formatDateTime(study.generated_at)} over movements observed between{" "}
                {formatDateTime(overall.first_observed_at)} and {formatDateTime(overall.last_observed_at)}.
              </p>
            </>
          )}
          {hours !== undefined && study.hours !== hours && (
            <p className="bn-muted">Data window: {study.hours}h (requested {hours}h).</p>
          )}
        </>
      )}
    </section>
  );
}

function GroupTable({
  title,
  icon: Icon,
  groups,
  minSample,
  empty,
}: {
  title: string;
  icon?: typeof BarChart3;
  groups: ImpactStudyGroup[];
  minSample: number;
  empty: string;
}) {
  if (groups.length === 0) {
    return (
      <div className="bn-study-block">
        <h4>
          {Icon && <Icon size={13} aria-hidden />} {title}
        </h4>
        <p className="bn-muted">{empty}</p>
      </div>
    );
  }

  const sufficient = groups.filter((group) => group.sufficient_sample);

  return (
    <div className="bn-study-block">
      <h4>
        {Icon && <Icon size={13} aria-hidden />} {title}
        <span className="bn-muted">
          {sufficient.length} of {groups.length} groups reach the {minSample}-observation minimum
        </span>
      </h4>
      <table className="bn-table">
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">n</th>
            <th scope="col">Mean</th>
            <th scope="col">Median</th>
            <th scope="col">σ</th>
            <th scope="col">Up / down</th>
            <th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.key}>
              <td>{group.label}</td>
              <td>{group.stats.sample_size}</td>
              <td className={toneOf(group.stats.mean_percent)}>{signed(group.stats.mean_percent, 3, "%")}</td>
              <td>{signed(group.stats.median_percent, 3, "%")}</td>
              <td>{group.stats.stdev_percent === null ? "unavailable" : fixed(group.stats.stdev_percent, 3)}</td>
              <td>
                {group.stats.up} / {group.stats.down}
                {group.stats.flat > 0 && <span className="bn-muted"> ({group.stats.flat} flat)</span>}
              </td>
              <td>
                {group.sufficient_sample ? (
                  <span className="bn-badge bn-mag-low">sufficient</span>
                ) : (
                  <span className="bn-badge bn-mag-none" title={`Fewer than ${minSample} measured observations`}>
                    insufficient
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="bn-study-metric" title={hint}>
      <span className="bn-k">{label}</span>
      <span className={`bn-v-sm ${tone ?? ""}`}>{value}</span>
    </div>
  );
}

/** Colour by direction only; `null` stays neutral rather than reading as 0. */
function toneOf(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  if (value > 0) return "bn-pos";
  if (value < 0) return "bn-neg";
  return "";
}
