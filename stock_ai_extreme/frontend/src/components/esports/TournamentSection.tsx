/**
 * Phase 21B §14 — tournament section.
 *
 * Displays the tournament name, status, dates, region and current stage plus a
 * link into `/esports/tournament/:id`. Related matches are rendered by the
 * tournament page itself; this section is the summary used on the match page.
 */
import { ArrowRight, Trophy } from "lucide-react";
import { Link } from "react-router-dom";

import { formatDay, gameLabel, NA, type TournamentDetail } from "../../lib/esports";

export default function TournamentSection({
  tournament,
  fallbackName,
  tournamentId,
}: {
  tournament: TournamentDetail | null | undefined;
  fallbackName: string | null;
  tournamentId: string;
}) {
  const name = tournament?.name || fallbackName || NA;
  return (
    <section className="esp-tournament" aria-label="Tournament">
      <div className="esp-section-head">
        <h3>
          <Trophy size={13} aria-hidden="true" /> Tournament
        </h3>
      </div>
      <div className="esp-tournament-body">
        <h4>{name}</h4>
        <dl className="esp-tournament-facts">
          <div>
            <dt>Game</dt>
            <dd>{tournament ? gameLabel(tournament.game_id) : NA}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{tournament?.status || NA}</dd>
          </div>
          <div>
            <dt>Starts</dt>
            <dd>{formatDay(tournament?.start_date)}</dd>
          </div>
          <div>
            <dt>Ends</dt>
            <dd>{formatDay(tournament?.end_date)}</dd>
          </div>
          <div>
            <dt>Region</dt>
            <dd>{tournament?.region || NA}</dd>
          </div>
          <div>
            <dt>Stage</dt>
            <dd>
              {tournament && typeof tournament.metadata?.block === "string"
                ? (tournament.metadata.block as string)
                : NA}
            </dd>
          </div>
          <div>
            <dt>Prize pool</dt>
            <dd>
              {typeof tournament?.prize_pool === "number"
                ? `$${Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(tournament.prize_pool)}`
                : NA}
            </dd>
          </div>
          <div>
            <dt>Matches</dt>
            <dd>{tournament ? tournament.match_count : NA}</dd>
          </div>
        </dl>
        <Link className="esp-btn" to={`/esports/tournament/${encodeURIComponent(tournamentId)}`}>
          View tournament <ArrowRight size={13} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
