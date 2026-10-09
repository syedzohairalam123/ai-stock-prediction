/**
 * Phase 23A — Expectation Card Component (spec §7, §18)
 *
 * Renders one sourced, market-implied policy-expectation snapshot. This is a
 * SOURCE-REPORTED probability (what a named market traded at a named
 * timestamp), never the central bank's decision and never a fabricated
 * prediction. The card shows the attribution, the observation time, the
 * methodology and the source link so every number can be verified, and it
 * renders a partial distribution honestly instead of completing it.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { DataSourceBadge } from './DataSourceBadge';

export interface ExpectationSnapshot {
  id: number;
  meeting_id: number;
  central_bank_id: string;
  meeting_scheduled_at: string | null;
  source: string;
  observed_at: string | null;
  expected_outcome: string | null;
  expected_rate_min: number | null;
  expected_rate_max: number | null;
  probabilities: Record<string, number>;
  probability_total: number | null;
  probability_note: string | null;
  methodology: string | null;
  source_url: string | null;
  data_quality: string;
}

interface ExpectationCardProps {
  snapshot: ExpectationSnapshot;
}

const DIRECTION_ORDER = ['hike', 'unchanged', 'cut'] as const;

const directionColor = (kind: string): string => {
  if (kind === 'hike') return 'bg-red-500';
  if (kind === 'cut') return 'bg-green-500';
  return 'bg-gray-400';
};

const fmtProb = (value: number | null | undefined): string =>
  value == null || !Number.isFinite(value) ? 'N/A' : `${value.toFixed(1)}%`;

export const ExpectationCard: React.FC<ExpectationCardProps> = ({ snapshot }) => {
  return (
    <BaseCard className="p-4">
      <div className="flex justify-between items-start mb-2">
        <span className="font-semibold text-gray-900">{snapshot.source}</span>
        <BaseBadge variant="outline" size="sm">{snapshot.data_quality}</BaseBadge>
      </div>

      <p className="text-xs text-gray-500 mb-2">
        Observed {snapshot.observed_at ? new Date(snapshot.observed_at).toLocaleString() : 'N/A'}
        {snapshot.expected_outcome ? ` · Most likely: ${snapshot.expected_outcome}` : ''}
        {snapshot.meeting_scheduled_at
          ? ` · Meeting ${new Date(snapshot.meeting_scheduled_at).toLocaleDateString()}`
          : ''}
      </p>

      <div className="space-y-1 mb-2">
        {DIRECTION_ORDER.map((kind) => (
          <div key={kind} className="flex items-center gap-2 text-xs">
            <span className="w-20 uppercase text-gray-500">{kind}</span>
            <div className="flex-1 h-2 bg-gray-100 rounded">
              <div
                className={`h-2 rounded ${directionColor(kind)}`}
                style={{
                  width: `${Math.max(0, Math.min(100, snapshot.probabilities[kind] ?? 0))}%`,
                }}
              />
            </div>
            <span className="w-14 text-right font-medium text-gray-800">
              {fmtProb(snapshot.probabilities[kind])}
            </span>
          </div>
        ))}
      </div>

      {(snapshot.expected_rate_min != null || snapshot.expected_rate_max != null) && (
        <p className="text-xs text-gray-600 mb-1">
          Expected rate range:{' '}
          {snapshot.expected_rate_min != null ? `${snapshot.expected_rate_min.toFixed(2)}%` : '—'}
          {' – '}
          {snapshot.expected_rate_max != null ? `${snapshot.expected_rate_max.toFixed(2)}%` : '—'}
        </p>
      )}

      {snapshot.probability_total != null && (
        <p className="text-xs text-gray-500 mb-1">
          Reported total: {fmtProb(snapshot.probability_total)}
        </p>
      )}

      {snapshot.methodology && (
        <p className="text-xs text-gray-500 mt-2">Methodology: {snapshot.methodology}</p>
      )}
      {snapshot.probability_note && (
        <p className="text-xs text-gray-400 mt-1">{snapshot.probability_note}</p>
      )}

      <DataSourceBadge
        source={snapshot.source}
        sourceUrl={snapshot.source_url}
        status={snapshot.data_quality}
        className="mt-2"
      />
    </BaseCard>
  );
};

export default ExpectationCard;
