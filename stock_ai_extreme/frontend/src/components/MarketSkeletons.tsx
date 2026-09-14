export default function LoadingSkeletonCard() {
  return (
    <div className="index-card skeleton-card" aria-hidden>
      <div className="skeleton skeleton-title" style={{ width: 70, height: 16, marginBottom: 10 }} />
      <div className="skeleton" style={{ width: 90, height: 22, marginBottom: 8 }} />
      <div className="skeleton" style={{ width: 110, height: 14 }} />
    </div>
  );
}

/** Skeleton for one mover card — mirrors MoverCard's flex layout exactly. */
export function LoadingSkeletonMover() {
  return (
    <div className="mover-card skeleton-card" aria-hidden>
      <div className="skeleton" style={{ width: 26, height: 20, borderRadius: 6 }} />
      <div className="skeleton" style={{ width: 34, height: 34, borderRadius: "50%" }} />
      <div className="mover-card-main">
        <div className="skeleton" style={{ width: 64, height: 14 }} />
        <div className="skeleton" style={{ width: 92, height: 11 }} />
      </div>
      <div className="mover-card-quote">
        <div className="skeleton" style={{ width: 52, height: 14 }} />
        <div className="skeleton" style={{ width: 44, height: 11 }} />
      </div>
      <div className="mover-card-vol">
        <div className="skeleton" style={{ width: 22, height: 9 }} />
        <div className="skeleton" style={{ width: 34, height: 12 }} />
      </div>
    </div>
  );
}

/** Skeleton for a data table with the given column count. */
export function LoadingSkeletonTable({ rows = 6, cols = 9 }: { rows?: number; cols?: number }) {
  return (
    <div className="table-skeleton" aria-hidden>
      <div className="table-skeleton-head">
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 12, flex: 1 }} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="table-skeleton-row">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="skeleton" style={{ height: 14, flex: 1, opacity: 1 - r * 0.08 }} />
          ))}
        </div>
      ))}
    </div>
  );
}
