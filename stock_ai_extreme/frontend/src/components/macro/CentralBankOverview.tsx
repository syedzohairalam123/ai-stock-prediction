/**
 * Phase 23A — Central Bank Overview Component
 *
 * Displays central bank information with current policy rate, next meeting countdown,
 * and previous decision. Includes refresh functionality and source attribution.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { Clock, TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';

interface CentralBank {
  id: string;
  name: string;
  country: string;
  currency: string;
  timezone: string;
  source: string;
}

interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  total_seconds: number;
  is_past: boolean;
}

interface PolicyMeeting {
  id: number;
  scheduled_at: string;
  status: string;
  countdown: Countdown;
  current_policy_rate?: number | null;
  previous_decision?: string;
  source_url?: string;
}

/** Latest verified policy setting with both range bounds labelled (spec §4). */
export interface PolicyRateRange {
  central_bank_id: string;
  is_range: boolean;
  lower: number | null;
  upper: number | null;
  midpoint: number | null;
  label: string;
  source: string | null;
  source_url: string | null;
  status: string;
}

interface CentralBankOverviewProps {
  bank: CentralBank;
  currentRate?: number | null;
  previousDecision?: string;
  nextMeeting?: PolicyMeeting;
  rateRange?: PolicyRateRange | null;
  onRefresh?: () => void;
}

export const CentralBankOverview: React.FC<CentralBankOverviewProps> = ({
  bank,
  currentRate,
  previousDecision,
  nextMeeting,
  rateRange,
  onRefresh,
}) => {
  const getDirectionIcon = (direction?: string) => {
    if (!direction) return <Minus className="w-4 h-4" />;
    switch (direction) {
      case 'HIKE':
        return <TrendingUp className="w-4 h-4 text-red-600" />;
      case 'CUT':
        return <TrendingDown className="w-4 h-4 text-green-600" />;
      default:
        return <Minus className="w-4 h-4 text-gray-600" />;
    }
  };

  const getDirectionColor = (direction?: string) => {
    if (!direction) return 'text-gray-600';
    switch (direction) {
      case 'HIKE':
        return 'text-red-600';
      case 'CUT':
        return 'text-green-600';
      default:
        return 'text-gray-600';
    }
  };

  const formatCountdown = (countdown: Countdown) => {
    if (countdown.is_past) {
      return 'Meeting passed';
    }
    if (countdown.days > 0) {
      return `${countdown.days}d ${countdown.hours}h ${countdown.minutes}m`;
    }
    if (countdown.hours > 0) {
      return `${countdown.hours}h ${countdown.minutes}m ${countdown.seconds}s`;
    }
    return `${countdown.minutes}m ${countdown.seconds}s`;
  };

  return (
    <BaseCard className="p-6">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{bank.name}</h2>
          <p className="text-sm text-gray-600">{bank.country}</p>
          <div className="flex items-center gap-2 mt-2">
            <BaseBadge variant="secondary" size="sm">
              {bank.currency}
            </BaseBadge>
            <BaseBadge variant="outline" size="sm">
              {bank.timezone}
            </BaseBadge>
          </div>
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh data"
          >
            <RefreshCw className="w-5 h-5 text-gray-600" />
          </button>
        )}
      </div>

      {/* Current Policy Rate / Target Range */}
      <div className="mb-4 p-4 bg-blue-50 rounded-lg">
        <p className="text-xs text-gray-500 uppercase mb-1">
          {rateRange?.is_range ? rateRange.label : 'Current Policy Rate'}
        </p>
        <div className="flex items-center gap-2">
          {rateRange?.is_range && rateRange.lower != null && rateRange.upper != null ? (
            <>
              <span className="text-3xl font-bold text-gray-900">
                {rateRange.lower.toFixed(2)}%–{rateRange.upper.toFixed(2)}%
              </span>
              {getDirectionIcon(previousDecision)}
            </>
          ) : currentRate != null ? (
            <>
              <span className="text-3xl font-bold text-gray-900">
                {currentRate.toFixed(2)}%
              </span>
              {getDirectionIcon(previousDecision)}
            </>
          ) : (
            <span className="text-gray-500">No data available</span>
          )}
        </div>
        {rateRange?.source && (
          <p className="text-xs text-gray-500 mt-1">
            {rateRange.is_range && rateRange.midpoint != null
              ? `Midpoint ${rateRange.midpoint.toFixed(2)}% · `
              : ''}
            {rateRange.status} · source {rateRange.source}
            {rateRange.source_url && (
              <a
                href={rateRange.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 text-blue-600 hover:underline"
              >
                (verify)
              </a>
            )}
          </p>
        )}
        {previousDecision && (
          <p className={`text-sm mt-1 ${getDirectionColor(previousDecision)}`}>
            Latest decision: {previousDecision}
          </p>
        )}
      </div>

      {/* Next Meeting Countdown */}
      {nextMeeting && (
        <div className="p-4 bg-gray-50 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-4 h-4 text-gray-600" />
            <p className="text-xs text-gray-500 uppercase">Next Meeting</p>
          </div>
          <p className="text-lg font-semibold text-gray-900 mb-1">
            {formatCountdown(nextMeeting.countdown)}
          </p>
          <p className="text-sm text-gray-600">
            {new Date(nextMeeting.scheduled_at).toLocaleDateString('en-US', {
              weekday: 'long',
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </p>
          {nextMeeting.source_url && (
            <a
              href={nextMeeting.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline mt-1 block"
            >
              Official Source
            </a>
          )}
        </div>
      )}

      {/* Source Attribution */}
      <div className="mt-4 pt-4 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          Source: <span className="font-medium">{bank.source}</span>
        </p>
      </div>
    </BaseCard>
  );
};
