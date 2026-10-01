/**
 * Phase 22C — shared state primitives for crypto widgets (spec §23/§24/§25).
 *
 * Error isolation: every widget renders its own error inside its own card, so a
 * failing forecast service can never blank the price, chart or volatility.
 * Loading shows a skeleton with NO fabricated numbers. Empty states say exactly
 * what is unavailable and why.
 */
import type { ReactNode } from "react";

/** A skeleton placeholder — deliberately has no values in it (spec §24). */
export function CryptoSkeleton({ height = 120, label }: { height?: number; label?: string }) {
  return (
    <div className="crypto-skeleton" style={{ height }} role="status" aria-live="polite">
      <span className="sr-only">{label ?? "Loading…"}</span>
    </div>
  );
}

/** Honest empty state: NO DATA AVAILABLE + a real explanation (spec §25). */
export function CryptoEmpty({
  title = "NO DATA AVAILABLE",
  reason,
  hint,
}: {
  title?: string;
  reason: string;
  hint?: string;
}) {
  return (
    <div className="crypto-empty" role="status">
      <strong>{title}</strong>
      <span>{reason}</span>
      {hint && <span className="dim">{hint}</span>}
    </div>
  );
}

/**
 * Isolated failure for one widget. The rest of the page keeps working; only
 * this card reports the failure and offers a retry.
 */
export function CryptoWidgetError({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="crypto-widget-error" role="alert">
      <strong>{title}</strong>
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="crypto-probe-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

/** Consistent card chrome: title + optional freshness/source chip on the right. */
export function CryptoPanel({
  title,
  badge,
  children,
  className,
}: {
  title: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel crypto-panel ${className ?? ""}`}>
      <div className="crypto-panel-head">
        <h2>{title}</h2>
        {badge}
      </div>
      {children}
    </section>
  );
}

/** Small key/value stat used across cards. */
export function CryptoStat({
  label,
  value,
  sub,
  tone,
  title,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "pos" | "neg" | "mut" | "warn";
  title?: string;
}) {
  return (
    <div className={`crypto-stat${tone === "warn" ? " warn" : ""}`} title={title}>
      <span className="crypto-stat-k">{label}</span>
      <span className={`crypto-stat-v ${tone && tone !== "warn" ? tone : ""}`}>{value}</span>
      {sub && <span className="crypto-stat-s">{sub}</span>}
    </div>
  );
}
