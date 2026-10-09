/**
 * Phase 23B — SPX vs SPY comparison (spec §6)
 *
 * Both instruments are indexed to 100 at the first session where they are BOTH
 * available, so the two are comparable regardless of their absolute levels. A
 * session present in only one series is a gap, never a zero — the alignment is
 * done by the backend on the exact trading date.
 */
import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';

export interface AlignedPoint {
  trading_date: string;
  spx_close: number | null;
  spy_close: number | null;
  spx_return_pct: number | null;
  spy_return_pct: number | null;
  both_available: boolean;
}

interface SpxSpyComparisonProps {
  aligned: AlignedPoint[];
  spxSource?: string | null;
  spySource?: string | null;
  note?: string | null;
}

export const SpxSpyComparison: React.FC<SpxSpyComparisonProps> = ({
  aligned,
  spxSource,
  spySource,
  note,
}) => {
  const indexed = useMemo(() => {
    const both = aligned.filter((p) => p.both_available && p.spx_close && p.spy_close);
    if (both.length === 0) return [];
    const baseSpx = both[0].spx_close as number;
    const baseSpy = both[0].spy_close as number;
    return both.map((p) => ({
      date: new Date(p.trading_date),
      spx: ((p.spx_close as number) / baseSpx) * 100,
      spy: ((p.spy_close as number) / baseSpy) * 100,
    }));
  }, [aligned]);

  if (indexed.length === 0) {
    return (
      <BaseCard className="p-6">
        <p className="text-center text-gray-500">
          No overlapping sessions to compare yet.
        </p>
      </BaseCard>
    );
  }

  const trace = (key: 'spx' | 'spy', name: string, color: string) => ({
    x: indexed.map((p) => p.date),
    y: indexed.map((p) => p[key]),
    type: 'scatter' as const,
    mode: 'lines' as const,
    name,
    line: { color, width: 2 },
  });

  return (
    <BaseCard className="p-4">
      <h3 className="text-sm font-semibold text-gray-800 mb-2">
        SPX vs SPY — indexed to 100 at first common session
      </h3>
      <Plot
        data={[trace('spx', 'SPX (index)', '#3b82f6'), trace('spy', 'SPY (ETF)', '#f97316')]}
        layout={{
          margin: { t: 30, r: 20, b: 40, l: 55 },
          showlegend: true,
          legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(255,255,255,0.8)' },
          yaxis: { title: 'Indexed level', gridcolor: '#e5e7eb' },
          xaxis: { gridcolor: '#e5e7eb' },
          plot_bgcolor: '#ffffff',
          paper_bgcolor: '#ffffff',
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: '100%', height: '340px' }}
        useResizeHandler
      />
      <p className="text-xs text-gray-500 mt-2">
        {note ?? 'Alignment is on the exact trading date; a missing session stays a gap.'}
        {spxSource ? ` · SPX source: ${spxSource}` : ''}
        {spySource ? ` · SPY source: ${spySource}` : ''}
      </p>
    </BaseCard>
  );
};

export default SpxSpyComparison;
