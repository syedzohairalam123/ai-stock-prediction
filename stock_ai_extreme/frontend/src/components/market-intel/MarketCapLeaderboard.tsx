/**
 * Phase 23B — Market-Cap Leaderboard (spec §11)
 *
 * Ranks are whatever the backend just computed from real observations — this
 * component never re-sorts by a hardcoded order. A company without current
 * verified data is shown as UNAVAILABLE with no rank and no invented value.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { formatCompact, formatPercent } from './api';

export interface CompanyRow {
  company_id: string;
  name: string;
  ticker: string;
  exchange: string | null;
  sector: string | null;
  price: number | null;
  currency: string | null;
  shares_outstanding: number | null;
  market_cap: number | null;
  market_cap_methodology: string;
  observation_timestamp: string | null;
  price_source: string | null;
  shares_source: string | null;
  data_quality: string;
  previous_market_cap: number | null;
  previous_rank: number | null;
  rank: number | null;
  rank_change: number | null;
  market_cap_change: number | null;
  market_cap_change_pct: number | null;
  additional_tickers: string[];
  note: string | null;
}

interface MarketCapLeaderboardProps {
  companies: CompanyRow[];
  generatedAt?: string | null;
  note?: string | null;
}

const qualityVariant = (quality: string): 'success' | 'warning' | 'danger' | 'secondary' =>
  quality === 'VERIFIED'
    ? 'success'
    : quality === 'ESTIMATED'
    ? 'warning'
    : quality === 'STALE'
    ? 'danger'
    : 'secondary';

const RankChange: React.FC<{ change: number | null }> = ({ change }) => {
  if (change === null || change === undefined) return <span className="text-gray-400">—</span>;
  if (change > 0) return <span className="text-green-600 font-semibold">▲ {change}</span>;
  if (change < 0) return <span className="text-red-600 font-semibold">▼ {Math.abs(change)}</span>;
  return <span className="text-gray-400">no change</span>;
};

export const MarketCapLeaderboard: React.FC<MarketCapLeaderboardProps> = ({
  companies,
  generatedAt,
  note,
}) => (
  <BaseCard className="p-4">
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-sm font-semibold text-gray-800">Dynamic market-cap leaderboard</h3>
      {generatedAt && (
        <span className="text-xs text-gray-500">
          generated {new Date(generatedAt).toLocaleString()}
        </span>
      )}
    </div>
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase">
            <th className="py-2 pr-4">#</th>
            <th className="py-2 pr-4">Company</th>
            <th className="py-2 pr-4">Market cap</th>
            <th className="py-2 pr-4">Prev rank</th>
            <th className="py-2 pr-4">Change</th>
            <th className="py-2 pr-4">Observed</th>
            <th className="py-2 pr-4">Source</th>
            <th className="py-2 pr-4">Quality</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((row) => (
            <tr key={row.company_id} className="border-t border-gray-100">
              <td className="py-2 pr-4 text-gray-700">{row.rank ?? '—'}</td>
              <td className="py-2 pr-4">
                <span className="font-medium text-gray-900">{row.ticker}</span>
                <span className="text-gray-500"> · {row.name}</span>
              </td>
              <td className="py-2 pr-4 text-gray-900">
                {row.market_cap === null ? (
                  <span className="text-gray-400">unavailable</span>
                ) : (
                  <span title={`${row.market_cap.toLocaleString()} ${row.currency ?? ''}`}>
                    {formatCompact(row.market_cap)}
                    {row.market_cap_methodology === 'PRICE_X_SHARES' && (
                      <span className="text-[10px] text-amber-600 ml-1">est.</span>
                    )}
                  </span>
                )}
              </td>
              <td className="py-2 pr-4 text-gray-700">{row.previous_rank ?? '—'}</td>
              <td className="py-2 pr-4">
                <RankChange change={row.rank_change} />
                {row.market_cap_change_pct !== null && (
                  <span className="text-xs text-gray-500 ml-2">
                    {formatPercent(row.market_cap_change_pct)}
                  </span>
                )}
              </td>
              <td className="py-2 pr-4 text-xs text-gray-500">
                {row.observation_timestamp
                  ? new Date(row.observation_timestamp).toLocaleDateString()
                  : '—'}
              </td>
              <td className="py-2 pr-4 text-xs text-gray-500">{row.price_source ?? '—'}</td>
              <td className="py-2 pr-4">
                <BaseBadge variant={qualityVariant(row.data_quality)} size="sm">
                  {row.data_quality}
                </BaseBadge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {note && <p className="text-xs text-gray-500 mt-3">{note}</p>}
  </BaseCard>
);

export default MarketCapLeaderboard;
