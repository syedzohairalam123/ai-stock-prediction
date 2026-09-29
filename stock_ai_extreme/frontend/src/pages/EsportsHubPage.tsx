/**
 * Phase 21B §1/§5/§6/§9/§18/§25 — the Esports Hub.
 *
 * Serves both `/esports` and `/esports/:game`. All live data comes from the
 * Phase 21A backend; the page opens one WebSocket (game channel or firehose)
 * whose events feed the activity ticker. Filters and the selected game live in
 * the URL, so refreshing restores the exact view without a page reload.
 */
import "../styles/esports.css";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Gamepad2, RefreshCw } from "lucide-react";

import ActivityTicker from "../components/esports/ActivityTicker";
import ConnectionStatus from "../components/esports/ConnectionStatus";
import DataSourcePanel from "../components/esports/DataSourcePanel";
import EsportsFilters, { type EsportsFiltersValue } from "../components/esports/EsportsFilters";
// Phase 21C: trending sidebar, trending matches and the data-quality panel.
import TrendingSidebar from "../components/esports/TrendingSidebar";
import TrendingMatches from "../components/esports/TrendingMatches";
import { DataQualityPanel } from "../components/esports/AnalyticsPanels";
import { EsportsAnalyticsService } from "../lib/esportsAnalytics";
import FeaturedMatchHero from "../components/esports/FeaturedMatchHero";
import GameCategoryCard from "../components/esports/GameCategoryCard";
import LiveMatchGrid from "../components/esports/LiveMatchGrid";
import { useEsportsSocket } from "../hooks/useEsportsSocket";
import {
  useEsportsSources,
  useFeaturedMatch,
  useGameTournaments,
  useGamesSummary,
  useMatchFeed,
} from "../hooks/useEsportsQueries";
import {
  GAME_LABELS,
  HUB_GAMES,
  type EsportsMatch,
  type MatchFeedParams,
  type MatchStatusValue,
} from "../lib/esports";

const PAGE_SIZE = 24;

