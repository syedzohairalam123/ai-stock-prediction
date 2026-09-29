/**
 * Phase 21B §11–§17 — the live match page (`/esports/match/:id`).
 *
 * Layout: header → scoreboard → map/game state → timeline → teams → players →
 * statistics → source/status. A single WebSocket subscription feeds the store;
 * the scoreboard reads only its own snapshot slice and the timeline only its
 * own events slice, so an incoming event never re-renders the whole page (§10).
 */
import "../styles/esports.css";
import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";

import ActivityTicker from "../components/esports/ActivityTicker";
import ConnectionStatus from "../components/esports/ConnectionStatus";
import DataSourcePanel from "../components/esports/DataSourcePanel";
import MatchTimeline from "../components/esports/MatchTimeline";
import Scoreboard from "../components/esports/Scoreboard";
import TournamentSection from "../components/esports/TournamentSection";
import { PlayerSection, TeamSection } from "../components/esports/RosterSections";
import { ScoreboardSkeleton } from "../components/esports/EsportsSkeletons";
// Phase 21C: analytics panels (team form, anomalies, data quality).
import { MatchAnalyticsPanel, TeamAnalyticsPanel } from "../components/esports/AnalyticsPanels";
import { useEsportsSocket } from "../hooks/useEsportsSocket";
import { useMatchDetail, useTournamentDetail } from "../hooks/useEsportsQueries";
import { describeMatch, gameLabel, NA, type EsportsEvent } from "../lib/esports";
import { selectMatchEvents, selectSnapshot, useEsportsStore } from "../store/useEsportsStore";

export default function EsportsMatchPage() {
  const { id } = useParams<{ id: string }>();
  const matchId = id ?? "";
  const seeded = useRef<Set<string>>(new Set());

  useEsportsSocket({ matchId, enabled: Boolean(matchId) });

  const detailQuery = useMatchDetail(matchId || undefined);
  const detail = detailQuery.data;
  const tournamentQuery = useTournamentDetail(detail?.tournament_id);
  const seedMatchEvents = useEsportsStore((s) => s.seedMatchEvents);

  const snapshot = useEsportsStore(selectSnapshot(matchId));
  const liveEvents = useEsportsStore(selectMatchEvents(matchId));

  // Seed the store timeline with the historical events once per match; live
  // events append to the same bounded buffer.
  useEffect(() => {
    if (!detail || !matchId || seeded.current.has(matchId)) return;
    seeded.current.add(matchId);
    seedMatchEvents(matchId, detail.events);
  }, [detail, matchId, seedMatchEvents]);

  const timelineEvents: EsportsEvent[] = useMemo(() => {
    if (liveEvents.length > 0) return liveEvents;
    return detail?.events ?? [];
  }, [liveEvents, detail]);

  if (detailQuery.isError) {
    return (
      <main className="esp-page">
        <div className="esp-state esp-state--error" role="alert">
          <AlertTriangle size={30} aria-hidden="true" />
          <h1>Match not found</h1>
          <p>{(detailQuery.error as Error).message}</p>
          <div className="esp-state-actions">
            <button type="button" className="esp-btn" onClick={() => detailQuery.refetch()}>
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

  if (detailQuery.isPending || !detail) {
    return (
      <main className="esp-page">
        <div className="esp-match-header">
          <div className="esp-skeleton esp-skeleton--line" style={{ width: 220 }} />
        </div>
        <ScoreboardSkeleton />
      </main>
    );
  }

  const activeSnapshot = snapshot ?? detail.snapshot;

  return (
    <main className="esp-page esp-match-page">
      <header className="esp-match-header">
        <Link className="esp-back" to="/esports">
          <ArrowLeft size={14} aria-hidden="true" /> Esports hub
        </Link>
        <div className="esp-match-header-main">
          <div>
            <p className="esp-eyebrow">{gameLabel(detail.game_id)}</p>
            <h1>
              {detail.team_a.name || NA} <span className="esp-vs">vs</span> {detail.team_b.name || NA}
            </h1>
            <p className="esp-muted">{detail.tournament_name || NA}</p>
          </div>
          <ConnectionStatus />
        </div>
      </header>

      <ActivityTicker />

      <div className="esp-match-layout">
        <div className="esp-match-main">
          <div aria-live="polite">
            <Scoreboard match={detail} snapshot={activeSnapshot} />
          </div>

          {/* Map / game state (§11) */}
          <section className="esp-mapstate" aria-label="Map and game state">
            <div className="esp-section-head">
              <h3>Map &amp; game state</h3>
            </div>
            <dl className="esp-mapstate-grid">
              <div>
                <dt>Current map</dt>
                <dd>{detail.current_map || NA}</dd>
              </div>
              <div>
                <dt>Map number</dt>
                <dd>{detail.map_number > 0 ? detail.map_number : NA}</dd>
              </div>
              <div>
                <dt>Best of</dt>
                <dd>{detail.best_of > 1 ? detail.best_of : NA}</dd>
              </div>
              <div>
                <dt>Series score</dt>
                <dd>
                  {detail.score_a} – {detail.score_b}
                </dd>
              </div>
            </dl>
          </section>

          <MatchTimeline events={timelineEvents} loading={detailQuery.isFetching && timelineEvents.length === 0} />

          <TeamSection match={detail} />

          <PlayerSection
            teamA={detail.players.team_a}
            teamB={detail.players.team_b}
            nameA={detail.team_a.name}
            nameB={detail.team_b.name}
          />

          {/* Phase 21C §1–§4/§10: descriptive analytics + labelled anomalies. */}
          <div className="esp-an-grid">
            <TeamAnalyticsPanel teamId={detail.team_a.id} gameId={detail.game_id} />
            <TeamAnalyticsPanel teamId={detail.team_b.id} gameId={detail.game_id} />
          </div>
          <MatchAnalyticsPanel matchId={matchId} />

          {/* Statistics (§11) */}
          <section className="esp-stats" aria-label="Match statistics">
            <div className="esp-section-head">
              <h3>Statistics</h3>
            </div>
            <dl className="esp-stats-grid">
              <div>
                <dt>Events reported</dt>
                <dd>{detail.event_count}</dd>
              </div>
              <div>
                <dt>Games in series</dt>
                <dd>{detail.games.length || NA}</dd>
              </div>
              <div>
                <dt>Started</dt>
                <dd>{detail.started_at ? new Date(detail.started_at).toLocaleString() : NA}</dd>
              </div>
              <div>
                <dt>Scheduled</dt>
                <dd>{detail.scheduled_at ? new Date(detail.scheduled_at).toLocaleString() : NA}</dd>
              </div>
            </dl>
            <p className="esp-a11y-note" aria-label="Accessible match description">
              {describeMatch(detail)}
            </p>
          </section>
        </div>

        <aside className="esp-match-aside" aria-label="Match context">
          <TournamentSection
            tournament={tournamentQuery.data ?? null}
            fallbackName={detail.tournament_name}
            tournamentId={detail.tournament_id}
          />
          <DataSourcePanel match={detail} sources={detail.data_sources} />
        </aside>
      </div>
    </main>
  );
}
