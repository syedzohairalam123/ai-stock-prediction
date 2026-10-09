/**
 * Phase 23A — Freshness Badge Component (spec §18)
 *
 * Renders the data-freshness status a real source reported — LIVE, RECENT,
 * DELAYED, HISTORICAL, STALE or UNAVAILABLE — exactly as the backend computed
 * it. It never upgrades a label: a historical macro reading stays HISTORICAL,
 * it is not shown as LIVE just because the page was just opened. When the
 * release date is only an estimate (keyless FRED CSV), that caveat is shown
 * next to the label rather than hidden.
 */
import React from 'react';
import BaseBadge from '../BaseBadge';

export type DataFreshness =
  | 'LIVE'
  | 'RECENT'
  | 'DELAYED'
  | 'HISTORICAL'
  | 'STALE'
  | 'UNAVAILABLE';

interface FreshnessBadgeProps {
  freshness: string | null | undefined;
  /** True when the source cannot publish an exact release timestamp. */
  estimated?: boolean;
  className?: string;
}

const freshnessClass = (freshness: string): string => {
  switch (freshness) {
    case 'LIVE':
      return 'bg-green-100 text-green-800';
    case 'RECENT':
      return 'bg-blue-100 text-blue-800';
    case 'DELAYED':
      return 'bg-yellow-100 text-yellow-800';
    case 'HISTORICAL':
      return 'bg-gray-100 text-gray-800';
    case 'STALE':
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-gray-100 text-gray-800';
  }
};

const freshnessTitle = (freshness: string, estimated: boolean): string => {
  const base: Record<string, string> = {
    LIVE: 'Published within the last few hours.',
    RECENT: 'Published recently.',
    DELAYED: 'Published some time ago.',
    HISTORICAL: 'A historical published value, not a live reading.',
    STALE: 'Old enough that it should be refreshed from the source.',
    UNAVAILABLE: 'No release timestamp is available for this value.',
  };
  const note = base[freshness] ?? 'Data freshness as reported by the source.';
  return estimated
    ? `${note} Release date is estimated: this source does not publish an exact release timestamp.`
    : note;
};

export const FreshnessBadge: React.FC<FreshnessBadgeProps> = ({
  freshness,
  estimated = false,
  className = '',
}) => {
  const label = (freshness || 'UNAVAILABLE').toUpperCase();
  return (
    <span className="inline-block" title={freshnessTitle(label, estimated)}>
      <BaseBadge
        variant="outline"
        size="sm"
        className={`${freshnessClass(label)} ${className}`}
      >
        {label}
        {estimated ? ' (est.)' : ''}
      </BaseBadge>
    </span>
  );
};

export default FreshnessBadge;
