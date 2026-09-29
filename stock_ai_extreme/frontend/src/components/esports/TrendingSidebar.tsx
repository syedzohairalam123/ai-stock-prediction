/**
 * Phase 21C §8 — TRENDING NOW sidebar.
 *
 * Shows exactly what the backend's TrendingGameEngine measured: live matches,
 * the activity metric with its unit and source, and last update. A signal the
 * backend could not measure appears in the disclosure line ("missing: viewer")
 * instead of being invented. Score confidence is rendered as text + badge, so
 * colour is never the only carrier.
 */
import { memo } from "react";
import { Flame, TrendingUp } from "lucide-react";

import { useTrendingGames } from "../../hooks/useEsportsAnalytics";
import { formatDateTime, gameLabel, NA, relTime } from "../../lib/esports";
import type { TrendingGame } from "../../lib/esportsAnalytics";

function formatMetric(game: TrendingGame): string {
  const metric = game.activity_metric;
  if (metric.value === null || metric.value === undefined) return NA;
  const value = new Intl.NumberFormat().format(metric.value);
  return `${value} ${metric.label}`;
}

const TrendingRow = memo(function TrendingRow({ game, rank }: { game: TrendingGame; rank: number }) {
  const missing = game.missing_signals.filter((key) => key !== "viewer");
  return (
    <li className="esp-trend-row">
      <span className="esp-trend-rank" aria-hidden="true">{rank}</span>
      <div className="esp-trend-main">
        <div className="esp-trend-name">
          <span>{gameLabel(game.game_id)}</span>
          <span className={`esp-mode esp-mode--${game.confidence.toLowerCase()}`} title={`Trend confidence: ${game.confidence}`}>
            {game.confidence}
          </span>
        </div>
        <div className="esp-trend-metric">
          {formatMetric(game)}
          {game.signals.live !== null && (
            <span className="esp-trend-live" title="Live matches tracked by this app">
              {" "}· {game.signals.live} live
            </span>
          )}
        </div>
        <div className="esp-trend-updated esp-muted">
          Updated {relTime(game.last_updated)}
          {missing.length > 0 && ` · missing signals: ${missing.join(", ")}`}
        </div>
      </div>
      <div className="esp-trend-score" aria-label={`Trending score ${game.score_0_100 ?? "unavailable"} of 100`}>
        {game.score_0_100 !== null ? Math.round(game.score_0_100) : NA}
      </div>
    </li>
  );
});

export default function TrendingSidebar() {
  const query = useTrendingGames();
  const games = query.data?.games ?? [];

  return (
    <section className="esp-aside-note esp-trending" aria-label="Trending now">
      <h3>
        <Flame size={13} aria-hidden="true" /> Trending now
      </h3>
      {query.isPending && <p className="esp-muted">Measuring activity…</p>}
      {query.isError && (
        <p className="esp-error-text" role="alert">
          Trending data unavailable.
          <button type="button" className="esp-btn esp-btn--sm" onClick={() => query.refetch()}>
            Retry
          </button>
        </p>
      )}
      {!query.isPending && !query.isError && games.length === 0 && (
        <p className="esp-muted">No activity measured in this window yet.</p>
      )}
      {games.length > 0 && (
        <>
          <ol className="esp-trend-list">
            {games.map((game, index) => (
              <TrendingRow key={game.game_id} game={game} rank={index + 1} />
            ))}
          </ol>
          <p className="esp-trend-footnote esp-muted">
            <TrendingUp size={11} aria-hidden="true" /> Score = weighted real signals (weights on the server).
            Signals with no source are disclosed, never estimated.
          </p>
        </>
      )}
      {query.dataUpdatedAt > 0 && (
        <p className="esp-trend-generated esp-muted" title={formatDateTime(new Date(query.dataUpdatedAt).toISOString())}>
          Generated {relTime(new Date(query.dataUpdatedAt).toISOString())}
        </p>
      )}
    </section>
  );
}
