/**
 * Phase 21B §7 — game-specific live scoreboards.
 *
 * Each game renders the fields its source actually supplies:
 *  - CS2: map, round (when supplied), team score, match/series state;
 *  - LoL: game time, team score, per-game state;
 *  - Dota 2: game time, team score, per-game objectives/statistics.
 * A field no source published renders as the labelled `N/A` — never a 0.
 */
import { Crosshair, MapPin, Shield, Swords, Timer } from "lucide-react";

import {
  formatClock,
  gameLabel,
  NA,
  type EsportsMatch,
  type EsportsSnapshot,
} from "../../lib/esports";
import MatchStatusBadge from "./MatchStatusBadge";
import { TeamLogo } from "./EsportsImage";

interface ScoreboardProps {
  match: EsportsMatch;
  snapshot?: EsportsSnapshot | null;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="esp-sb-row">
      <span className="esp-sb-label">{label}</span>
      <span className="esp-sb-value">{value === null || value === undefined || value === "" ? NA : value}</span>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function GameTime({ match, snapshot }: ScoreboardProps) {
  const state = asRecord(snapshot?.game_state);
  const fromState = typeof state.game_time_seconds === "number" ? state.game_time_seconds : null;
  const seconds = match.game_time_seconds ?? fromState;
  return (
    <span className="esp-sb-timer" title="Game time reported by the data source">
      <Timer size={12} aria-hidden="true" /> {formatClock(seconds)}
    </span>
  );
}

export default function Scoreboard({ match, snapshot }: ScoreboardProps) {
  const state = asRecord(snapshot?.game_state);
  const paused = state.paused === true;
  const game = match.game_id;

  const currentMapScores = snapshot?.current_map_scores || {};

  return (
    <section className="esp-scoreboard" aria-label={`${gameLabel(game)} scoreboard`}>
      <header className="esp-sb-head">
        <div className="esp-sb-head-left">
          <span className="esp-sb-game-icon" aria-hidden="true">
            {game === "cs2" ? <Crosshair size={16} /> : game === "lol" ? <Swords size={16} /> : <Shield size={16} />}
          </span>
          <strong>{gameLabel(game)}</strong>
          <MatchStatusBadge status={match.status} size="sm" />
          {paused && <span className="esp-sb-paused">Paused</span>}
        </div>
        <div className="esp-sb-head-right">
          <span className="esp-sb-map">
            <MapPin size={12} aria-hidden="true" />
            {match.current_map || (match.map_number > 0 ? `Map ${match.map_number}` : NA)}
          </span>
          {(game === "lol" || game === "dota2") && <GameTime match={match} snapshot={snapshot} />}
        </div>
      </header>

      <div className="esp-sb-body">
        <div className={`esp-sb-team${match.winner_id === match.team_a.id ? " is-winner" : ""}`}>
          <TeamLogo src={match.team_a.logo_url} name={match.team_a.name} size={40} />
          <span className="esp-sb-team-name">{match.team_a.name || NA}</span>
        </div>
        <div className="esp-sb-scoreline" aria-live="polite" aria-label={`Score ${match.score_a} to ${match.score_b}`}>
          <span className={match.score_a > match.score_b ? "leading" : ""}>{match.score_a}</span>
          <span className="esp-sb-colon">:</span>
          <span className={match.score_b > match.score_a ? "leading" : ""}>{match.score_b}</span>
        </div>
        <div className={`esp-sb-team esp-sb-team--right${match.winner_id === match.team_b.id ? " is-winner" : ""}`}>
          <span className="esp-sb-team-name">{match.team_b.name || NA}</span>
          <TeamLogo src={match.team_b.logo_url} name={match.team_b.name} size={40} />
        </div>
      </div>

      {/* ---- game-specific detail ---- */}
      {game === "cs2" && (
        <div className="esp-sb-details">
          <Row label="Map" value={match.current_map || (match.map_number > 0 ? `Map ${match.map_number}` : null)} />
          <Row label="Map number" value={match.map_number > 0 ? match.map_number : null} />
          <Row
            label="Round"
            value={typeof state.round_number === "number" ? (state.round_number as number) : null}
          />
          <Row
            label="Round winner"
            value={typeof state.round_winner === "string" ? (state.round_winner as string) : null}
          />
          <Row label="Series" value={match.best_of > 1 ? `Best of ${match.best_of}` : null} />
          {match.games.length > 0 && (
            <div className="esp-sb-maps">
              {match.games.map((map, index) => (
                <div className="esp-sb-map-row" key={`${map.name ?? index}-${index}`}>
                  <span>{map.name || `Map ${index + 1}`}</span>
                  <span>
                    {map.team_a_score ?? NA} – {map.team_b_score ?? NA}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {game === "lol" && (
        <div className="esp-sb-details">
          <Row label="Series" value={match.best_of > 1 ? `Best of ${match.best_of}` : null} />
          <Row label="Games played" value={match.games.length || null} />
          <Row label="Series score" value={`${match.score_a} – ${match.score_b}`} />
          {match.games.length > 0 && (
            <div className="esp-sb-maps">
              {match.games.map((g, index) => (
                <div className="esp-sb-map-row" key={`${g.number ?? index}-${index}`}>
                  <span>Game {g.number ?? index + 1}</span>
                  <span>{g.state ? g.state : NA}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {game === "dota2" && (
        <div className="esp-sb-details">
          <Row label="Game time" value={formatClock(match.game_time_seconds)} />
          <Row label="Series score" value={`${match.score_a} – ${match.score_b}`} />
          {match.games.length > 0 && (
            <div className="esp-sb-maps">
              {match.games.map((g, index) => (
                <div className="esp-sb-map-row" key={`${g.match_id ?? index}-${index}`}>
                  <span>Game {index + 1}</span>
                  <span>
                    {g.radiant_score ?? NA} – {g.dire_score ?? NA}
                    {g.duration ? ` · ${formatClock(g.duration)}` : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {Object.keys(currentMapScores).length > 0 && (
        <div className="esp-sb-details">
          {Object.entries(currentMapScores).map(([mapName, scores]) => (
            <Row
              key={mapName}
              label={mapName}
              value={`${scores.team_a ?? NA} – ${scores.team_b ?? NA}`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
