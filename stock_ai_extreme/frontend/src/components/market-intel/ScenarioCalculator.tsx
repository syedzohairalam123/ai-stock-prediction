/**
 * Phase 23B — Market-Cap Scenario Calculator (spec §13)
 *
 * Pick a company and an assumed price change; the backend returns the
 * arithmetic result (scenarioPrice = reference × (1 + r), scenarioMarketCap =
 * scenarioPrice × shares). The output is labelled HYPOTHETICAL SCENARIO because
 * it is arithmetic under an assumption, not a prediction or guarantee.
 */
import React, { useState } from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { MARKET_INTEL_API_BASE, formatCompact, formatPrice } from './api';

export interface CompanyOption {
  company_id: string;
  name: string;
  ticker: string;
}

export interface ScenarioResult {
  company_id: string;
  name: string;
  ticker: string;
  currency: string | null;
  reference_price: number | null;
  shares_outstanding: number | null;
  scenario_return: number;
  scenario_return_pct: number;
  scenario_price: number | null;
  scenario_market_cap: number | null;
  reference_market_cap: number | null;
  reference_data_quality: string;
  reference_observation_timestamp: string | null;
  label: string;
  note: string;
}

interface ScenarioCalculatorProps {
  companies: CompanyOption[];
}

const PRESETS = [-50, -25, -10, 10, 25, 50];

export const ScenarioCalculator: React.FC<ScenarioCalculatorProps> = ({ companies }) => {
  const [companyId, setCompanyId] = useState(companies[0]?.company_id ?? '');
  const [returnPct, setReturnPct] = useState(10);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async (pct: number = returnPct) => {
    if (!companyId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${MARKET_INTEL_API_BASE}/api/v1/market-intel/company/${companyId}/scenario?return_pct=${pct}`,
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.detail ? String(body.detail) : `${response.status}`);
      }
      setResult((await response.json()) as ScenarioResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scenario unavailable.');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <BaseCard className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-800">Hypothetical scenario calculator</h3>
        <BaseBadge variant="warning" size="sm">
          HYPOTHETICAL
        </BaseBadge>
      </div>

      <div className="flex flex-wrap items-end gap-3">
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
        <label className="text-xs text-gray-600">
          Assumed price change (%)
          <input
            type="number"
            className="block mt-1 border border-gray-300 rounded px-2 py-1 text-sm text-gray-900 w-32"
            value={returnPct}
            step={1}
            min={-99}
            onChange={(event) => setReturnPct(Number(event.target.value))}
          />
        </label>
        <button
          type="button"
          onClick={() => run()}
          disabled={loading || !companyId}
          className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
        >
          {loading ? 'Calculating…' : 'Calculate scenario'}
        </button>
        <div className="flex gap-1">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => {
                setReturnPct(preset);
                run(preset);
              }}
              className="px-2 py-1 rounded border border-gray-300 text-xs text-gray-700 hover:bg-gray-50"
            >
              {preset > 0 ? `+${preset}%` : `${preset}%`}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-red-600 mt-3">{error}</p>}

      {result && (
        <div className="mt-4 border border-amber-200 bg-amber-50 rounded p-3">
          <div className="flex items-center gap-2 mb-2">
            <BaseBadge variant="warning" size="sm">
              {result.label}
            </BaseBadge>
            <span className="text-xs text-gray-600">
              {result.ticker} · reference {formatPrice(result.reference_price)}{' '}
              {result.currency ?? ''} ({result.reference_data_quality})
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <div className="text-xs text-gray-500">Assumed change</div>
              <div className="font-semibold text-gray-900">
                {result.scenario_return_pct > 0 ? '+' : ''}
                {result.scenario_return_pct}%
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Scenario price</div>
              <div className="font-semibold text-gray-900">{formatPrice(result.scenario_price)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Scenario market cap</div>
              <div className="font-semibold text-gray-900">
                {formatCompact(result.scenario_market_cap)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">Current observed cap</div>
              <div className="font-semibold text-gray-900">
                {formatCompact(result.reference_market_cap)}
              </div>
            </div>
          </div>
          <p className="text-[11px] text-amber-800 mt-2">{result.note}</p>
        </div>
      )}
    </BaseCard>
  );
};

export default ScenarioCalculator;
