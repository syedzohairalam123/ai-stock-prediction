/**
 * Phase 21B §12/§13 — team and player sections.
 *
 * Teams show name, logo, region, current score and tournament. Players show
 * name, handle, role, country, avatar and any statistics the provider attached.
 * A field the source omitted renders `N/A`; a missing roster renders an honest
 * empty state — no player statistic is ever invented (§12).
 */
import { Users } from "lucide-react";

import { NA, type EsportsMatch, type EsportsPlayer, type TeamRef } from "../../lib/esports";
import { PlayerAvatar, TeamLogo } from "./EsportsImage";

function TeamBlock({ team, score, tournamentName }: { team: TeamRef; score: number; tournamentName: string | null }) {
  return (
    <div className="esp-team-block">
      <div className="esp-team-block-head">
        <TeamLogo src={team.logo_url} name={team.name} size={44} />
        <div>
          <h4>{team.name || NA}</h4>
          <p className="esp-muted">{team.region || "Region N/A"}</p>
        </div>
        <span className="esp-team-score" aria-label={`Score ${score}`}>
          {score}
        </span>
      </div>
      <dl className="esp-team-facts">
        <div>
          <dt>Tournament</dt>
          <dd>{tournamentName || NA}</dd>
        </div>
        <div>
          <dt>Short code</dt>
          <dd>{team.short_name || NA}</dd>
        </div>
        {team.metadata && typeof team.metadata === "object" && "wins" in team.metadata && (
          <div>
            <dt>Record</dt>
            <dd>
              {String((team.metadata as Record<string, unknown>).wins ?? NA)}W ·{" "}
              {String((team.metadata as Record<string, unknown>).losses ?? NA)}L
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function PlayerRow({ player }: { player: EsportsPlayer }) {
  const meta = player.meta_data || {};
  const avatar = typeof meta.avatar_url === "string" ? meta.avatar_url : null;
  const stats: string[] = [];
  for (const key of ["rating", "adr", "kast", "wins", "games_played"]) {
    const value = meta[key];
    if (typeof value === "number") stats.push(`${key.toUpperCase()} ${Number.isInteger(value) ? value : value.toFixed(2)}`);
  }
  return (
    <li className="esp-player">
      <PlayerAvatar src={avatar} name={player.handle || player.name} size={38} />
      <div className="esp-player-body">
        <div className="esp-player-name">
          <strong>{player.handle || player.name || NA}</strong>
          {player.name && player.name !== player.handle && <span className="esp-muted">{player.name}</span>}
        </div>
        <div className="esp-player-meta">
          <span>{player.role || "Role N/A"}</span>
          <span>{player.country || "Country N/A"}</span>
        </div>
        {stats.length > 0 && <div className="esp-player-stats">{stats.join(" · ")}</div>}
      </div>
    </li>
  );
}

function RosterList({ players }: { players: EsportsPlayer[] }) {
  if (players.length === 0) {
    return (
      <div className="esp-state esp-state--empty esp-state--inline" role="status">
        <Users size={20} aria-hidden="true" />
        <h3>No player roster reported by this source.</h3>
      </div>
    );
  }
  return (
    <ul className="esp-player-list">
      {players.map((player) => (
        <PlayerRow key={player.id} player={player} />
      ))}
    </ul>
  );
}

export function TeamSection({ match }: { match: EsportsMatch }) {
  return (
    <section className="esp-teams" aria-label="Teams">
      <div className="esp-section-head">
        <h3>Teams</h3>
      </div>
      <div className="esp-teams-grid">
        <TeamBlock team={match.team_a} score={match.score_a} tournamentName={match.tournament_name} />
        <TeamBlock team={match.team_b} score={match.score_b} tournamentName={match.tournament_name} />
      </div>
    </section>
  );
}

export function PlayerSection({
  teamA,
  teamB,
  nameA,
  nameB,
}: {
  teamA: EsportsPlayer[];
  teamB: EsportsPlayer[];
  nameA: string | null;
  nameB: string | null;
}) {
  return (
    <section className="esp-players" aria-label="Players">
      <div className="esp-section-head">
        <h3>Players</h3>
      </div>
      <div className="esp-players-grid">
        <div className="esp-roster">
          <h4 className="esp-roster-title">{nameA || "Team A"}</h4>
          <RosterList players={teamA} />
        </div>
        <div className="esp-roster">
          <h4 className="esp-roster-title">{nameB || "Team B"}</h4>
          <RosterList players={teamB} />
        </div>
      </div>
    </section>
  );
}
