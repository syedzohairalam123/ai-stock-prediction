/**
 * Phase 23A — Central Bank and Macroeconomic Intelligence Page
 *
 * Main dashboard for central bank meetings, policy decisions, and macro data.
 * Integrates all macro components with real-time data fetching.
 */
import React, { useState, useEffect } from 'react';
import {
  CentralBankOverview,
  PolicyMeetingCard,
  PolicyDecisionCard,
  RateHistoryChart,
  MacroSeriesCard,
} from '../components/macro';
import BaseCard from '../components/BaseCard';
import BaseBadge from '../components/BaseBadge';
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

interface MacroSeries {
  id: number;
  series_id: string;
  observation_date: string;
  release_date: string;
  value: number;
  unit: string;
  frequency: string;
  source: string;
  data_freshness: string;
  revision: number;
  previous_value?: number;
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

export const MacroIntelligencePage: React.FC = () => {
  const [selectedBank, setSelectedBank] = useState<string>('FED');
  const [banks, setBanks] = useState<CentralBank[]>([]);
  const [meetings, setMeetings] = useState<PolicyMeeting[]>([]);
  const [decisions, setDecisions] = useState<PolicyDecision[]>([]);
  const [macroSeries, setMacroSeries] = useState<MacroSeries[]>([]);
  const [analytics, setAnalytics] = useState<PolicyAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchBanks();
  }, []);

  useEffect(() => {
    if (selectedBank) {
      fetchBankData(selectedBank);
    }
  }, [selectedBank]);

  const fetchBanks = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/macro/central-banks`);
      if (!response.ok) throw new Error('Failed to fetch central banks');
      const data = await response.json();
      setBanks(data);
    } catch (err) {
      console.error('Error fetching banks:', err);
      setError('Failed to load central banks');
    }
  };

  const fetchBankData = async (bankId: string) => {
    setLoading(true);
    setError(null);

    try {
      // Fetch meetings
      const meetingsResponse = await fetch(
        `${API_BASE}/api/v1/macro/meetings/${bankId}?limit=10`
      );
      const meetingsData = await meetingsResponse.json();
      setMeetings(meetingsData);

      // Fetch decisions
      const decisionsResponse = await fetch(
        `${API_BASE}/api/v1/macro/policy/${bankId}?limit=50`
      );
      const decisionsData = await decisionsResponse.json();
      setDecisions(decisionsData);

      // Fetch analytics
      const analyticsResponse = await fetch(
        `${API_BASE}/api/v1/macro/analytics/policy/${bankId}`
      );
      const analyticsData = await analyticsResponse.json();
      setAnalytics(analyticsData);

      // Fetch some key macro series (example: Fed Funds Rate)
      if (bankId === 'FED') {
        const seriesResponse = await fetch(
          `${API_BASE}/api/v1/macro/series/DFF?limit=10`
        );
        const seriesData = await seriesResponse.json();
        setMacroSeries(seriesData);
      }
    } catch (err) {
      console.error('Error fetching bank data:', err);
      setError('Failed to load bank data');
    } finally {
      setLoading(false);
    }
  };

  const refreshData = () => {
    fetchBankData(selectedBank);
  };

  const selectedBankInfo = banks.find((b) => b.id === selectedBank);

  if (loading && banks.length === 0) {
    return (
      <div className="p-6">
        <CardSkeleton />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Central Bank & Macroeconomic Intelligence
        </h1>
        <p className="text-gray-600">
          Real-time policy meeting schedules, rate decisions, and macroeconomic data from official sources.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 text-red-800 rounded">
          {error}
        </div>
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
            onRefresh={refreshData}
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

      {/* Upcoming Meetings */}
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Upcoming Meetings</h2>
        {loading ? (
          <CardSkeleton />
        ) : meetings.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {meetings.map((meeting) => (
              <PolicyMeetingCard
                key={meeting.id}
                meeting={meeting}
                bankName={selectedBankInfo?.name}
              />
            ))}
          </div>
        ) : (
          <BaseCard className="p-6">
            <p className="text-center text-gray-500">No upcoming meetings scheduled</p>
          </BaseCard>
        )}
      </div>

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

      {/* Macro Series */}
      {macroSeries.length > 0 && (
        <div className="mb-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Key Macro Indicators</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {macroSeries.slice(0, 8).map((series) => (
              <MacroSeriesCard key={series.id} series={series} />
            ))}
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded">
        <p className="text-sm text-yellow-800">
          <strong>Disclaimer:</strong> This data is sourced from official central bank publications
          and licensed economic data providers. All rate changes are calculated from actual decisions
          (bps = (new_rate - previous_rate) × 100). Market expectations are sourced from legitimate
          providers and clearly labeled as SOURCE-DERIVED EXPECTATION. This is for informational
          purposes only and not investment advice.
        </p>
      </div>
    </div>
  );
};

export default MacroIntelligencePage;
