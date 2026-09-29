/**
 * Phase 21B §5 — game category cards.
 *
 * Every number is a literal count of the matches the provider actually
 * returned (live / upcoming / recent / tournaments) plus the activity metric
 * the backend supplied with its unit. No volume figure is invented.
 */
import { Crosshair, Gamepad2, Shield, Swords } from "lucide-react";
import { Link } from "react-router-dom";

import { dataModeTone, gameLabel, relTime, type GameSummary } from "../../lib/esports";

const GAME_ICONS: Record<string, typeof Gamepad2> = {
  cs2: Crosshair,
  lol: Swords,
  dota2: Shield,
};

export default function GameCategoryCard({
  summary,
  active = false,
}: {
  summary: GameSummary;
  active?: boolean;
}) {
  const Icon = GAME_ICONS[summary.game_id] ?? Gamepad2;
  return (
    <Link
      to={`/esports/${summary.game_id}`}
      className={`esp-game-card${active ? " active" : ""}`}
      aria-label={`Open ${gameLabel(summary.game_id)} hub`}
    >
      <div className="esp-game-card-head">
        <span className="esp-game-icon" aria-hidden="true">
          <Icon size={20} />
        </span>
        <div className="esp-game-titles">
          <h3>{gameLabel(summary.game_id)}</h3>
          <p className="esp-muted">{summary.source}</p>
        </div>
        <span className={`esp-mode esp-mode--${dataModeTone(summary.data_mode)}`}>{summary.data_mode}</span>
      </div>

      <dl className="esp-game-counts">
        <div>
          <dt>Live</dt>
          <dd>{summary.counts.live}</dd>
        </div>
        <div>
          <dt>Upcoming</dt>
          <dd>{summary.counts.upcoming}</dd>
        </div>
        <div>
          <dt>Recent</dt>
          <dd>{summary.counts.recent}</dd>
        </div>
        <div>
          <dt>Tournaments</dt>
          <dd>{summary.counts.tournaments}</dd>
        </div>
      </dl>

      <div className="esp-game-foot">
        <span title={`${summary.activity.value} ${summary.activity.label}`}>
          {summary.activity.value} {summary.activity.label}
        </span>
        <span className="esp-muted">Updated {relTime(summary.last_updated)}</span>
      </div>
    </Link>
  );
}