export default function EsportsHubPage() {
  const { game: pathGame } = useParams<{ game?: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState(0);

  const game =
    pathGame && (HUB_GAMES as readonly string[]).includes(pathGame) ? pathGame : null;

  const filters: EsportsFiltersValue = useMemo(
    () => ({
      game,
      live: searchParams.get("live") === "1",
      upcoming: searchParams.get("upcoming") === "1",
      status: (searchParams.get("status") as MatchStatusValue | null) || null,
      tournamentId: searchParams.get("tournament"),
      dateFrom: searchParams.get("from"),
      dateTo: searchParams.get("to"),
      region: searchParams.get("region"),
      q: searchParams.get("q") ?? "",
    }),
    [game, searchParams]
  );

  // Any filter change resets paging to the first page.
  useEffect(() => {
    setPage(0);
  }, [searchParams, game]);

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(patch).forEach(([key, value]) => {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      });
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const onFiltersChange = useCallback(
    (patch: Partial<EsportsFiltersValue>) => {
      const { game: patchGame, ...rest } = patch;
      if (patchGame !== undefined) {
        navigate(patchGame ? `/esports/${patchGame}` : "/esports");
        return;
      }
      const mapped: Record<string, string | null> = {};
      if ("live" in rest) mapped.live = rest.live ? "1" : null;
      if ("upcoming" in rest) mapped.upcoming = rest.upcoming ? "1" : null;
      if ("status" in rest) mapped.status = rest.status ?? null;
      if ("tournamentId" in rest) mapped.tournament = rest.tournamentId ?? null;
      if ("dateFrom" in rest) mapped.from = rest.dateFrom ?? null;
      if ("dateTo" in rest) mapped.to = rest.dateTo ?? null;
      if ("region" in rest) mapped.region = rest.region ?? null;
      if ("q" in rest) mapped.q = rest.q || null;
      patchParams(mapped);
    },
    [navigate, patchParams]
  );

  const onClear = useCallback(() => {
    if (game) navigate("/esports");
    setSearchParams(new URLSearchParams(), { replace: true });
  }, [game, navigate, setSearchParams]);

  // One socket per page: game channel when a game is selected, else firehose.
  useEsportsSocket({ gameId: game, all: !game, enabled: true });

  // Phase 21C §6: record a real interest signal for the trending engine when a
  // hub view is opened. One POST per game selection, fired (and forgotten) —
  // the trending score only ever counts what users actually did.
  useEffect(() => {
    if (!game) return;
    EsportsAnalyticsService.recordInterest(game, "view").catch(() => {
      /* interest recording must never surface as a page error */
    });
  }, [game]);

  const summaryQuery = useGamesSummary();
  const featuredQuery = useFeaturedMatch(game);
  const tournamentsQuery = useGameTournaments(game ?? undefined);
  const sourcesQuery = useEsportsSources();

  const feedParams: MatchFeedParams = useMemo(
    () => ({
      game_id: game,
      statuses: filters.status ? [filters.status] : null,
      live: filters.live,
      upcoming: filters.upcoming,
      tournament_id: filters.tournamentId,
      region: filters.region,
      q: filters.q || null,
      date_from: filters.dateFrom ? `${filters.dateFrom}T00:00:00Z` : null,
      date_to: filters.dateTo ? `${filters.dateTo}T23:59:59Z` : null,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [game, filters, page]
  );

  const feedQuery = useMatchFeed(feedParams);
  const [visible, setVisible] = useState<EsportsMatch[]>([]);

  useEffect(() => {
    const feed = feedQuery.data;
    if (!feed) return;
    if (feed.offset === 0) {
      setVisible(feed.matches);
      return;
    }
    setVisible((previous) => {
      const known = new Set(previous.map((m) => m.id));
      return [...previous, ...feed.matches.filter((m) => !known.has(m.id))];
    });
  }, [feedQuery.data]);

  const refreshAll = useCallback(() => {
    summaryQuery.refetch();
    featuredQuery.refetch();
    feedQuery.refetch();
    sourcesQuery.refetch();
  }, [summaryQuery, featuredQuery, feedQuery, sourcesQuery]);

  const games = summaryQuery.data?.games ?? [];
  const tournaments = tournamentsQuery.data?.tournaments ?? [];

  return (
    <main className="esp-page">
      <header className="esp-page-head">
        <div>
          <p className="esp-eyebrow">Phase 21B · Real-time esports hub</p>
          <h1>
            <Gamepad2 size={22} aria-hidden="true" /> {game ? GAME_LABELS[game] : "Esports"}
          </h1>
          <p className="esp-page-sub">
            Live and scheduled professional matches from real, named data sources. Nothing here is simulated.
          </p>
        </div>
        <div className="esp-head-actions">
          <ConnectionStatus onReconnect={refreshAll} />
          <button type="button" className="esp-btn" onClick={refreshAll} disabled={feedQuery.isFetching}>
            <RefreshCw size={14} aria-hidden="true" className={feedQuery.isFetching ? "esp-spin" : ""} />
            Refresh
          </button>
        </div>
      </header>

      <ActivityTicker />

      <FeaturedMatchHero
        match={featuredQuery.data?.featured ?? null}
        loading={featuredQuery.isPending}
        error={featuredQuery.isError ? (featuredQuery.error as Error).message : null}
        onRetry={() => featuredQuery.refetch()}
      />

      <section className="esp-games" aria-label="Game categories">
        <div className="esp-section-head">
          <h2>Games</h2>
          <span className="esp-muted">{games.length} configured</span>
        </div>
        {summaryQuery.isPending ? (
          <div className="esp-games-grid" aria-hidden="true">
            {HUB_GAMES.map((id) => (
              <div key={id} className="esp-game-card skeleton-block" />
            ))}
          </div>
        ) : (
          <div className="esp-games-grid">
            {games.map((summary) => (
              <GameCategoryCard key={summary.game_id} summary={summary} active={summary.game_id === game} />
            ))}
          </div>
        )}
      </section>

      <div className="esp-layout">
        <section className="esp-results" aria-label="Matches">
          <div className="esp-section-head">
            <h2>{game ? "Matches" : "All matches"}</h2>
            {feedQuery.data && (
              <span className="esp-muted">
                {visible.length} of {feedQuery.data.total}
              </span>
            )}
          </div>

          <EsportsFilters
            value={filters}
            onChange={onFiltersChange}
            onClear={onClear}
            tournaments={tournaments}
          />

          <LiveMatchGrid
            matches={visible}
            loading={feedQuery.isPending || (feedQuery.isFetching && visible.length === 0)}
            error={feedQuery.isError ? (feedQuery.error as Error).message : null}
            onRetry={() => feedQuery.refetch()}
            showGame={!game}
            emptyTitle={
              filters.live
                ? "No live matches currently available."
                : filters.upcoming
                  ? "No upcoming matches returned by the provider."
                  : "No matches match these filters."
            }
          />

          {(feedQuery.data?.has_more ?? false) && (
            <div className="esp-pager">
              <button
                type="button"
                className="esp-btn"
                onClick={() => setPage((value) => value + 1)}
                disabled={feedQuery.isFetching}
              >
                Load more
              </button>
            </div>
          )}
        </section>

        <aside className="esp-aside" aria-label="Trending and data status">
          <TrendingSidebar />
          <DataSourcePanel sources={sourcesQuery.data?.providers} />
          <DataQualityPanel gameId={game} />
          <section className="esp-aside-note">
            <h3>About this hub</h3>
            <p className="esp-muted">
              Data comes from public esports providers. A match the provider marks finished is shown as
              completed, and a field a provider does not publish is shown as N/A — never guessed.
            </p>
          </section>
        </aside>
      </div>

      <TrendingMatches gameId={game} />
    </main>
  );
}
