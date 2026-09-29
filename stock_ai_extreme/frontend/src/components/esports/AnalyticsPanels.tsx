/**
 * Phase 21C §1–§5, §10, §11, §12 — analytics display panels.
 *
 * Three panels, one honesty contract:
 *  - TeamAnalyticsPanel: form / map win rates / durations, each with the sample
 *    size and date range the backend attached — a percentage is never rendered
 *    without the n it was computed from;
 *  - MatchAnalyticsPanel: event frequency + ANOMALY DETECTED findings, exactly
 *    labelled as the backend labels them, never speculated about;
 *  - DataQualityPanel: per-match HIGH/MEDIUM/LOW grades with reasons, plus
 *    SOURCE DISCREPANCY findings surfaced verbatim.
 */
import { memo } from "react";
import { Activity, AlertOctagon, Gauge, ShieldAlert } from "lucide-react";

import { useDataQuality, useMatchAnalytics, useTeamAnalytics } from "../../hooks/useEsportsAnalytics";
import { formatDateTime, gameLabel, NA } from "../../lib/esports";
import type { AggregateQuality, DataQualityResponse, FormEntry, MapStat, MetricBlock, TeamFormValue } from "../../lib/esportsAnalytics";

// ---------------------------------------------------------------------------
// small building blocks
// ---------------------------------------------------------------------------

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return NA;
  return `${Math.round(value * 100)}%`;
}

function dateRange(range: { from: string | null; to: string | null }): string {
  if (!range.from && !range.to) return NA;
  const from = range.from ? formatDateTime(range.from).split(",")[0] : "…";
  const to = range.to ? formatDateTime(range.to).split(",")[0] : "…";
  return `${from} → ${to}`;
}

const QualityBadge = memo(function QualityBadge({ label }: { label: string }) {
  const tone = label.toLowerCase();
  return <span className={`esp-mode esp-mode--${tone}`}>{label}</span>;
});

function SampleNote({
  sample,
  range,
  sources,
  quality,
}: {
  sample: number;
  range: { from: string | null; to: string | null };
  sources: string[];
  quality: string;
}) {
  return (
    <p className="esp-metric-note esp-muted">
      n={sample} · {dateRange(range)} · {sources.length ? sources.join(", ") : NA} ·{" "}
      <QualityBadge label={quality} />
    </p>
  );
}

