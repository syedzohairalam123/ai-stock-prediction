/**
 * Phase 21B §8/§27 — live match event timeline.
 *
 * Each row carries its timestamp, event name, the player/team when the source
 * supplied one, an icon and its sequence. The list keeps only the newest rows
 * mounted (`MAX_ROWS`) so a long match cannot mount thousands of nodes on
 * mobile, and it is memoized so an unrelated re-render never rebuilds it.
 */
import { memo } from "react";
import {
  Activity,
  CircleDot,
  Flag,
  Pause,
  Play,
  Radio,
  Swords,
  Target,
  Timer,
  Trophy,
} from "lucide-react";

import { formatDateTime, relTime, type EsportsEvent } from "../../lib/esports";
import { TimelineSkeleton } from "./EsportsSkeletons";

const MAX_ROWS = 60;

const EVENT_ICONS: Record<string, typeof Radio> = {
  MATCH_STARTED: Play,
  MATCH_ENDED: Trophy,
  MATCH_PAUSED: Pause,
  MATCH_RESUMED: Play,
  MAP_STARTED: Flag,
  MAP_ENDED: Flag,
  ROUND_STARTED: CircleDot,
  ROUND_ENDED: Target,
  SCORE_CHANGED: Swords,
  PLAYER_EVENT: Activity,
  OBJECTIVE_EVENT: Target,
};

const EVENT_LABELS: Record<string, string> = {
  MATCH_STARTED: "Match started",
  MATCH_ENDED: "Match ended",
  MATCH_PAUSED: "Match paused",
  MATCH_RESUMED: "Match resumed",
  MAP_STARTED: "Map started",
  MAP_ENDED: "Map ended",
  ROUND_STARTED: "Round started",
  ROUND_ENDED: "Round ended",
  SCORE_CHANGED: "Score changed",
  PLAYER_EVENT: "Player event",
  OBJECTIVE_EVENT: "Objective event",
};

function eventDetail(event: EsportsEvent): string | null {
  const p = event.payload || {};
  const parts: string[] = [];
  if (typeof p.map_name === "string") parts.push(p.map_name);
  if (typeof p.team_a_score === "number" || typeof p.team_b_score === "number") {
    parts.push(`${p.team_a_score ?? "?"} – ${p.team_b_score ?? "?"}`);
  }
  if (typeof p.team_a_name === "string" || typeof p.team_b_name === "string") {
    parts.push(`${p.team_a_name ?? "?"} vs ${p.team_b_name ?? "?"}`);
  }
  if (typeof p.objective_type === "string") parts.push(p.objective_type);
  if (typeof p.player_event_type === "string") parts.push(p.player_event_type);
  if (typeof p.duration_seconds === "number") parts.push(`${Math.round(p.duration_seconds / 60)} min`);
  if (typeof p.winner_id === "string") parts.push(`Winner: ${p.winner_id}`);
  return parts.length ? parts.join(" · ") : null;
}

function MatchTimelineBase({
  events,
  loading = false,
}: {
  events: EsportsEvent[];
  loading?: boolean;
}) {
  if (loading && events.length === 0) {
    return <TimelineSkeleton />;
  }

  if (events.length === 0) {
    return (
      <div className="esp-state esp-state--empty esp-state--inline" role="status">
        <Timer size={22} aria-hidden="true" />
        <h3>No live events available from this data source.</h3>
        <p className="esp-muted">
          Events appear here the moment a provider reports one for this match.
        </p>
      </div>
    );
  }

  const ordered = [...events].sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
  const visible = ordered.slice(-MAX_ROWS);
  const hidden = ordered.length - visible.length;

  return (
    <section className="esp-timeline" aria-label="Live match events">
      <div className="esp-timeline-head">
        <h3>Live match events</h3>
        <span className="esp-muted">{events.length} total</span>
      </div>
      {hidden > 0 && (
        <p className="esp-timeline-note">Showing the latest {MAX_ROWS} events ({hidden} older hidden).</p>
      )}
      <ol className="esp-timeline-list">
        {visible.map((event) => {
          const Icon = EVENT_ICONS[event.type] ?? Radio;
          const detail = eventDetail(event);
          return (
            <li key={event.id} className={`esp-timeline-row esp-ev-${event.type.toLowerCase()}`}>
              <span className="esp-timeline-dot" aria-hidden="true">
                <Icon size={12} />
              </span>
              <div className="esp-timeline-body">
                <div className="esp-timeline-title">
                  <strong>{EVENT_LABELS[event.type] ?? event.type.replace(/_/g, " ")}</strong>
                  <span className="esp-muted">#{event.sequence}</span>
                </div>
                {detail && <p className="esp-timeline-detail">{detail}</p>}
                <div className="esp-timeline-meta">
                  <span title={formatDateTime(event.timestamp)}>{relTime(event.timestamp)}</span>
                  <span className="esp-muted">{event.source}</span>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default memo(MatchTimelineBase);
