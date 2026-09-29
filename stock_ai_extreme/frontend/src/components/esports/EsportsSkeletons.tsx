/**
 * Phase 21B §21 — loading skeletons.
 *
 * Structure-only placeholders: they reserve the exact layout the real content
 * will occupy but render no numbers, scores or names, so a loading state can
 * never be mistaken for real (or fake) data.
 */

export function HeroSkeleton() {
  return (
    <div className="esp-hero esp-hero--skeleton" aria-hidden="true">
      <div className="esp-hero-top">
        <div className="esp-skeleton esp-skeleton--pill" />
        <div className="esp-skeleton esp-skeleton--pill esp-skeleton--sm" />
      </div>
      <div className="esp-hero-teams">
        <div className="esp-hero-team">
          <div className="esp-skeleton esp-skeleton--logo" />
          <div className="esp-skeleton esp-skeleton--line" />
        </div>
        <div className="esp-hero-score">
          <div className="esp-skeleton esp-skeleton--score" />
        </div>
        <div className="esp-hero-team">
          <div className="esp-skeleton esp-skeleton--logo" />
          <div className="esp-skeleton esp-skeleton--line" />
        </div>
      </div>
      <div className="esp-skeleton esp-skeleton--bar" />
    </div>
  );
}

export function MatchCardSkeleton() {
  return (
    <div className="esp-match-card esp-match-card--skeleton" aria-hidden="true">
      <div className="esp-match-head">
        <div className="esp-skeleton esp-skeleton--pill esp-skeleton--sm" />
        <div className="esp-skeleton esp-skeleton--pill esp-skeleton--sm" />
      </div>
      <div className="esp-match-rows">
        <div className="esp-skeleton esp-skeleton--row" />
        <div className="esp-skeleton esp-skeleton--row" />
      </div>
      <div className="esp-skeleton esp-skeleton--bar" />
    </div>
  );
}

export function MatchGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="esp-grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <MatchCardSkeleton key={index} />
      ))}
    </div>
  );
}

export function ScoreboardSkeleton() {
  return (
    <div className="esp-scoreboard esp-scoreboard--skeleton" aria-hidden="true">
      <div className="esp-skeleton esp-skeleton--bar" />
      <div className="esp-scoreboard-body">
        <div className="esp-skeleton esp-skeleton--score" />
        <div className="esp-skeleton esp-skeleton--score" />
      </div>
    </div>
  );
}

export function TimelineSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="esp-timeline esp-timeline--skeleton" aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div className="esp-timeline-row" key={index}>
          <div className="esp-skeleton esp-skeleton--dot" />
          <div className="esp-timeline-body">
            <div className="esp-skeleton esp-skeleton--line" />
            <div className="esp-skeleton esp-skeleton--line esp-skeleton--short" />
          </div>
        </div>
      ))}
    </div>
  );
}
