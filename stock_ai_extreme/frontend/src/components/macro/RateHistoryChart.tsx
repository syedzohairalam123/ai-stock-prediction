/**
 * Phase 23A — Rate History Chart Component
 *
 * Displays historical policy rate decisions as a step chart using Plotly.
 * Shows rate changes over time with direction indicators.
 */
import React, { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';

interface PolicyDecision {
  id: number;
  meeting_id: number;
  previous_rate: number;
  new_rate: number;
  change_bps: number;
  direction: string;
  decision_timestamp: string;
  source: string;
  source_document?: string;
}

interface RateHistoryChartProps {
  decisions: PolicyDecision[];
}

export const RateHistoryChart: React.FC<RateHistoryChartProps> = ({ decisions }) => {
  const [chartData, setChartData] = useState<any>(null);

  useEffect(() => {
    if (!decisions || decisions.length === 0) {
      setChartData(null);
      return;
    }

    // Sort decisions by date (oldest first)
    const sortedDecisions = [...decisions].sort((a, b) =>
      new Date(a.decision_timestamp).getTime() - new Date(b.decision_timestamp).getTime()
    );

    // Build step chart data
    const dates = sortedDecisions.map((d) => new Date(d.decision_timestamp));
    const rates = sortedDecisions.map((d) => d.new_rate);

    // Add starting point for step chart
    const firstDecision = sortedDecisions[0];
    const extendedDates = [new Date(firstDecision.decision_timestamp), ...dates];
    const extendedRates = [firstDecision.previous_rate, ...rates];

    // Color points by direction
    const colors = sortedDecisions.map((d) => {
      switch (d.direction) {
        case 'HIKE':
          return '#ef4444'; // red
        case 'CUT':
          return '#22c55e'; // green
        default:
          return '#6b7280'; // gray
      }
    });

    const data = [
      {
        x: extendedDates,
        y: extendedRates,
        type: 'scatter',
        mode: 'lines',
        line: {
          shape: 'vh', // vertical-horizontal steps
          color: '#3b82f6',
          width: 2,
        },
        name: 'Policy Rate',
      },
      {
        x: dates,
        y: rates,
        type: 'scatter',
        mode: 'markers',
        marker: {
          size: 8,
          color: colors,
          line: {
            color: '#ffffff',
            width: 2,
          },
        },
        name: 'Decision Points',
        text: sortedDecisions.map((d) => `${d.direction}<br>${d.change_bps > 0 ? '+' : ''}${d.change_bps} bps`),
        hoverinfo: 'text+x+y',
      },
    ];

    const layout = {
      title: {
        text: 'Historical Policy Rate Decisions',
        font: { size: 16, color: '#1f2937' },
      },
      xaxis: {
        title: 'Date',
        type: 'date',
        gridcolor: '#e5e7eb',
      },
      yaxis: {
        title: 'Policy Rate (%)',
        gridcolor: '#e5e7eb',
      },
      hovermode: 'x unified',
      showlegend: true,
      legend: {
        x: 0.02,
        y: 0.98,
        bgcolor: 'rgba(255, 255, 255, 0.8)',
        bordercolor: '#e5e7eb',
        borderwidth: 1,
      },
      margin: { t: 60, r: 20, b: 60, l: 60 },
      plot_bgcolor: '#ffffff',
      paper_bgcolor: '#ffffff',
    };

    const config = {
      responsive: true,
      displayModeBar: true,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    };

    setChartData({ data, layout, config });
  }, [decisions]);

  if (!chartData) {
    return (
      <BaseCard className="p-6">
        <p className="text-center text-gray-500">No rate history data available</p>
      </BaseCard>
    );
  }

  return (
    <BaseCard className="p-6">
      <Plot
        data={chartData.data}
        layout={chartData.layout}
        config={chartData.config}
        style={{ width: '100%', height: '400px' }}
        useResizeHandler={true}
      />
    </BaseCard>
  );
};
