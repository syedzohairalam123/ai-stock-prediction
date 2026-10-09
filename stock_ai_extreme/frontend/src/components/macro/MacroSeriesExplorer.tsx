/**
 * Phase 23A — Macro Series Explorer (spec §10, §11, §12, §18)
 *
 * Lets the user pick any curated economic series the engine serves and shows
 * its real published observations: latest value (MacroSeriesCard), the trend
 * analytics the backend computed, and the recent history — with observation
 * date kept distinct from release date and every revision surfaced. The whole
 * panel is driven by the versioned API (`/series`, `/series/{id}`,
 * `/analytics/trend/{id}`); no series is hardcoded in the component and no
 * value is invented when a series has nothing stored yet.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { MacroSeriesCard } from './MacroSeriesCard';
import { FreshnessBadge } from './FreshnessBadge';
import { DataSourceBadge } from './DataSourceBadge';
import { macroGet } from './api';

export interface SeriesOption {
  key: string;
  series_id: string;
  description: string;
}

export interface MacroSeriesObservation {
  id: number;
  series_id: string;
  observation_date: string;
  release_date: string;
  value: number | null;
  unit: string;
  frequency: string;
  source: string;
  source_url?: string | null;
  data_freshness: string;
  revision: number;
  previous_value?: number | null;
}

interface TrendAnalytics {
  series_id: string;
  trend: string;
  latest_value: number;
  previous_value: number;
  change_pct: number;
  rolling_avg_3m: number | null;
  rolling_avg_6m: number | null;
  rolling_avg_12m: number | null;
  volatility: number;
  momentum: number;
}

interface MacroSeriesExplorerProps {
  /** Keys to offer; defaults to every series the API lists. */
  keys?: string[];
}

const trendColor = (trend: string): string => {
  if (trend === 'increasing') return 'text-green-600';
  if (trend === 'decreasing') return 'text-red-600';
  if (trend === 'volatile') return 'text-orange-600';
  return 'text-gray-600';
};

const fmt = (value: number | null | undefined, digits = 4): string =>
  value == null || !Number.isFinite(value)
    ? 'N/A'
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });

/** Minimal, dependency-free sparkline over real observation values. */
const Sparkline: React.FC<{ values: number[] }> = ({ values }) => {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 240;
  const height = 48;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-12"
      role="img"
      aria-label="Recent observations sparkline"
      preserveAspectRatio="none"
    >
      <polyline
        fill="none"
        stroke="#3b82f6"
        strokeWidth="2"
        points={points}
      />
    </svg>
  );
};

export const MacroSeriesExplorer: React.FC<MacroSeriesExplorerProps> = ({ keys }) => {
  const [options, setOptions] = useState<SeriesOption[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [observations, setObservations] = useState<MacroSeriesObservation[]>([]);
  const [trend, setTrend] = useState<TrendAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = await macroGet<{ series: SeriesOption[] }>('/api/v1/macro/series');
        if (cancelled) return;
        const allowed = keys && keys.length > 0
          ? body.series.filter((option) => keys.includes(option.key))
          : body.series;
        setOptions(allowed);
        setSelected((current) => current || allowed[0]?.series_id || '');
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load series list');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [keys]);

  const loadSeries = useCallback(async (seriesId: string) => {
    if (!seriesId) return;
    setLoading(true);
    setError(null);
    try {
      const [rows, trendBody] = await Promise.all([
        macroGet<MacroSeriesObservation[]>(
          `/api/v1/macro/series/${encodeURIComponent(seriesId)}?limit=120`
        ),
        macroGet<TrendAnalytics>(
          `/api/v1/macro/analytics/trend/${encodeURIComponent(seriesId)}`
        ).catch(() => null),
      ]);
      setObservations(rows);
      setTrend(trendBody);
    } catch (err) {
      setObservations([]);
      setTrend(null);
      setError(err instanceof Error ? err.message : 'Failed to load series');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selected) loadSeries(selected);
  }, [selected, loadSeries]);

  const latest = observations[0] ?? null;
  // Observations arrive newest-first; the sparkline reads oldest → newest.
  const sparkValues = useMemo(
    () =>
      observations
        .slice(0, 60)
        .map((row) => row.value)
        .filter((value): value is number => value != null && Number.isFinite(value))
        .reverse(),
    [observations]
  );

  return (
    <section className="mb-6" aria-label="Macro series explorer">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-xl font-bold text-gray-900">Macro Series Explorer</h2>
        <label className="text-sm text-gray-600">
          Series{' '}
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="ml-1 rounded border border-gray-300 bg-white px-2 py-1 text-sm"
          >
            {options.map((option) => (
              <option key={option.series_id} value={option.series_id}>
                {option.description} ({option.series_id})
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 text-red-800 rounded">{error}</div>
      )}

      {latest ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1">
            <MacroSeriesCard series={latest} />
          </div>

          <BaseCard className="p-4 lg:col-span-2">
            {trend ? (
              <div className="mb-3">
                <div className="flex items-center gap-3 flex-wrap mb-2">
                  <span className={`font-semibold capitalize ${trendColor(trend.trend)}`}>
                    {trend.trend}
                  </span>
                  <span className="text-sm text-gray-600">
                    latest {fmt(trend.latest_value)} · previous {fmt(trend.previous_value)} ·{' '}
                    {trend.change_pct >= 0 ? '+' : ''}
                    {trend.change_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-gray-600">
                  <div>Rolling 3M: <span className="font-medium">{fmt(trend.rolling_avg_3m)}</span></div>
                  <div>Rolling 6M: <span className="font-medium">{fmt(trend.rolling_avg_6m)}</span></div>
                  <div>Rolling 12M: <span className="font-medium">{fmt(trend.rolling_avg_12m)}</span></div>
                  <div>Volatility: <span className="font-medium">{fmt(trend.volatility)}</span></div>
                  <div>Momentum: <span className="font-medium">{trend.momentum.toFixed(2)}%</span></div>
                </div>
                <p className="text-xs text-gray-400 mt-2">
                  Trend classification is computed by the backend from stored observations — a
                  historical reading, not a forecast.
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-500 mb-3">
                Trend analytics unavailable for this series.
              </p>
            )}

            <div className="flex items-center gap-2 flex-wrap mb-2">
              <FreshnessBadge
                freshness={latest.data_freshness}
                estimated={latest.source === 'FRED CSV'}
              />
              <BaseBadge variant="outline" size="sm">{latest.frequency}</BaseBadge>
              <span className="text-xs text-gray-400">{observations.length} stored observations</span>
            </div>

            <Sparkline values={sparkValues} />

            <p className="text-xs text-gray-500 mt-2">
              Observation {latest.observation_date.slice(0, 10)} · Release{' '}
              {latest.release_date.slice(0, 10)}
              {latest.source === 'FRED CSV' ? ' (estimated)' : ''}
              {' · '}
              <DataSourceBadge
                source={latest.source}
                sourceUrl={latest.source_url}
                label="Source"
              />
            </p>
          </BaseCard>
        </div>
      ) : (
        <BaseCard className="p-6">
          <p className="text-center text-gray-500">
            {loading
              ? 'Loading series…'
              : 'No stored observations for this series yet — use “Refresh from official sources”.'}
          </p>
        </BaseCard>
      )}
    </section>
  );
};

export default MacroSeriesExplorer;
