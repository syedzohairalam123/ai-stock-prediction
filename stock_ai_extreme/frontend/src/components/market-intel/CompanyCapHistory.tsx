/**
 * Phase 23B — Company Market-Cap History (spec §14)
 *
 * Charts only the observations the backend actually stored: observation date,
 * market capitalisation and rank, each with its source. Missing periods are
 * absent — the chart connects real points and never fabricates a value to fill
 * a gap. When a company has no stored points yet the panel says so.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Plot from 'react-plotly.js';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { marketIntelGet, marketIntelPost, formatCompact, formatPrice } from './api';
import type { CompanyOption } from './ScenarioCalculator';

interface CorporateAction {
  action_type: string;
  ratio: number | null;
  effective_date: string;
  source: string | null;
  notes: string | null;
}

interface HistoryPoint {
  observed_at: string | null;
  price: number | null;
  currency: string | null;
  shares_outstanding: number | null;
  market_cap: number | null;
  market_cap_methodology: string;
  data_quality: string;
  price_source: string | null;
  shares_source: string | null;
}

interface RankPoint {
  observed_at: string | null;
  rank: number;
  market_cap: number | null;
  source: string | null;
  data_quality: string;
}

interface CompanyHistoryResponse {
  company_id: string;
  name: string;
  ticker: string;
  points: HistoryPoint[];
  ranks: RankPoint[];
  point_count: number;
  note: string;
}

interface CompanyCapHistoryProps {
  companies: CompanyOption[];
}

export const CompanyCapHistory: React.FC<CompanyCapHistoryProps> = ({ companies }) => {
  const [companyId, setCompanyId] = useState(companies[0]?.company_id ?? '');
  const [payload, setPayload] = useState<CompanyHistoryResponse | null>(null);
  const [actions, setActions] = useState<CorporateAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!companyId && companies[0]) setCompanyId(companies[0].company_id);
  }, [companies, companyId]);

  const load = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [data, actionData] = await Promise.all([
        marketIntelGet<CompanyHistoryResponse>(
          `/api/v1/market-intel/company/${id}/history?limit=1000`,
        ),
        marketIntelGet<{ actions: CorporateAction[] }>(
          `/api/v1/market-intel/company/${id}/corporate-actions?limit=50`,
        ),
      ]);
      setPayload(data);
      setActions(actionData.actions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'History unavailable.');
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshSplits = useCallback(async () => {
    if (!companyId) return;
    setRefreshing(true);
    try {
      await marketIntelPost(`/api/v1/market-intel/corporate-actions/refresh/${companyId}`);
      await load(companyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Splits refresh failed.');
    } finally {
      setRefreshing(false);
    }
  }, [companyId, load]);

  useEffect(() => {
    void load(companyId);
  }, [companyId, load]);

  const usablePoints = useMemo(
    () => (payload?.points ?? []).filter((point) => point.observed_at && point.market_cap !== null),
    [payload],
  );

  const latest = payload?.points.length ? payload.points[payload.points.length - 1] : null;

  return (
    <BaseCard className="p-4">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">Company market-cap history</h3>
          <p className="text-xs text-gray-500">
            Stored real observations only — missing periods are absent, never zero-filled.
          </p>
        </div>
        <label className="text-xs text-gray-600">
          Company
          <select
            className="block mt-1 border border-gray-300 rounded px-2 py-1 text-sm text-gray-900"
            value={companyId}
            onChange={(event) => setCompanyId(event.target.value)}
          >
            {companies.map((company) => (
              <option key={company.company_id} value={company.company_id}>
                {company.ticker} — {company.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && usablePoints.length === 0 && (
        <p className="text-sm text-gray-500">
          No stored observations for this company yet. Open the leaderboard once to record one.
        </p>
      )}

      {usablePoints.length > 0 && (
        <>
          <Plot
            data={[
              {
                x: usablePoints.map((point) => new Date(point.observed_at as string)),
                y: usablePoints.map((point) => point.market_cap),
                type: 'scatter',
                mode: 'lines+markers',
                name: 'Market cap',
                line: { color: '#3b82f6', width: 2 },
                hovertemplate: '%{x|%Y-%m-%d}<br>%{y:.3s}<extra></extra>',
              },
            ]}
            layout={{
              margin: { t: 20, r: 20, b: 40, l: 70 },
              showlegend: false,
              yaxis: { title: 'Market cap', gridcolor: '#e5e7eb' },
              xaxis: { gridcolor: '#e5e7eb' },
              plot_bgcolor: '#ffffff',
              paper_bgcolor: '#ffffff',
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%', height: '300px' }}
            useResizeHandler
          />

          {(payload?.ranks.length ?? 0) > 0 && (
            <Plot
              data={[
                {
                  x: payload!.ranks.map((point) => new Date(point.observed_at as string)),
                  y: payload!.ranks.map((point) => point.rank),
                  type: 'scatter',
                  mode: 'lines+markers',
                  name: 'Rank',
                  line: { color: '#8b5cf6', width: 2 },
                  hovertemplate: '%{x|%Y-%m-%d}<br>rank %{y}<extra></extra>',
                },
              ]}
              layout={{
                margin: { t: 20, r: 20, b: 40, l: 70 },
                showlegend: false,
                yaxis: { title: 'Rank (1 = largest)', autorange: 'reversed', gridcolor: '#e5e7eb' },
                xaxis: { gridcolor: '#e5e7eb' },
                plot_bgcolor: '#ffffff',
                paper_bgcolor: '#ffffff',
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '240px' }}
              useResizeHandler
            />
          )}

          {latest && (
            <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-gray-600">
              <span>
                Latest observed:{' '}
                <span className="font-medium text-gray-900">
                  {latest.observed_at ? new Date(latest.observed_at).toLocaleString() : '—'}
                </span>
              </span>
              <span>
                Price: <span className="font-medium text-gray-900">{formatPrice(latest.price)} {latest.currency ?? ''}</span>
              </span>
              <span>
                Cap: <span className="font-medium text-gray-900">{formatCompact(latest.market_cap)}</span>
              </span>
              <BaseBadge variant={latest.market_cap_methodology === 'PROVIDER_REPORTED' ? 'success' : 'warning'} size="sm">
                {latest.market_cap_methodology}
              </BaseBadge>
              <BaseBadge variant={latest.data_quality === 'VERIFIED' ? 'success' : 'secondary'} size="sm">
                {latest.data_quality}
              </BaseBadge>
              <span>Source: {latest.price_source ?? '—'}</span>
            </div>
          )}
        </>
      )}

      {/* §10 — source-reported corporate actions that break comparability */}
      <div className="mt-4 border-t border-gray-100 pt-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-xs font-semibold text-gray-700">
            Corporate actions ({actions.length})
          </h4>
          <button
            type="button"
            onClick={() => void refreshSplits()}
            disabled={refreshing || !companyId}
            className="px-2 py-1 rounded border border-gray-300 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {refreshing ? 'Refreshing…' : 'Refresh splits from provider'}
          </button>
        </div>
        {actions.length === 0 ? (
          <p className="text-xs text-gray-500 mt-2">
            No source-reported corporate actions stored for this company.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {actions.slice(0, 5).map((action) => (
              <li key={`${action.action_type}-${action.effective_date}`} className="text-xs text-gray-600">
                <span className="font-medium text-gray-800">{action.action_type}</span>{' '}
                {action.ratio ? `${action.ratio}:1 ` : ''}
                {action.effective_date ? new Date(action.effective_date).toLocaleDateString() : '—'}
                {action.source ? ` · ${action.source}` : ''}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-gray-400 mt-1">
          A split/buyback/issuance makes a raw price or share comparison invalid, so caps
          across one are flagged rather than shown as growth.
        </p>
      </div>

      {payload?.note && <p className="text-xs text-gray-500 mt-3">{payload.note}</p>}
    </BaseCard>
  );
};

export default CompanyCapHistory;
