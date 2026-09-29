/**
 * Phase 21B §6 — a single match in the live grid.
 *
 * Shows game, tournament, both teams, score, status, current map, start time
 * and last update; clicking opens `/esports/match/:id`. All fields are
 * data-driven — a field the source omitted renders the labelled `N/A`.
 */
import { memo } from "react";
import { ChevronRight, MapPin } from "lucide-react";
import { Link } from "react-router-dom";

import {
  describeMatch,
  formatDateTime,
  gameShort,
  NA,
  relTime,
  type EsportsMatch,
} from "../../lib/esports";
import MatchStatusBadge from "./MatchStatusBadge";
import { TeamLogo } from "./EsportsImage";

function LiveMatchCardBase({ match, showGame = true }: { match: EsportsMatch; showGame?: boolean }) {
  const isLive = match.status === "LIVE" || match.status === "PAUSED" || match.status === "MAP_BREAK";
  return (
    <Link
      to={`/esports/match/${encodeURIComponent(match.id)}`}
      className={`esp-match-card${isLive ? " is-live" : ""}`}
      aria-label={describeMatch(match)}
    >
      <div className="esp-match-head">
        {showGame && <span className="esp-game-tag">{gameShort(match.game_id)}</span>}
        <MatchStatusBadge status={match.status} size="sm" />
        <span className={`esp-quality esp-quality--${(match.data_quality || "unavailable").toLowerCase()}`}>
          {match.data_quality || "UNAVAILABLE"}
        </span>
      </div>

      <p className="esp-match-tournament" title={match.tournament_name ?? undefined}>
        {match.tournament_name || NA}
      </p>

      <div className="esp-match-teams">
        <div className={`esp-match-team${match.winner_id === match.team_a.id ? " is-winner" : ""}`}>
          <TeamLogo src={match.team_a.logo_url} name={match.team_a.name} size={30} />
          <span className="esp-match-team-name">{match.team_a.name || NA}</span>
          <span className="esp-match-score">{match.score_a}</span>
        </div>
        <div className={`esp-match-team${match.winner_id === match.team_b.id ? " is-winner" : ""}`}>
          <TeamLogo src={match.team_b.logo_url} name={match.team_b.name} size={30} />
          <span className="esp-match-team-name">{match.team_b.name || NA}</span>
          <span className="esp-match-score">{match.score_b}</span>
        </div>
      </div>

      <div className="esp-match-foot">
        <span className="esp-match-map">
          <MapPin size={11} aria-hidden="true" />
          {match.current_map || (match.map_number > 0 ? `Map ${match.map_number}` : "Map —")}
          {match.best_of > 1 ? ` · Bo${match.best_of}` : ""}
        </span>
        <span className="esp-muted">
          {isLive ? `Updated ${relTime(match.last_updated)}` : formatDateTime(match.scheduled_at)}
        </span>
        <ChevronRight size={14} aria-hidden="true" className="esp-match-chevron" />
      </div>
    </Link>
  );
}

export default memo(LiveMatchCardBase);
