/**
 * Phase 21B §2/§3 — featured match hero.
 *
 * Displays the backend's ranked featured match (never simply the first row) and
 * only fields the source actually provided: game, tournament, both teams and
 * logos, current score, series score, current map, map number, best-of, status,
 * a timer where the source publishes one, last update and data source.
 */
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Clock, MapPin, Trophy } from "lucide-react";
import { Link } from "react-router-dom";

import {
  describeMatch,
  formatClock,
  formatDateTime,
  gameLabel,
  NA,
  relTime,
  type EsportsMatch,
} from "../../lib/esports";
import MatchStatusBadge from "./MatchStatusBadge";
import { TeamLogo } from "./EsportsImage";
import { HeroSkeleton } from "./EsportsSkeletons";

const LIVE_STATUSES = new Set(["LIVE", "PAUSED", "MAP_BREAK"]);

/** A ticking match clock, only when the provider supplies a real start time. */
function MatchClock({ match }: { match: EsportsMatch }) {
  const [tick, setTick] = useState(0);
  const live = LIVE_STATUSES.has(match.status);
  const hasSourceTime = typeof match.game_time_seconds === "number" && match.game_time_seconds >= 0;
  const base = match.started_at || match.scheduled_at;

  useEffect(() => {
    if (!live || hasSourceTime || !base) return;
    const id = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, [live, hasSourceTime, base]);

  if (hasSourceTime) {
    return (
      <span className="esp-hero-timer" title="Game time reported by the data source">
        <Clock size={12} aria-hidden="true" /> Game time {formatClock(match.game_time_seconds)}
      </span>
    );
  }
  if (!live || !base) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(base).getTime()) / 1000) + tick * 0);
  return (
    <span className="esp-hero-timer" title="Elapsed since the published start time">
      <Clock size={12} aria-hidden="true" /> {formatClock(seconds)}
    </span>
  );
}

export default function FeaturedMatchHero({
  match,
  loading = false,
  error = null,
  onRetry,
}: {
  match: EsportsMatch | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}) {
  if (loading && !match) return <HeroSkeleton />;

  if (error && !match) {
    return (
      <div className="esp-hero esp-hero--state" role="alert">
        <AlertTriangle size={26} aria-hidden="true" />
        <h2>Featured match unavailable</h2>
        <p>{error}</p>
        {onRetry && (
          <button type="button" className="esp-btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    );
  }

  if (!match) {
    return (
      <div className="esp-hero esp-hero--state" role="status">
        <Trophy size={26} aria-hidden="true" />
        <h2>No live matches currently available.</h2>
        <p className="esp-muted">
          The hub will surface the top-ranked match here as soon as a provider reports one.
        </p>
      </div>
    );
  }

  return (
    <article className={`esp-hero${LIVE_STATUSES.has(match.status) ? " is-live" : ""}`} aria-label={describeMatch(match)}>
      <div className="esp-hero-top">
        <span className="esp-hero-flag">Featured</span>
        <MatchStatusBadge status={match.status} />
        <span className={`esp-mode esp-mode--${(match.data_mode || "delayed").toLowerCase()}`}>{match.data_mode}</span>
        <span className="esp-hero-game">{gameLabel(match.game_id)}</span>
      </div>

      <p className="esp-hero-tournament">
        <Trophy size={12} aria-hidden="true" />
        {match.tournament_name ? (
          <Link to={`/esports/tournament/${encodeURIComponent(match.tournament_id)}`}>
            {match.tournament_name}
          </Link>
        ) : (
          NA
        )}
      </p>

      <div className="esp-hero-teams">
        <div className="esp-hero-team">
          <TeamLogo src={match.team_a.logo_url} name={match.team_a.name} size={64} />
          <h2 className="esp-hero-team-name">{match.team_a.name || NA}</h2>
        </div>

        <div className="esp-hero-score" aria-live="polite">
          <div className="esp-hero-scoreline">
            <span className={match.score_a > match.score_b ? "leading" : ""}>{match.score_a}</span>
            <span className="esp-hero-colon">:</span>
            <span className={match.score_b > match.score_a ? "leading" : ""}>{match.score_b}</span>
          </div>
          <div className="esp-hero-series">Series score</div>
          <div className="esp-hero-mapinfo">
            <span>
              <MapPin size={11} aria-hidden="true" /> {match.current_map || (match.map_number > 0 ? `Map ${match.map_number}` : "Map —")}
            </span>
            {match.map_number > 0 && <span>Map {match.map_number}</span>}
            {match.best_of > 1 && <span>Best of {match.best_of}</span>}
          </div>
        </div>

        <div className="esp-hero-team">
          <TeamLogo src={match.team_b.logo_url} name={match.team_b.name} size={64} />
          <h2 className="esp-hero-team-name">{match.team_b.name || NA}</h2>
        </div>
      </div>

      <div className="esp-hero-foot">
        <MatchClock match={match} />
        <span className="esp-muted">Last updated {relTime(match.last_updated)}</span>
        <span className="esp-muted" title={`Scheduled ${formatDateTime(match.scheduled_at)}`}>
          Source: {match.source}
        </span>
        <Link className="esp-btn esp-btn--primary" to={`/esports/match/${encodeURIComponent(match.id)}`}>
          Open match <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </article>
  );
}
