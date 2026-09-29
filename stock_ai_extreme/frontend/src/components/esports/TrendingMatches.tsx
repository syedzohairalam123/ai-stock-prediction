/**
 * Phase 21C §9 — Trending Matches section.
 *
 * The backend ranks these by measured activity (live state, events it actually
 * ingested, observed starts, recency) and discloses the method. The component
 * renders that ranking and the per-match component breakdown — no client-side
 * re-ranking, no invented heat.
 */
import { memo } from "react";
import { Flame } from "lucide-react";
import { Link } from "react-router-dom";

import { useTrendingMatches } from "../../hooks/useEsportsAnalytics";
import MatchStatusBadge from "./MatchStatusBadge";
import { TeamLogo } from "./EsportsImage";
import { gameLabel, NA, relTime } from "../../lib/esports";
import type { TrendingMatchRow } from "../../lib/esportsAnalytics";

const Row = memo(function TrendingMatchCard({ row }: { row: TrendingMatchRow }) {
  const m = row.match;
  const total = row.components.events_observed;
  return (
    <li className="esp-tmatch-row">
      <Link to={`/esports/match/${encodeURIComponent(m.id)}`} className="esp-tmatch-link">
        <div className="esp-tmatch-teams">
          <span className="esp-tmatch-team">
            <TeamLogo src={m.team_a.logo_url} name={m.team_a.name} size={16} />
            {m.team_a.name || NA}
          </span>
          <span className="esp-tmatch-score">
            {m.score_a} : {m.score_b}
          </span>
          <span className="esp-tmatch-team">
            <TeamLogo src={m.team_b.logo_url} name={m.team_b.name} size={16} />
            {m.team_b.name || NA}
          </span>
        </div>
        <div className="esp-tmatch-meta esp-muted">
          {gameLabel(m.game_id)} · {m.tournament_name || NA} · updated {relTime(m.last_updated)}
        </div>
        <div className="esp-tmatch-foot">
          <MatchStatusBadge status={m.status} size="sm" />
          <span className="esp-muted" title="Events this app actually ingested for this match">
            {total} events observed
          </span>
          <span className="esp-tmatch-points" title={`Trending score ${row.score.toFixed(3)} (live ${row.components.live_state}, recency ${row.components.recency})`}>
            {Math.round(row.score * 100)} pts
          </span>
        </div>
      </Link>
    </li>
  );
});

export default function TrendingMatches({ gameId }: { gameId?: string | null }) {
  const query = useTrendingMatches(gameId ?? null, 6);
  const rows = query.data?.matches ?? [];

  return (
    <section aria-label="Trending matches">
      <div className="esp-section-head">
        <h2>
          <Flame size={16} aria-hidden="true" /> Trending matches
        </h2>
        <span className="esp-muted">{query.data?.selection.method ? "ranked by measured activity" : ""}</span>
      </div>

      {query.isPending && <p className="esp-muted esp-panel">Loading trending matches…</p>}
      {query.isError && (
        <div className="esp-panel esp-error-text" role="alert">
          Trending matches unavailable.
          <button type="button" className="esp-btn esp-btn--sm" onClick={() => query.refetch()}>
            Retry
          </button>
        </div>
      )}
      {!query.isPending && !query.isError && rows.length === 0 && (
        <p className="esp-muted esp-panel">No trending matches measured yet — activity appears as events are ingested.</p>
      )}
      {rows.length > 0 && (
        <ul className="esp-tmatch-list">
          {rows.map((row) => (
            <Row key={row.match_id} row={row} />
          ))}
        </ul>
      )}
      {query.data && (
        <p className="esp-trend-footnote esp-muted">
          Method: {query.data.selection.method}. Weights:{" "}
          {Object.entries(query.data.selection.weights)
            .map(([key, weight]) => `${key.replace(/_/g, " ")} ${weight}`)
            .join(", ")}
          .
        </p>
      )}
    </section>
  );
}
