/**
 * Phase 23A — Macro Indicator Card Component
 *
 * Displays one real macroeconomic indicator: latest value, unit, change,
 * observation vs release date, freshness and source attribution. When the
 * release date is estimated (keyless CSV source), it is labelled as such
 * rather than presented as exact.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { TrendingUp, TrendingDown, Minus, ExternalLink } from 'lucide-react';

export interface MacroIndicator {
  key: string;
  series_id: string;
  label: string;
  value: number | null;
  unit: string;
  frequency: string;
  observation_date: string;
  release_date: string;
  source: string;
  source_url?: string | null;
  data_freshness: string;
  previous_value?: number | null;
  change?: number | null;
  change_pct?: number | null;
  revision: number;
  release_date_estimated: boolean;
}

interface MacroIndicatorCardProps {
  indicator: MacroIndicator;
}

const freshnessColor = (freshness: string): string => {
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

const formatDate = (value: string): string => {
  if (!value) return 'N/A';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

export const MacroIndicatorCard: React.FC<MacroIndicatorCardProps> = ({ indicator }) => {
  const change = indicator.change;
  const hasChange = change != null && Number.isFinite(change);
  const ChangeIcon = !hasChange ? Minus : change > 0 ? TrendingUp : TrendingDown;
  const changeColor = !hasChange ? 'text-gray-500' : change > 0 ? 'text-green-600' : 'text-red-600';

  return (
    <BaseCard className="p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900 mb-1 text-sm">{indicator.label}</h3>
          <div className="flex items-center gap-2 flex-wrap">
            <BaseBadge variant="outline" size="sm" className={freshnessColor(indicator.data_freshness)}>
              {indicator.data_freshness}
            </BaseBadge>
            {indicator.frequency && (
              <BaseBadge variant="outline" size="sm">
                {indicator.frequency}
              </BaseBadge>
            )}
            <span className="text-xs text-gray-400">{indicator.series_id}</span>
          </div>
        </div>
        {indicator.source_url && (
          <a
            href={indicator.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title={`View ${indicator.source} source`}
          >
            <ExternalLink className="w-4 h-4 text-gray-600" />
          </a>
        )}
      </div>

      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-gray-900">
            {indicator.value != null
              ? indicator.value.toLocaleString(undefined, { maximumFractionDigits: 4 })
              : 'N/A'}
          </span>
          {indicator.unit && <span className="text-sm text-gray-500">{indicator.unit}</span>}
        </div>
        {hasChange && (
          <div className="flex items-center gap-1 mt-1">
            <ChangeIcon className={`w-4 h-4 ${changeColor}`} />
            <span className={`text-sm font-medium ${changeColor}`}>
              {change! >= 0 ? '+' : ''}
              {change!.toFixed(4)}
              {indicator.change_pct != null && Number.isFinite(indicator.change_pct)
                ? ` (${indicator.change_pct >= 0 ? '+' : ''}${indicator.change_pct.toFixed(2)}%)`
                : ''}
            </span>
          </div>
        )}
      </div>

      <div className="text-xs text-gray-600 mb-2 space-y-1">
        <div>
          <span className="text-gray-500">Observed:</span> {formatDate(indicator.observation_date)}
        </div>
        <div>
          <span className="text-gray-500">Released:</span> {formatDate(indicator.release_date)}
          {indicator.release_date_estimated && (
            <span
              className="text-gray-400"
              title="Estimated: the keyless source does not publish an exact release timestamp"
            >
              {' '}(est.)
            </span>
          )}
        </div>
      </div>

      {indicator.revision > 0 && (
        <div className="pt-2 border-t border-gray-200">
          <p className="text-xs text-gray-500">Revision #{indicator.revision}</p>
        </div>
      )}

      <div className="pt-2 border-t border-gray-200 mt-2">
        <p className="text-xs text-gray-500">
          Source: <span className="font-medium">{indicator.source}</span>
        </p>
      </div>
    </BaseCard>
  );
};

export default MacroIndicatorCard;
