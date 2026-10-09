/**
 * Phase 23A — Central Bank and Macroeconomic Intelligence Page
 *
 * Main dashboard for central bank meetings, policy decisions, and macro data.
 * Every panel is driven by real sources: official central-bank calendars,
 * FRED economic series, and live prediction-market expectations. Nothing is
 * fabricated — a missing source shows an explicit unavailable state.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CentralBankOverview,
  PolicyDecisionCard,
  RateHistoryChart,
  MacroIndicatorCard,
  MacroSeriesExplorer,
  UpcomingMeetings,
  ExpectationCard,
} from '../components/macro';
import type { MacroIndicator, ExpectationSnapshot } from '../components/macro';
import type { PolicyRateRange } from '../components/macro/CentralBankOverview';
import BaseCard from '../components/BaseCard';
import { CardSkeleton } from '../components/LoadingSkeleton';

interface CentralBank {
  id: string;
  name: string;
  country: string;
  currency: string;
  timezone: string;
  source: string;
}

interface PolicyMeeting {
  id: number;
  central_bank_id: string;
  scheduled_at: string;
  timezone: string;
  status: string;
  meeting_type: string;
  countdown: {
    days: number;
    hours: number;
    minutes: number;
    seconds: number;
    total_seconds: number;
    is_past: boolean;
  };
  current_policy_rate?: number;
  previous_decision?: string;
  source_url?: string;
}

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

interface PolicyAnalytics {
  total_decisions: number;
  hikes: number;
  cuts: number;
  unchanged: number;
  avg_hike_bps: number;
  avg_cut_bps: number;
  max_hike_bps: number;
  max_cut_bps: number;
  current_rate?: number;
  rate_range_min?: number;
  rate_range_max?: number;
  total_bps_change: number;
  volatility_bps: number | null;
}

// ---- Phase 23A additions: sourced expectations + event-window analysis ----

// ExpectationSnapshot is defined by the ExpectationCard component (§18) and
// imported above, so the page and the card consume one identical contract.

interface ExpectationsResponse {
  central_bank_id: string;
  snapshots: ExpectationSnapshot[];
  count: number;
  status: 'LIVE' | 'UNAVAILABLE';
  expectation_source: string[] | null;
  statement: string;
  note: string;
}

interface EventWindowRow {
  decision_timestamp: string;
  direction: string;
  change_bps: number;
  previous_rate: number;
  new_rate: number;
  source_document: string | null;
  market_ticker: string;
  pre_event_avg: number | null;
  post_event_avg: number | null;
  change_1d: number | null;
  change_3d: number | null;
  change_5d: number | null;
  change_10d: number | null;
  change_20d: number | null;
  pre_volatility: number | null;
  post_volatility: number | null;
}

interface EventWindowResponse {
  central_bank_id: string;
  ticker: string;
  windows: number[];
  results: EventWindowRow[];
  count: number;
  status: 'LIVE' | 'UNAVAILABLE';
  market_source: string | null;
  market_status?: string | null;
  history_start?: string;
  history_end?: string;
  note?: string;
  reason?: string;
}

const fmtPct = (value: number | null | undefined): string =>
  value == null || !Number.isFinite(value) ? 'N/A' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const MacroIntelligencePage: React.FC = () => {
  const [selectedBank, setSelectedBank] = useState<string>('FED');
  const [banks, setBanks] = useState<CentralBank[]>([]);
  const [meetings, setMeetings] = useState<PolicyMeeting[]>([]);
  const [decisions, setDecisions] = useState<PolicyDecision[]>([]);
  const [analytics, setAnalytics] = useState<PolicyAnalytics | null>(null);
  const [policyRange, setPolicyRange] = useState<PolicyRateRange | null>(null);
  const [indicators, setIndicators] = useState<MacroIndicator[]>([]);
  const [expectations, setExpectations] = useState<ExpectationsResponse | null>(null);
  const [eventWindow, setEventWindow] = useState<EventWindowResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBanks = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/macro/central-banks`);
      if (!response.ok) throw new Error('Failed to fetch central banks');
      setBanks(await response.json());
    } catch (err) {
      console.error('Error fetching banks:', err);
      setError('Failed to load central banks');
    }
  }, []);

  const loadBank = useCallback(async (bankId: string) => {
    setLoading(true);
    setError(null);
    try {
      const [meetingsRes, decisionsRes, analyticsRes, rangeRes, indicatorsRes] =
        await Promise.all([
          fetch(`${API_BASE}/api/v1/macro/meetings/${bankId}?limit=10`),
          fetch(`${API_BASE}/api/v1/macro/policy/${bankId}?limit=50`),
          fetch(`${API_BASE}/api/v1/macro/analytics/policy/${bankId}`),
          fetch(`${API_BASE}/api/v1/macro/policy-range/${bankId}`),
          fetch(`${API_BASE}/api/v1/macro/indicators`),
        ]);

      if (meetingsRes.ok) setMeetings(await meetingsRes.json());
      if (decisionsRes.ok) setDecisions(await decisionsRes.json());
      if (analyticsRes.ok) setAnalytics(await analyticsRes.json());
      if (rangeRes.ok) setPolicyRange(await rangeRes.json());
      if (indicatorsRes.ok) {
        const body = await indicatorsRes.json();
        setIndicators(body.indicators ?? []);
      }

      // Sourced expectation snapshots + event-window analysis. Both endpoints
      // may legitimately report UNAVAILABLE (no reachable market / no stored
      // decisions), so a missing panel is an honest state, not a failure.
      setExpectations(null);
      setEventWindow(null);
      try {
        const expectationsRes = await fetch(
          `${API_BASE}/api/v1/macro/expectations/${bankId}?limit=50`
        );
        if (expectationsRes.ok) setExpectations(await expectationsRes.json());
      } catch {
        console.error('Error fetching expectations');
      }
      try {
        const eventWindowRes = await fetch(
          `${API_BASE}/api/v1/macro/event-window/${bankId}?ticker=%5EGSPC&lookback_decisions=4`
        );
        if (eventWindowRes.ok) setEventWindow(await eventWindowRes.json());
      } catch {
        console.error('Error fetching event-window analysis');
      }
    } catch (err) {
      console.error('Error fetching bank data:', err);
      setError('Failed to load bank data');
    } finally {
      setLoading(false);
    }
  }, []);

  /** Pull fresh data from the official/real sources, then reload the panels. */
  const refreshFromSources = useCallback(
    async (bankId: string) => {
      setRefreshing(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE}/api/v1/macro/refresh/${bankId}`, {
          method: 'POST',
        });
        if (!response.ok) throw new Error(`Refresh failed (${response.status})`);
        await loadBank(bankId);
      } catch (err) {
        console.error('Error refreshing macro data:', err);
        setError(
          'Could not refresh from the upstream sources — showing the last stored data.'
        );
      } finally {
        setRefreshing(false);
      }
    },
    [loadBank]
  );

  useEffect(() => {
    fetchBanks();
  }, [fetchBanks]);

  useEffect(() => {
    if (selectedBank) loadBank(selectedBank);
  }, [selectedBank, loadBank]);

  // First run on a fresh database: pull real data from the official sources
  // once so the page is populated without a manual click. Attempted at most
  // once per bank — a failed refresh must not retry in a loop.
  const autoBootstrapRef = useRef<Set<string>>(new Set());
  const hasNoData = !loading && meetings.length === 0 && decisions.length === 0;
  useEffect(() => {
    if (!hasNoData || autoBootstrapRef.current.has(selectedBank)) return;
    autoBootstrapRef.current.add(selectedBank);
    refreshFromSources(selectedBank);
  }, [hasNoData, selectedBank, refreshFromSources]);

  const selectedBankInfo = useMemo(
    () => banks.find((bank) => bank.id === selectedBank),
    [banks, selectedBank]
  );

  // Newest sourced expectation per meeting, surfaced on the meeting card (§6).
  const impliedByMeeting = useMemo(() => {
    const map = new Map<number, ExpectationSnapshot>();
    if (expectations?.status === 'LIVE') {
      for (const snapshot of expectations.snapshots) {
        if (!map.has(snapshot.meeting_id)) map.set(snapshot.meeting_id, snapshot);
      }
    }
    return map;
  }, [expectations]);

  if (loading && banks.length === 0) {
    return (
      <div className="p-6">
        <CardSkeleton />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Central Bank &amp; Macroeconomic Intelligence
          </h1>
          <p className="text-gray-600">
            Real-time policy meeting schedules, rate decisions, and macroeconomic data from official sources.
          </p>
        </div>
        <button
          onClick={() => refreshFromSources(selectedBank)}
          disabled={refreshing}
          className="px-4 py-2 rounded-lg font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {refreshing ? 'Refreshing from sources…' : 'Refresh from official sources'}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 text-red-800 rounded">{error}</div>
      )}

      {/* Bank Selector */}
      <div className="mb-6 flex gap-2 flex-wrap">
        {banks.map((bank) => (
          <button
            key={bank.id}
            onClick={() => setSelectedBank(bank.id)}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              selectedBank === bank.id
                ? 'bg-blue-600 text-white'
                : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
            }`}
          >
            {bank.name}
          </button>
        ))}
      </div>

      {selectedBankInfo && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          <CentralBankOverview
            bank={selectedBankInfo}
            currentRate={analytics?.current_rate}
            previousDecision={decisions[0]?.direction}
            nextMeeting={meetings[0]}
            rateRange={policyRange}
            onRefresh={() => refreshFromSources(selectedBank)}
          />
        </div>
      )}

      {/* Policy Analytics */}
      {analytics && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <BaseCard className="p-4">
            <p className="text-xs text-gray-500 uppercase">Total Decisions</p>
            <p className="text-2xl font-bold text-gray-900">{analytics.total_decisions}</p>
          </BaseCard>
          <BaseCard className="p-4">
            <p className="text-xs text-gray-500 uppercase">Hikes</p>
            <p className="text-2xl font-bold text-red-600">{analytics.hikes}</p>
          </BaseCard>
          <BaseCard className="p-4">
            <p className="text-xs text-gray-500 uppercase">Cuts</p>
            <p className="text-2xl font-bold text-green-600">{analytics.cuts}</p>
          </BaseCard>
          <BaseCard className="p-4">
            <p className="text-xs text-gray-500 uppercase">Volatility (bps)</p>
            <p className="text-2xl font-bold text-gray-900">
              {analytics.volatility_bps != null ? analytics.volatility_bps.toFixed(1) : 'N/A'}
            </p>
          </BaseCard>
        </div>
      )}

      {/* Upcoming Meetings (§8, §9, §18) */}
      <UpcomingMeetings
        meetings={meetings}
        bankName={selectedBankInfo?.name}
        impliedByMeeting={impliedByMeeting}
        loading={loading}
      />

      {/* Rate History Chart */}
      {decisions.length > 0 && (
        <div className="mb-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Policy Rate History</h2>
          <RateHistoryChart decisions={decisions} />
        </div>
      )}

      {/* Recent Decisions */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Recent Decisions</h2>
        {loading ? (
          <CardSkeleton />
        ) : decisions.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {decisions.slice(0, 12).map((decision) => (
              <PolicyDecisionCard key={decision.id} decision={decision} />
            ))}
          </div>
        ) : (
          <BaseCard className="p-6">
            <p className="text-center text-gray-500">No decision history available</p>
          </BaseCard>
        )}
      </div>

      {/* Key Macro Indicators (real FRED series) */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Key Macro Indicators</h2>
        {indicators.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {indicators.map((indicator) => (
              <MacroIndicatorCard key={indicator.series_id} indicator={indicator} />
            ))}
          </div>
        ) : (
          <BaseCard className="p-6">
            <p className="text-center text-gray-500">
              No macro indicators loaded yet — use “Refresh from official sources”.
            </p>
          </BaseCard>
        )}
      </div>

      {/* Macro Series Explorer (§10) — every curated FRED series, real data */}
      <MacroSeriesExplorer />

      {/* Policy Expectations (Phase 23A §7) — sourced snapshots only */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Market-Implied Policy Expectations</h2>
        {expectations && expectations.status === 'LIVE' && expectations.snapshots.length > 0 ? (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {expectations.snapshots.slice(0, 6).map((snap) => (
                <ExpectationCard key={snap.id} snapshot={snap} />
              ))}
            </div>
            {expectations.note && <p className="text-xs text-gray-500 mt-3">{expectations.note}</p>}
          </div>
        ) : (
          <BaseCard className="p-6">
            <p className="text-center font-semibold text-gray-700">
              {expectations?.statement ?? 'Market-implied expectations unavailable.'}
            </p>
            {expectations?.note && (
              <p className="text-center text-xs text-gray-500 mt-2">{expectations.note}</p>
            )}
          </BaseCard>
        )}
      </div>

      {/* Event-Window Analysis (Phase 23A §10) — historical observation only */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Event-Window Analysis</h2>
        {eventWindow && eventWindow.status === 'LIVE' && eventWindow.results.length > 0 ? (
          <BaseCard className="p-4">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 uppercase">
                    <th className="py-2 pr-4">Decision</th>
                    <th className="py-2 pr-4">Direction</th>
                    <th className="py-2 pr-4">Δbps</th>
                    <th className="py-2 pr-4">1D</th>
                    <th className="py-2 pr-4">3D</th>
                    <th className="py-2 pr-4">5D</th>
                    <th className="py-2 pr-4">10D</th>
                    <th className="py-2 pr-4">20D</th>
                  </tr>
                </thead>
                <tbody>
                  {eventWindow.results.map((row) => (
                    <tr key={row.decision_timestamp} className="border-t border-gray-100">
                      <td className="py-2 pr-4 text-gray-900">
                        {new Date(row.decision_timestamp).toLocaleDateString()}
                      </td>
                      <td className="py-2 pr-4">{row.direction}</td>
                      <td className="py-2 pr-4">{row.change_bps}</td>
                      <td className="py-2 pr-4">{fmtPct(row.change_1d)}</td>
                      <td className="py-2 pr-4">{fmtPct(row.change_3d)}</td>
                      <td className="py-2 pr-4">{fmtPct(row.change_5d)}</td>
                      <td className="py-2 pr-4">{fmtPct(row.change_10d)}</td>
                      <td className="py-2 pr-4">{fmtPct(row.change_20d)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-500 mt-3">
              {eventWindow.note} Market leg: {eventWindow.market_source ?? 'N/A'}
              {' '}({eventWindow.market_status ?? 'N/A'}) · {eventWindow.ticker}
              {eventWindow.history_start && eventWindow.history_end
                ? ` · history ${eventWindow.history_start} → ${eventWindow.history_end}`
                : ''}
            </p>
          </BaseCard>
        ) : (
          <BaseCard className="p-6">
            <p className="text-center text-gray-500">
              {eventWindow?.reason ?? 'Event-window analysis unavailable.'}
            </p>
          </BaseCard>
        )}
      </div>

      {/* Disclaimer */}
      <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded">
        <p className="text-sm text-yellow-800">
          <strong>Disclaimer:</strong> This data is sourced from official central bank publications,
          FRED economic series, and public prediction markets. All rate changes are calculated from
          actual decisions (bps = (new_rate − previous_rate) × 100). Market-implied expectations are
          what a named source traded at a named timestamp and are not the central bank’s decision.
          For informational purposes only; not investment advice.
        </p>
      </div>
    </div>
  );
};

export default MacroIntelligencePage;
