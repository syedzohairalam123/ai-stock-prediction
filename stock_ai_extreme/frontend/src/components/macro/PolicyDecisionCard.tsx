/**
 * Phase 23A — Policy Decision Card Component
 *
 * Displays historical policy rate decisions with previous rate, new rate,
 * change in basis points, direction, and source attribution.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { TrendingUp, TrendingDown, Minus, ExternalLink } from 'lucide-react';

interface PolicyDecision {
  id: number;
  meeting_id: number;
  previous_rate: number | null;
  new_rate: number | null;
  change_bps: number | null;
  direction: string;
  decision_timestamp: string;
  source: string;
  source_document?: string;
}

interface PolicyDecisionCardProps {
  decision: PolicyDecision;
}

export const PolicyDecisionCard: React.FC<PolicyDecisionCardProps> = ({
  decision,
}) => {
  const getDirectionIcon = (direction: string) => {
    switch (direction) {
      case 'HIKE':
        return <TrendingUp className="w-5 h-5 text-red-600" />;
      case 'CUT':
        return <TrendingDown className="w-5 h-5 text-green-600" />;
      default:
        return <Minus className="w-5 h-5 text-gray-600" />;
    }
  };

  const getDirectionColor = (direction: string) => {
    switch (direction) {
      case 'HIKE':
        return 'text-red-600 bg-red-50';
      case 'CUT':
        return 'text-green-600 bg-green-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  const formatBps = (bps: number | null) => {
    if (bps == null) return 'N/A';
    if (bps > 0) return `+${bps} bps`;
    if (bps < 0) return `${bps} bps`;
    return '0 bps';
  };

  const decisionDate = new Date(decision.decision_timestamp);

  return (
    <BaseCard className="p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-center gap-2">
          {getDirectionIcon(decision.direction)}
          <BaseBadge
            variant="outline"
            size="sm"
            className={getDirectionColor(decision.direction)}
          >
            {decision.direction}
          </BaseBadge>
        </div>
        {decision.source_document && (
          <a
            href={decision.source_document}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="View official document"
          >
            <ExternalLink className="w-4 h-4 text-gray-600" />
          </a>
        )}
      </div>

      {/* Rate Change */}
      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-gray-900">
            {decision.new_rate != null ? `${decision.new_rate.toFixed(2)}%` : 'N/A'}
          </span>
          <span className="text-sm text-gray-500">
            from {decision.previous_rate != null ? `${decision.previous_rate.toFixed(2)}%` : 'N/A'}
          </span>
        </div>
        <p className={`text-lg font-semibold mt-1 ${getDirectionColor(decision.direction).split(' ')[0]}`}>
          {formatBps(decision.change_bps)}
        </p>
      </div>

      {/* Decision Date */}
      <div className="text-sm text-gray-600 mb-3">
        {decisionDate.toLocaleDateString('en-US', {
          weekday: 'short',
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        })}
      </div>

      {/* Source Attribution */}
      <div className="pt-3 border-t border-gray-200">
        <p className="text-xs text-gray-500">
          Source: <span className="font-medium">{decision.source}</span>
        </p>
      </div>
    </BaseCard>
  );
};
