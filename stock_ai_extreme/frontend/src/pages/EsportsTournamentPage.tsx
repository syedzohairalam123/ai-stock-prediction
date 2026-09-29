/**
 * Phase 21B §14/§25 — tournament page (`/esports/tournament/:id`).
 *
 * Shows the tournament's name, status, dates, region and current stage together
 * with the real matches the provider associates with it, and deep-links back
 * into each match. Refresh restores the tournament from the URL (§25).
 */
import "../styles/esports.css";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, RefreshCw, Trophy } from "lucide-react";

import DataSourcePanel from "../components/esports/DataSourcePanel";
import LiveMatchGrid from "../components/esports/LiveMatchGrid";
import { useEsportsSources, useTournamentDetail } from "../hooks/useEsportsQueries";
import { formatDay, gameLabel, NA } from "../lib/esports";

export default function EsportsTournamentPage() {
  const { id } = useParams<{ id: string }>();
  const tournamentId = id ?? "";
  const query = useTournamentDetail(tournamentId || undefined);
  const sourcesQuery = useEsportsSources();
  const tournament = query.data;
  const errorMessage = query.isError ? (query.error as Error).message : null;

  if (query.isError) {
    return (
      <main className="esp-page">
        <div className="esp-state esp-state--error" role="alert">
          <AlertTriangle size={30} aria-hidden="true" />
          <h1>Tournament not found</h1>
          <p>{(query.error as Error).message}</p>
          <div className="esp-state-actions">
            <button type="button" className="esp-btn" onClick={() => query.refetch()}>
              <RefreshCw size={14} aria-hidden="true" /> Retry
            </button>
            <Link className="esp-btn" to="/esports">
              <ArrowLeft size={14} aria-hidden="true" /> Back to hub
            </Link>
          </div>
        </div>
      </main>
    );
  }

  if (query.isPending || !tournament) {
    return (
      <main className="esp-page">
        <div className="esp-match-header">
          <div className="esp-skeleton esp-skeleton--line" style={{ width: 260 }} />
        </div>
        <div className="esp-skeleton esp-skeleton--bar" />
      </main>
    );
  }

  return (
    <main className="esp-page esp-tournament-page">
      <header className="esp-match-header">
        <Link className="esp-back" to="/esports">
          <ArrowLeft size={14} aria-hidden="true" /> Esports hub
        </Link>
        <div className="esp-match-header-main">
          <div>
            <p className="esp-eyebrow">{gameLabel(tournament.game_id)} · Tournament</p>
            <h1>
              <Trophy size={22} aria-hidden="true" /> {tournament.name}
            </h1>
          </div>
        </div>
      </header>

      <div className="esp-panel">
        <dl className="esp-tournament-facts">
          <div>
            <dt>Status</dt>
            <dd>{tournament.status || NA}</dd>
          </div>
          <div>
            <dt>Starts</dt>
            <dd>{formatDay(tournament.start_date)}</dd>
          </div>
          <div>
            <dt>Ends</dt>
            <dd>{formatDay(tournament.end_date)}</dd>
          </div>
          <div>
            <dt>Region</dt>
            <dd>{tournament.region || NA}</dd>
          </div>
          <div>
            <dt>Stage</dt>
            <dd>
              {typeof tournament.metadata?.block === "string" ? (tournament.metadata.block as string) : NA}
            </dd>
          </div>
          <div>
            <dt>Prize pool</dt>
            <dd>
              {typeof tournament.prize_pool === "number"
                ? `$${Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(tournament.prize_pool)}`
                : NA}
            </dd>
          </div>
          <div>
            <dt>Matches</dt>
            <dd>{tournament.match_count}</dd>
          </div>
        </dl>
      </div>

      <section className="esp-results" aria-label="Related matches">
        <div className="esp-section-head">
          <h2>Related matches</h2>
          <span className="esp-muted">{tournament.match_count} total</span>
        </div>
        <LiveMatchGrid
          matches={tournament.matches}
          loading={query.isFetching && tournament.matches.length === 0}
          error={errorMessage}
          onRetry={() => query.refetch()}
          emptyTitle="No matches returned for this tournament."
        />
      </section>

      <DataSourcePanel sources={sourcesQuery.data?.providers} />
    </main>
  );
}
