/**
 * Phase 19 §8 — one discovery card.
 *
 * Shows exactly what the contract promises: name, category, tags, the real
 * activity metric (or N/A), the trend/popularity score with an expandable
 * breakdown of its components and weights, a sparkline of stored
 * observations, the honest "updated" time, and source + data mode.
 *
 * Nothing on this card is decorative data: every number traces back to a
 * named source, and every unavailable one says N/A.
 */
import { memo } from "react";
import { Link } from "react-router-dom";
import BaseBadge from "../BaseBadge";
import TrendSparkline from "./TrendSparkline";
import {
  ENTITY_LABELS,
  NA,
  SIGNAL_LABELS,
  dataModeLabel,
  formatActivity,
  formatScore,
  relTime,
  type ActivityMetric,
  type DiscoverableEntity,
  type DiscoveryMode,
  type ScoreBlock,
} from "../../lib/discovery";

interface DiscoveryCardProps {
  entity: DiscoverableEntity;
  mode: DiscoveryMode;
  onTagClick: (tag: string) => void;
  onCategoryClick: (category: string) => void;
  onOpen: (entity: DiscoverableEntity) => void;
}

const MAX_VISIBLE_TAGS = 4;

function scoreForMode(entity: DiscoverableEntity, mode: DiscoveryMode): ScoreBlock {
  return mode === "popular" ? entity.popularity : entity.trend;
}

function scoreLabel(mode: DiscoveryMode): string {
  return mode === "popular" ? "Popularity" : "Trend score";
}

function ActivityValue({ activity }: { activity: ActivityMetric | null }) {
  const text = formatActivity(activity);
  if (text === NA) {
    return (
      <span className="disc-activity na" title={activity?.note ?? "No source publishes an activity metric for this entity."}>
        <span className="disc-activity-label">{activity?.label ?? "Activity"}</span>
        <strong>{NA}</strong>
      </span>
    );
  }
  const raw = activity?.value ?? 0;
  return (
    <span
      className={`disc-activity ${raw > 0 ? "pos" : raw < 0 ? "neg" : ""}`}
      title={activity?.note ?? undefined}
    >
      <span className="disc-activity-label">{activity?.label}</span>
      <strong>{text}</strong>
    </span>
  );
}

function DiscoveryCardComponent({ entity, mode, onTagClick, onCategoryClick, onOpen }: DiscoveryCardProps) {
  const score = scoreForMode(entity, mode);
  const components = score.components ?? {};
  const missing = new Set(score.missing ?? []);
  const visibleTags = entity.tags.slice(0, MAX_VISIBLE_TAGS);
  const extraTags = entity.tags.length - visibleTags.length;

  const title = (
    <h3 className="disc-card-title">
      {entity.route ? (
        <Link to={entity.route} onClick={() => onOpen(entity)}>
          {entity.name}
        </Link>
      ) : (
        <span>{entity.name}</span>
      )}
      {entity.symbol && <span className="disc-card-symbol">{entity.symbol}</span>}
    </h3>
  );

  return (
    <article className="disc-card" data-entity-type={entity.type}>
      <header className="disc-card-head">
        <div className="disc-card-badges">
          <BaseBadge variant="info" size="sm">
            {ENTITY_LABELS[entity.type] ?? entity.type}
          </BaseBadge>
          <span className={`disc-mode-chip ${entity.dataMode.toLowerCase()}`} title={`Data mode: ${entity.dataMode}`}>
            {dataModeLabel(entity.dataMode)}
          </span>
          {entity.status && entity.status !== "ACTIVE" && (
            <BaseBadge variant="warning" size="sm">
              {entity.status}
            </BaseBadge>
          )}
          {entity.personal?.watchlist && (
            <span title="In your watchlist">
              <BaseBadge variant="success" size="sm">
                ★ Watchlist
              </BaseBadge>
            </span>
          )}
          {entity.personal?.recentlyViewed && (
            <span title="You opened this recently">
              <BaseBadge variant="default" size="sm">
                ⟲ Recent
              </BaseBadge>
            </span>
          )}
          {entity.personalBoostApplied && (
            <span className="disc-boost-note" title="Ranking boosted by an explicit personal signal; the score shown is unboosted.">
              personalized rank
            </span>
          )}
        </div>
        <ActivityValue activity={entity.activity} />
      </header>

      {title}

      <div className="disc-card-taxonomy">
        <button
          type="button"
          className="disc-cat-chip"
          onClick={() => onCategoryClick(entity.category)}
          title={`Filter by category ${entity.category}`}
        >
          {entity.category}
        </button>
        {visibleTags.map((tag) => (
          <button
            key={tag}
            type="button"
            className="disc-tag-chip"
            onClick={() => onTagClick(tag)}
            title={`Filter everything tagged ${tag}`}
          >
            {tag}
          </button>
        ))}
        {extraTags > 0 && <span className="disc-tag-more">+{extraTags}</span>}
      </div>

      <div className="disc-card-score">
        <div className="disc-score-main">
          <span className="disc-score-label">{scoreLabel(mode)}</span>
          <span className={`disc-score-value ${score.score === null ? "na" : ""}`}>
            {formatScore(score.score)}
            {score.score !== null && <span className="disc-score-max">/100</span>}
          </span>
        </div>
        <TrendSparkline entityId={entity.id} />
      </div>

      <details className="disc-score-detail">
        <summary>How this score was computed</summary>
        <ul className="disc-component-list">
          {Object.entries(components).map(([name, value]) => (
            <li key={name} className={value === null ? "is-missing" : ""}>
              <span>{SIGNAL_LABELS[name] ?? name}</span>
              <span className="disc-component-value">
                {value === null ? NA : value.toFixed(3)}
                {value !== null && score.weightsUsed?.[name] !== undefined && (
                  <em> · weight {score.weightsUsed[name].toFixed(2)}</em>
                )}
              </span>
            </li>
          ))}
        </ul>
        {missing.size > 0 && (
          <p className="disc-missing-signals">
            Signals with no measurement (excluded, not zeroed):{" "}
            {[...missing].map((name) => SIGNAL_LABELS[name] ?? name).join(", ")}.
          </p>
        )}
        <p className="disc-interest-row">
          Recorded interest: {entity.interest.total} event(s) — {entity.interest.view} view(s),{" "}
          {entity.interest.search} search(es), {entity.interest.watchlist} watchlist save(s).
        </p>
        {score.score !== null && entity.rankScore !== null && entity.rankScore !== undefined && (
          <p className="disc-interest-row">Rank used for ordering: {entity.rankScore.toFixed(1)}.</p>
        )}
      </details>

      <footer className="disc-card-foot">
        <span title={entity.updatedAt ?? undefined}>Updated {relTime(entity.updatedAt)}</span>
        <span className="disc-card-source" title={`Source: ${entity.source}`}>
          {entity.source}
        </span>
      </footer>
    </article>
  );
}

/**
 * Memoized: a 60-second background refetch that returns identical data must
 * not re-render every card in the grid (spec §16 — feed rendering).
 */
const DiscoveryCard = memo(DiscoveryCardComponent);
export default DiscoveryCard;