function FormList({ block }: { block: MetricBlock<TeamFormValue> & { form: FormEntry[] } }) {
  return (
    <div className="esp-an-panel">
      <div className="esp-an-headline">
        <strong>{pct(block.value?.win_rate ?? null)}</strong>
        <span className="esp-muted">win rate</span>
        <span className="esp-an-chips">
          <span className="esp-an-chip esp-an-chip--w">{block.value?.wins ?? 0}W</span>
          <span className="esp-an-chip esp-an-chip--l">{block.value?.losses ?? 0}L</span>
          {block.value?.streak && <span className="esp-an-chip">{block.value.streak}</span>}
        </span>
      </div>
      <SampleNote
        sample={block.sample_size}
        range={block.date_range}
        sources={block.sources}
        quality={block.data_quality}
      />
      {block.form && block.form.length > 0 && (
        <ul className="esp-form-list">
          {block.form.slice(-5).reverse().map((entry) => (
            <li key={`${entry.match_id}-${entry.played_at ?? ""}`} className="esp-form-row">
              <span className={`esp-form-dot ${entry.outcome === "win" ? "esp-form-dot--w" : entry.outcome === "loss" ? "esp-form-dot--l" : "esp-form-dot--d"}`} aria-hidden="true" />
              <span className="esp-form-opponent">{entry.opponent_name || entry.opponent_id}</span>
              <span className="esp-form-score">{entry.score}</span>
              <span className="esp-form-when esp-muted">{entry.played_at ? formatDateTime(entry.played_at).split(",")[0] : NA}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MapTable({ maps }: { maps: MapStat[] }) {
  if (maps.length === 0) return null;
  return (
    <table className="esp-map-table">
      <caption className="esp-visually-hidden">Map win rates</caption>
      <thead>
        <tr>
          <th scope="col">Map</th>
          <th scope="col">W–L</th>
          <th scope="col">Win rate</th>
          <th scope="col">n</th>
        </tr>
      </thead>
      <tbody>
        {maps.slice(0, 6).map((map) => (
          <tr key={map.map}>
            <th scope="row">{map.map}</th>
            <td>{map.wins}–{map.losses}</td>
            <td>{pct(map.win_rate)}</td>
            <td className="esp-muted">{map.sample_size}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------------------
// §1–§4 — team analytics panel
// ---------------------------------------------------------------------------

export function TeamAnalyticsPanel({ teamId, gameId }: { teamId: string | null | undefined; gameId?: string | null }) {
  const query = useTeamAnalytics(teamId, gameId);
  const data = query.data;

  return (
    <section className="esp-panel esp-an" aria-label="Team analytics">
      <h3>
        <Gauge size={13} aria-hidden="true" /> Team analytics
      </h3>
      {query.isPending && <p className="esp-muted">Computing from historical results…</p>}
      {query.isError && (
        <p className="esp-error-text" role="alert">
          Analytics unavailable for this team.
          <button type="button" className="esp-btn esp-btn--sm" onClick={() => query.refetch()}>Retry</button>
        </p>
      )}
      {data && (
        <>
          <p className="esp-an-sub esp-muted">
            {data.sample_size} tracked matches · {dateRange(data.date_range)} · {data.sources.join(", ") || NA}
          </p>
          <h4 className="esp-an-h4">Recent form</h4>
          <FormList block={data.form} />
          {data.map_analytics.available ? (
            <>
              <h4 className="esp-an-h4">Map analytics</h4>
              <MapTable maps={data.map_analytics.maps} />
              <SampleNote
                sample={data.map_analytics.sample_size}
                range={data.map_analytics.date_range}
                sources={data.map_analytics.sources}
                quality={data.map_analytics.data_quality}
              />
            </>
          ) : (
            <p className="esp-metric-note esp-muted">
              Map analytics: {data.map_analytics.reason || "unavailable for this team"}.
            </p>
          )}
          <h4 className="esp-an-h4">Consistency</h4>
          <p className="esp-metric-note">
            {data.historical_consistency.value !== null
              ? `${Math.round(data.historical_consistency.value * 100)} / 100`
              : NA}{" "}
            <span className="esp-muted">
              (n={data.historical_consistency.sample_size}, <QualityBadge label={data.historical_consistency.data_quality} />)
            </span>
          </p>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// §10 — match analytics panel (anomaly detection)
// ---------------------------------------------------------------------------

export function MatchAnalyticsPanel({ matchId }: { matchId: string }) {
  const query = useMatchAnalytics(matchId);
  const data = query.data;

  return (
    <section className="esp-panel esp-an" aria-label="Match analytics">
      <h3>
        <Activity size={13} aria-hidden="true" /> Match analytics
      </h3>
      {query.isPending && <p className="esp-muted">Analyzing event stream…</p>}
      {query.isError && (
        <p className="esp-error-text" role="alert">
          Match analytics unavailable.
          <button type="button" className="esp-btn esp-btn--sm" onClick={() => query.refetch()}>Retry</button>
        </p>
      )}
      {data && (
        <>
          {data.event_frequency.available ? (
            <p className="esp-metric-note">
              {data.event_frequency.total_events} events ·{" "}
              {data.event_frequency.events_per_minute !== null
                ? `${data.event_frequency.events_per_minute}/min`
                : NA}{" "}
              <span className="esp-muted">
                (n={data.event_frequency.sample_size}, <QualityBadge label={data.event_frequency.data_quality} />)
              </span>
            </p>
          ) : (
            <p className="esp-metric-note esp-muted">Event frequency: no events recorded yet.</p>
          )}

          {data.duration_stats.available && data.duration_stats.value && (
            <p className="esp-metric-note">
              Duration avg {Math.round(data.duration_stats.value.mean_seconds / 60)} min
              <span className="esp-muted"> (n={data.duration_stats.sample_size})</span>
            </p>
          )}

          <div className={`esp-anomaly ${data.anomaly_detection.count > 0 ? "esp-anomaly--flagged" : ""}`}>
            <div className="esp-anomaly-head">
              <AlertOctagon size={14} aria-hidden="true" />
              <strong>{data.anomaly_detection.label}</strong>
              <span className="esp-muted">{data.anomaly_detection.count} finding(s)</span>
            </div>
            {data.anomaly_detection.findings.length > 0 && (
              <ul className="esp-anomaly-list">
                {data.anomaly_detection.findings.slice(0, 5).map((finding, index) => (
                  <li key={`${finding.method}-${finding.index}-${index}`}>
                    <span className="esp-anomaly-method">{finding.method}</span>
                    {finding.reference && <span className="esp-muted"> {finding.reference}</span>}
                    {finding.z_score !== undefined && (
                      <span className="esp-muted"> z={finding.z_score} ({finding.direction})</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="esp-metric-note esp-muted">{data.anomaly_detection.note}</p>
          </div>

          {data.source_consistency.count > 0 && (
            <div className="esp-discrepancy" role="alert">
              <ShieldAlert size={14} aria-hidden="true" />
              <div>
                <strong>SOURCE DISCREPANCY</strong>
                <ul>
                  {data.source_consistency.discrepancies.slice(0, 3).map((discrepancy, index) => (
                    <li key={index}>
                      <span className="esp-muted">{discrepancy.kind}</span> {discrepancy.field}:{" "}
                      {String(discrepancy.values[0])} vs {String(discrepancy.values[1])}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <p className="esp-metric-note esp-muted">
            Team A form {pct(data.team_a.form.value?.win_rate ?? null)} (n={data.team_a.form.sample_size}) · Team B
            form {pct(data.team_b.form.value?.win_rate ?? null)} (n={data.team_b.form.sample_size})
          </p>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// §11/§12 — data quality panel (hub-level)
// ---------------------------------------------------------------------------

export function DataQualityPanel({ gameId }: { gameId?: string | null }) {
  const query = useDataQuality(gameId ?? null, 25);
  const data = query.data;

  return (
    <section className="esp-panel esp-an" aria-label="Data quality">
      <h3>
        <ShieldAlert size={13} aria-hidden="true" /> Data quality
      </h3>
      {query.isPending && <p className="esp-muted">Evaluating feed quality…</p>}
      {query.isError && (
        <p className="esp-error-text" role="alert">
          Data quality unavailable.
          <button type="button" className="esp-btn esp-btn--sm" onClick={() => query.refetch()}>Retry</button>
        </p>
      )}
      {data && (
        <>
          <p className="esp-metric-note">
            Feed grade <QualityBadge label={data.aggregate.label} />
            {data.aggregate.score !== null && ` · ${Math.round(data.aggregate.score * 100)} / 100`}
            <span className="esp-muted"> ({data.aggregate.evaluated} matches evaluated)</span>
          </p>

          {data.source_consistency.count > 0 && (
            <div className="esp-discrepancy" role="alert">
              <ShieldAlert size={14} aria-hidden="true" />
              <div>
                <strong>SOURCE DISCREPANCY ({data.source_consistency.count})</strong>
                <ul>
                  {data.source_consistency.discrepancies.slice(0, 3).map((discrepancy, index) => (
                    <li key={index}>
                      {discrepancy.field} — {discrepancy.sources.filter(Boolean).join(" vs ")}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <ul className="esp-quality-list">
            {data.matches.slice(0, 6).map((match) => (
              <li key={match.match_id} className="esp-quality-row">
                <QualityBadge label={match.label} />
                <span className="esp-quality-meta esp-muted">
                  {gameLabel(match.game_id)} · {match.source || NA}
                  {match.reasons.length > 0 && ` · ${match.reasons[0]}`}
                </span>
              </li>
            ))}
          </ul>

          {(() => {
            // Defensive shape guard: the anomaly scan is an async worker
            // product; older cached payloads or a worker that has not run yet
            // can omit any field. Missing data is rendered as N/A — never a
            // crash, never a fabricated number.
            const scan = data.anomaly_scan as
              | (NonNullable<DataQualityResponse["anomaly_scan"]> & { matches_scanned?: number })
              | null
              | undefined;
            const findings = Array.isArray(scan?.findings) ? scan!.findings : [];
            const matchesScanned =
              typeof scan?.matches_scanned === "number" && Number.isFinite(scan!.matches_scanned)
                ? scan!.matches_scanned
                : null;
            if (findings.length === 0) return null;
            return (
              <p className="esp-metric-note esp-muted">
                Background anomaly scan: {findings.length} finding(s) across{" "}
                {matchesScanned === null ? "N/A" : matchesScanned} matches.
              </p>
            );
          })()}
        </>
      )}
    </section>
  );
}

// Aggregate re-export for convenience.
export { AggregateQuality };
