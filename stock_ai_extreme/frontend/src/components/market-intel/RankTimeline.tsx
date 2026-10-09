/**
 * Phase 23B — Cross-company rank timeline (spec §14)
 *
 * Charts the stored rank snapshots (observation date, company, rank) for the
 * largest companies over time. Only stored observations are plotted — a company
 * that was not observed at a time is a gap, never a fabricated rank. The y-axis
 * is inverted so rank 1 is at the top.
 */
import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';

export interface RankSeriesPoint {
  observed_at: string | null;
  market_cap: number | null;
  rank: number;
  source: string | null;
  data_quality: string;
}

export interface RankSeries {
  ticker: string;
  points: RankSeriesPoint[];
}

interface RankTimelineProps {
  series: RankSeries[];
  note?: string | null;
  /** How many top-ranked companies to draw (rest are listed in the footnote). */
  topN?: number;
}

const PALETTE = [
  '#2563eb', '#dc2626', '#16a34a', '#f59e0b', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#9333ea', '#ea580c',
];

export const RankTimeline: React.FC<RankTimelineProps> = ({ series, note, topN = 10 }) => {
  const { drawn, skipped } = useMemo(() => {
    const withPoints = series.filter((entry) => entry.points.length > 0);
    // Latest observed rank decides who is "top"; missing latest rank sorts last.
    const latestRank = (entry: RankSeries): number => {
      for (let i = entry.points.length - 1; i >= 0; i -= 1) {
        if (entry.points[i].rank !== null && entry.points[i].rank !== undefined) return entry.points[i].rank;
      }
      return Number.MAX_SAFE_INTEGER;
    };
    const ordered = [...withPoints].sort((a, b) => latestRank(a) - latestRank(b));
    return { drawn: ordered.slice(0, topN), skipped: ordered.length - Math.min(topN, ordered.length) };
  }, [series, topN]);

  if (drawn.length === 0) {
    return (
      <BaseCard className="p-6">
        <p className="text-center text-gray-500">
          No rank snapshots stored yet — refresh the leaderboard to record one.
        </p>
      </BaseCard>
    );
  }

  const traces = drawn.map((entry, index) => ({
    x: entry.points.map((point) => new Date(point.observed_at as string)),
    y: entry.points.map((point) => point.rank),
    type: 'scatter' as const,
    mode: 'lines+markers' as const,
    name: entry.ticker,
    line: { color: PALETTE[index % PALETTE.length], width: 2 },
    connectgaps: false,
  }));

  return (
    <BaseCard className="p-4">
      <h3 className="text-sm font-semibold text-gray-800 mb-1">
        Ranking timeline — largest {drawn.length} companies
      </h3>
      <p className="text-xs text-gray-500 mb-2">
        Stored rank snapshots only; a company not observed at a time is a gap, never an invented rank.
      </p>
      <Plot
        data={traces}
        layout={{
          margin: { t: 20, r: 20, b: 40, l: 70 },
          showlegend: true,
          legend: { x: 1.0, xanchor: 'right', y: 1.0, bgcolor: 'rgba(255,255,255,0.8)' },
          yaxis: { title: 'Rank (1 = largest)', autorange: 'reversed', gridcolor: '#e5e7eb' },
          xaxis: { gridcolor: '#e5e7eb' },
          plot_bgcolor: '#ffffff',
          paper_bgcolor: '#ffffff',
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: '100%', height: '380px' }}
        useResizeHandler
      />
      {note && <p className="text-xs text-gray-500 mt-2">{note}</p>}
      {skipped > 0 && (
        <p className="text-[11px] text-gray-400 mt-1">
          {skipped} more companie(s) have stored snapshots and are shown in the race table below.
        </p>
      )}
    </BaseCard>
  );
};

export default RankTimeline;
