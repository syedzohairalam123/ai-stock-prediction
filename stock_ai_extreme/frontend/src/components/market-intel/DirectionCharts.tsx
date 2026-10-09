/**
 * Phase 23B — Direction Charts (spec §6)
 *
 * Four charts over the real observation series: daily price, the UP/DOWN/FLAT
 * timeline, return history, and rolling volatility. Dates come straight from
 * the backend and a session that was not observed is simply absent (Plotly
 * leaves a gap), so a missing day is never drawn as a 0% return.
 */
import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';

export interface SeriesPoint {
  trading_date: string;
  close: number | null;
  return_pct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | null;
}

export interface RollingPoint {
  trading_date: string;
  rolling_return_pct: number | null;
  rolling_volatility_pct: number | null;
}

interface DirectionChartsProps {
  series: SeriesPoint[];
  rolling: RollingPoint[];
  window?: number;
}

const DIRECTION_COLORS: Record<string, string> = {
  UP: '#22c55e',
  DOWN: '#ef4444',
  FLAT: '#9ca3af',
};

const chartStyle = { width: '100%', height: '320px' } as const;

export const DirectionCharts: React.FC<DirectionChartsProps> = ({ series, rolling, window = 20 }) => {
  const dated = useMemo(
    () => series.map((point) => ({ ...point, date: new Date(point.trading_date) })),
    [series],
  );

  if (dated.length === 0) {
    return (
      <BaseCard className="p-6">
        <p className="text-center text-gray-500">No observation series available.</p>
      </BaseCard>
    );
  }

  const priceTrace = {
    x: dated.map((p) => p.date),
    y: dated.map((p) => p.close),
    type: 'scatter' as const,
    mode: 'lines' as const,
    name: 'Close',
    line: { color: '#3b82f6', width: 2 },
    connectgaps: false,
  };

  const withDirection = dated.filter((p) => p.direction);
  const directionTrace = {
    x: withDirection.map((p) => p.date),
    y: withDirection.map((p) => p.return_pct),
    type: 'bar' as const,
    name: 'Daily return',
    marker: { color: withDirection.map((p) => DIRECTION_COLORS[p.direction as string] ?? '#9ca3af') },
    customdata: withDirection.map((p) => p.direction),
    hovertemplate: '%{x|%Y-%m-%d}<br>%{y:.3f}% — %{customdata}<extra></extra>',
  };

  const directionTimelineTrace = {
    x: withDirection.map((p) => p.date),
    y: withDirection.map(() => 1),
    type: 'scatter' as const,
    mode: 'markers' as const,
    name: 'Direction',
    marker: {
      size: 10,
      symbol: 'square',
      color: withDirection.map((p) => DIRECTION_COLORS[p.direction as string] ?? '#9ca3af'),
    },
    customdata: withDirection.map((p) => p.direction),
    hovertemplate: '%{x|%Y-%m-%d} — %{customdata}<extra></extra>',
  };

  const rollingReturnTrace = {
    x: rolling.map((p) => new Date(p.trading_date)),
    y: rolling.map((p) => p.rolling_return_pct),
    type: 'scatter' as const,
    mode: 'lines' as const,
    name: `${window}-session return`,
    line: { color: '#8b5cf6', width: 2 },
    connectgaps: false,
  };

  const volatilityTrace = {
    x: rolling.map((p) => new Date(p.trading_date)),
    y: rolling.map((p) => p.rolling_volatility_pct),
    type: 'scatter' as const,
    mode: 'lines' as const,
    name: `${window}-session annualised volatility`,
    line: { color: '#f59e0b', width: 2 },
    connectgaps: false,
  };

  const baseLayout = {
    margin: { t: 40, r: 20, b: 40, l: 55 },
    showlegend: false,
    plot_bgcolor: '#ffffff',
    paper_bgcolor: '#ffffff',
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <BaseCard className="p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-2">Daily price</h3>
        <Plot
          data={[priceTrace]}
          layout={{ ...baseLayout, yaxis: { title: 'Price', gridcolor: '#e5e7eb' }, xaxis: { gridcolor: '#e5e7eb' } }}
          config={{ responsive: true, displayModeBar: false }}
          style={chartStyle}
          useResizeHandler
        />
      </BaseCard>

      <BaseCard className="p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-2">
          Historical UP / DOWN / FLAT timeline
        </h3>
        <Plot
          data={[directionTimelineTrace]}
          layout={{
            ...baseLayout,
            yaxis: { showticklabels: false, gridcolor: '#e5e7eb', range: [0, 2] },
            xaxis: { gridcolor: '#e5e7eb' },
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={chartStyle}
          useResizeHandler
        />
      </BaseCard>

      <BaseCard className="p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-2">Return history</h3>
        <Plot
          data={[directionTrace]}
          layout={{
            ...baseLayout,
            yaxis: { title: 'Daily return (%)', gridcolor: '#e5e7eb' },
            xaxis: { gridcolor: '#e5e7eb' },
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={chartStyle}
          useResizeHandler
        />
      </BaseCard>

      <BaseCard className="p-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-2">
          Rolling return &amp; volatility
        </h3>
        <Plot
          data={[rollingReturnTrace, volatilityTrace]}
          layout={{
            ...baseLayout,
            showlegend: true,
            legend: { x: 0.02, y: 0.98, bgcolor: 'rgba(255,255,255,0.8)' },
            yaxis: { title: 'Percent (%)', gridcolor: '#e5e7eb' },
            xaxis: { gridcolor: '#e5e7eb' },
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={chartStyle}
          useResizeHandler
        />
      </BaseCard>
    </div>
  );
};

export default DirectionCharts;
