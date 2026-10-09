/**
 * Phase 23B — Market-Cap Race (spec §12)
 *
 * A *descriptive* comparison of observed companies over a period: current
 * observed rankings, historical rankings where data exists, ranking changes
 * and market-cap changes. It deliberately produces no probability and no
 * forecast — the backend note says so, and this component never renders a
 * "chance of staying largest" style claim.
 */
import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { formatCompact, formatPercent } from './api';

export interface RaceRow {
  company_id: string;
  name: string;
  ticker: string;
  current_market_cap: number | null;
  current_rank: number | null;
  first_observed_market_cap: number | null;
  first_observed_rank: number | null;
  market_cap_change: number | null;
  market_cap_change_pct: number | null;
  history_points: number;
  data_quality: string;
}

export interface RaceResponse {
  rows: RaceRow[];
  note: string;
  period_days: number;
  observation_start: string | null;
}

interface MarketCapRaceProps {
  rows: RaceRow[];
  note?: string | null;
  periodDays?: number;
  observationStart?: string | null;
}

const qualityVariant = (quality: string): 'success' | 'warning' | 'danger' | 'secondary' =>
  quality === 'VERIFIED' ? 'success' : quality === 'ESTIMATED' ? 'warning' : quality === 'STALE' ? 'danger' : 'secondary';

export const MarketCapRace: React.FC<MarketCapRaceProps> = ({
  rows,
  note,
  periodDays,
  observationStart,
}) => {
  // Only rows with an observed current cap can be charted/ranked; the rest are
  // listed honestly as history-only.
  const charted = useMemo(
    () =>
      rows
        .filter((row) => row.current_market_cap !== null)
        .sort((a, b) => (b.current_market_cap ?? 0) - (a.current_market_cap ?? 0))
        .slice(0, 12),
    [rows],
  );

  if (rows.length === 0) {
    return (
      <BaseCard className="p-6">
        <p className="text-center text-gray-500">
          No market-cap history stored yet — refresh the leaderboard to record an observation.
        </p>
      </BaseCard>
    );
  }

  const firstCaps = charted.map((row) => row.first_observed_market_cap);
  const currentCaps = charted.map((row) => row.current_market_cap);
  const tickers = charted.map((row) => row.ticker);

  return (
    <BaseCard className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-800">Market-cap race (descriptive)</h3>
        <div className="flex items-center gap-2">
          {periodDays && (
            <span className="text-xs text-gray-500">
              Window: last {periodDays} days{observationStart ? ` · since ${new Date(observationStart).toLocaleDateString()}` : ''}
            </span>
          )}
          <BaseBadge variant="info" size="sm">
            OBSERVED ONLY
          </BaseBadge>
        </div>
      </div>

      {charted.length > 0 && (
        <Plot
          data={[
            {
              x: tickers,
              y: firstCaps,
              type: 'bar',
              name: 'First observed cap',
              marker: { color: '#cbd5e1' },
              hovertemplate: '%{x}<br>first %{y:.3s}<extra></extra>',
            },
            {
              x: tickers,
              y: currentCaps,
              type: 'bar',
              name: 'Current observed cap',
              marker: { color: '#3b82f6' },
              hovertemplate: '%{x}<br>current %{y:.3s}<extra></extra>',
            },
          ]}
          layout={{
            barmode: 'group',
            margin: { t: 30, r: 20, b: 60, l: 70 },
            showlegend: true,
            legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(255,255,255,0.8)' },
            yaxis: { title: 'Market cap', gridcolor: '#e5e7eb' },
            xaxis: { gridcolor: '#e5e7eb' },
            plot_bgcolor: '#ffffff',
            paper_bgcolor: '#ffffff',
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={{ width: '100%', height: '320px' }}
          useResizeHandler
        />
      )}

      <div className="overflow-x-auto mt-3">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase">
              <th className="py-2 pr-4">Company</th>
              <th className="py-2 pr-4">Current rank</th>
              <th className="py-2 pr-4">Current cap</th>
              <th className="py-2 pr-4">First observed</th>
              <th className="py-2 pr-4">Cap change</th>
              <th className="py-2 pr-4">Observations</th>
              <th className="py-2 pr-4">Quality</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.company_id} className="border-t border-gray-100">
                <td className="py-2 pr-4">
                  <span className="font-medium text-gray-900">{row.ticker}</span>
                  <span className="text-gray-500"> · {row.name}</span>
                </td>
                <td className="py-2 pr-4 text-gray-700">
                  {row.current_rank ?? '—'}
                  {row.first_observed_rank !== null && row.current_rank !== null && (
                    <span
                      className={`ml-2 text-xs ${
                        row.current_rank < row.first_observed_rank ? 'text-green-600' : row.current_rank > row.first_observed_rank ? 'text-red-600' : 'text-gray-400'
                      }`}
                    >
                      {row.current_rank < row.first_observed_rank
                        ? `▲ from ${row.first_observed_rank}`
                        : row.current_rank > row.first_observed_rank
                        ? `▼ from ${row.first_observed_rank}`
                        : 'no change'}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 text-gray-900">{formatCompact(row.current_market_cap)}</td>
                <td className="py-2 pr-4 text-gray-600">{formatCompact(row.first_observed_market_cap)}</td>
                <td className="py-2 pr-4 text-gray-700">
                  {row.market_cap_change === null ? (
                    '—'
                  ) : (
                    <>
                      {formatCompact(row.market_cap_change)}{' '}
                      <span className="text-xs text-gray-500">{formatPercent(row.market_cap_change_pct)}</span>
                    </>
                  )}
                </td>
                <td className="py-2 pr-4 text-xs text-gray-500">{row.history_points}</td>
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
};

export default MarketCapRace;
