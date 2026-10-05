/**
 * Phase 23A — Macro Series Card Component
 *
 * Displays macroeconomic indicator data with value, unit, frequency,
 * data freshness badge, and revision information.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { TrendingUp, TrendingDown, Minus, ExternalLink } from 'lucide-react';

interface MacroSeries {
  id: number;
  series_id: string;
  observation_date: string;
  release_date: string;
  value: number | null;
  unit: string;
  frequency: string;
  source: string;
  data_freshness: string;
  revision: number;
  previous_value?: number | null;
  source_url?: string;
}

interface MacroSeriesCardProps {
  series: MacroSeries;
}

export const MacroSeriesCard: React.FC<MacroSeriesCardProps> = ({ series }) => {
  const getFreshnessColor = (freshness: string) => {
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

  const getChangeIndicator = (current: number | null | undefined, previous?: number | null) => {
    if (current == null || previous == null || previous === 0) return null;
    const change = ((current - previous) / previous) * 100;
    if (change > 0) {
      return { icon: <TrendingUp className="w-4 h-4 text-green-600" />, color: 'text-green-600', value: `+${change.toFixed(2)}%` };
    } else if (change < 0) {
      return { icon: <TrendingDown className="w-4 h-4 text-red-600" />, color: 'text-red-600', value: `${change.toFixed(2)}%` };
    }
    return { icon: <Minus className="w-4 h-4 text-gray-600" />, color: 'text-gray-600', value: '0.00%' };
  };

  const changeIndicator = getChangeIndicator(series.value, series.previous_value);
  const observationDate = new Date(series.observation_date);
  const releaseDate = new Date(series.release_date);

  return (
    <BaseCard className="p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900 mb-1 text-sm">
            {series.series_id}
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <BaseBadge variant="outline" size="sm" className={getFreshnessColor(series.data_freshness)}>
              {series.data_freshness}
            </BaseBadge>
            <BaseBadge variant="outline" size="sm">
              {series.frequency}
            </BaseBadge>
          </div>
        </div>
        {series.source_url && (
          <a
            href={series.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="View source"
          >
            <ExternalLink className="w-4 h-4 text-gray-600" />
          </a>
        )}
      </div>

      {/* Value */}
      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-gray-900">
            {series.value != null ? series.value.toFixed(2) : 'N/A'}
          </span>
          <span className="text-sm text-gray-500">{series.unit}</span>
        </div>
        {changeIndicator && (
          <div className="flex items-center gap-1 mt-1">
            {changeIndicator.icon}
            <span className={`text-sm font-medium ${changeIndicator.color}`}>
              {changeIndicator.value}
            </span>
          </div>
        )}
      </div>

      {/* Dates */}
      <div className="text-xs text-gray-600 mb-2 space-y-1">
        <div>
          <span className="text-gray-500">Observed:</span>{' '}
          {observationDate.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
          })}
        </div>
        <div>
          <span className="text-gray-500">Released:</span>{' '}
          {releaseDate.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
          })}
        </div>
      </div>

      {/* Revision Info */}
      {series.revision > 0 && (
        <div className="pt-2 border-t border-gray-200">
          <p className="text-xs text-gray-500">
            Revision #{series.revision}
            {series.previous_value != null && (
              <span>
                {' '}({series.previous_value.toFixed(2)} → {series.value != null ? series.value.toFixed(2) : 'N/A'})
              </span>
            )}
          </p>
        </div>
      )}

      {/* Source Attribution */}
      <div className="pt-2 border-t border-gray-200 mt-2">
        <p className="text-xs text-gray-500">
          Source: <span className="font-medium">{series.source}</span>
        </p>
      </div>
    </BaseCard>
  );
};
