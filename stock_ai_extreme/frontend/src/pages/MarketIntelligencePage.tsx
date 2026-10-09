/**
 * Phase 23B — Market Direction & Corporate Market-Cap Intelligence page.
 *
 * Everything on this page is driven by real provider data: SPX index and SPY
 * ETF sessions come from the shared market-data stack, and the market-cap
 * leaderboard is computed from live company observations. Nothing is hardcoded
 * — a missing source renders an explicit unavailable state, and every figure
 * carries its observation period, sample size and source.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import BaseCard from '../components/BaseCard';
import BaseBadge from '../components/BaseBadge';
import { CardSkeleton } from '../components/LoadingSkeleton';
import {
  InstrumentCard,
  DirectionCharts,
  SpxSpyComparison,
  MarketCapLeaderboard,
  ScenarioCalculator,
  MarketCapRace,
  CompanyCapHistory,
  RankTimeline,
  marketIntelGet,
} from '../components/market-intel';
import type {
  InstrumentInfo,
  LatestSession,
  SeriesPoint,
  RollingPoint,
  AlignedPoint,
  CompanyRow,
  CompanyOption,
  RaceRow,
  RankSeries,
} from '../components/market-intel';

interface DirectionStatistics {
  instrument: string;
  symbol: string;
  instrument_kind: string;
  period_start: string | null;
  period_end: string | null;
  sample_size: number;
  up_days: number;
  down_days: number;
  flat_days: number;
  up_frequency: number | null;
  down_frequency: number | null;
  flat_frequency: number | null;
  avg_up_return_pct: number | null;
  avg_down_return_pct: number | null;
  max_gain_pct: number | null;
  max_decline_pct: number | null;
  total_return_pct: number | null;
}

interface DashboardCard {
  instrument: InstrumentInfo;
  latest: LatestSession | null;
  statistics: DirectionStatistics;
  source: string | null;
  data_status: string | null;
  error: string | null;
  fetch_timestamp: string | null;
}

interface DashboardResponse {
  cards: DashboardCard[];
  note: string;
}

interface HistoryResponse {
  instrument: InstrumentInfo;
  source: string | null;
  data_status: string | null;
  series: SeriesPoint[];
  latest: LatestSession | null;
  error: string | null;
}

interface RollingResponse {
  points: RollingPoint[];
  window: number;
  error: string | null;
}

interface ComparisonResponse {
  aligned: AlignedPoint[];
  spx_source: string | null;
  spy_source: string | null;
  note: string;
}

interface LeaderboardResponse {
  companies: CompanyRow[];
  generated_at: string;
  note: string;
}

interface EventStudyResponse {
  bank_id: string;
  instrument?: InstrumentInfo;
  status: string | null;
  reason: string | null;
  results: Array<Record<string, number | string | null>>;
  windows?: number[];
  market_source: string | null;
  market_status: string | null;
  note: string;
}

interface RaceResponse {
  rows: RaceRow[];
  note: string;
  period_days: number;
  observation_start: string | null;
}

const fmtPct = (value: number | null | undefined): string =>
  value === null || value === undefined ? 'N/A' : `${value.toFixed(2)}%`;

const StatCell: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="border border-gray-100 rounded p-2">
    <div className="text-[11px] text-gray-500">{label}</div>
    <div className="text-sm font-semibold text-gray-900">{value}</div>
  </div>
);

const MarketIntelligencePage: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [activeKey, setActiveKey] = useState<'spx' | 'spy'>('spx');
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [rolling, setRolling] = useState<RollingResponse | null>(null);
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardResponse | null>(null);
  const [race, setRace] = useState<RaceResponse | null>(null);
  const [raceDays, setRaceDays] = useState(365);
  const [rankHistory, setRankHistory] = useState<RankSeries[]>([]);
  const [eventStudy, setEventStudy] = useState<EventStudyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [studyLoading, setStudyLoading] = useState(true);

  const loadCore = useCallback(async () => {
    // The leaderboard refresh records an observation first, then the race reads
    // the stored rank history — sequential so the race sees this refresh.
    const [dash, comp, board] = await Promise.allSettled([
      marketIntelGet<DashboardResponse>('/api/v1/market-intel/dashboard?days=400'),
      marketIntelGet<ComparisonResponse>('/api/v1/market-intel/comparison?days=400'),
      marketIntelGet<LeaderboardResponse>('/api/v1/market-intel/leaderboard?limit=50'),
    ]);
    if (dash.status === 'fulfilled') setDashboard(dash.value);
    if (comp.status === 'fulfilled') setComparison(comp.value);
    if (board.status === 'fulfilled') setLeaderboard(board.value);
  }, []);

  // §12/§14 — the race honours the selected period and the rank timeline reads
  // the same stored snapshots, so both reload together when the period changes.
  const loadRace = useCallback(async (days: number) => {
    const [raceResult, rankResult] = await Promise.allSettled([
      marketIntelGet<RaceResponse>(`/api/v1/market-intel/race?period_days=${days}`),
      marketIntelGet<{ series: RankSeries[] }>('/api/v1/market-intel/rank-history?limit=2000'),
    ]);
    if (raceResult.status === 'fulfilled') setRace(raceResult.value);
    if (rankResult.status === 'fulfilled') setRankHistory(rankResult.value.series);
  }, []);

  useEffect(() => {
    void loadRace(raceDays);
  }, [raceDays, loadRace]);

  const loadInstrument = useCallback(async (key: 'spx' | 'spy') => {
    const [hist, roll] = await Promise.allSettled([
      marketIntelGet<HistoryResponse>(`/api/v1/market-intel/${key}/history?days=400`),
      marketIntelGet<RollingResponse>(`/api/v1/market-intel/${key}/rolling?days=400&window=20`),
    ]);
    if (hist.status === 'fulfilled') setHistory(hist.value);
    if (roll.status === 'fulfilled') setRolling(roll.value);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setStudyLoading(true);
      // The event study reuses the macro engine and fetches a long market
      // history, so it runs in parallel with the core panels instead of after
      // them. A loading state prevents the section showing "unavailable" while
      // the request is still in flight.
      const studyPromise = marketIntelGet<EventStudyResponse>(
        `/api/v1/market-intel/events/FED?instrument=${activeKey}&lookback_decisions=6`,
      ).catch(() => null);
      await Promise.all([loadCore(), loadInstrument(activeKey)]);
      const study = await studyPromise;
      if (cancelled) return;
      if (study) setEventStudy(study);
      setStudyLoading(false);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadCore, loadInstrument, activeKey]);

  const activeStats = useMemo<DirectionStatistics | null>(() => {
    const card = dashboard?.cards.find((entry) => entry.instrument.key === activeKey);
    return card?.statistics ?? null;
  }, [dashboard, activeKey]);

  const companyOptions: CompanyOption[] = useMemo(
    () =>
      (leaderboard?.companies ?? []).map((company) => ({
        company_id: company.company_id,
        name: company.name,
        ticker: company.ticker,
      })),
    [leaderboard],
  );

  // §7 — the event study returns whichever observation windows the backend
  // computed; render exactly those, so no column is invented or dropped.
  const studyWindows = eventStudy?.windows ?? [1, 3, 5, 10, 20];

  const unavailable = (label: string) => (
    <BaseCard className="p-6">
      <p className="text-center text-gray-500">{label}</p>
    </BaseCard>
  );

  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          Market Direction &amp; Market-Cap Intelligence
        </h1>
        <p className="text-sm text-gray-600 mt-1">
          SPX index and SPY ETF direction analytics from real trading sessions, plus a dynamic
          corporate market-cap ranking computed from live observations. Values are the latest
          available session closes — not live intraday quotes.
        </p>
      </div>

      {/* §5 — separate SPX and SPY cards */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Index &amp; ETF</h2>
        {loading && !dashboard ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <CardSkeleton />
            <CardSkeleton />
          </div>
        ) : dashboard ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {dashboard.cards.map((card) => (
              <InstrumentCard
                key={card.instrument.key}
                info={card.instrument}
                latest={card.latest}
                source={card.source}
                status={card.data_status}
                error={card.error}
              />
            ))}
          </div>
        ) : (
          unavailable('Instrument data unavailable.')
        )}
        {dashboard?.note && <p className="text-xs text-gray-500 mt-2">{dashboard.note}</p>}
      </div>

      {/* §4 — historical statistics with period + sample size */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-3">
          <h2 className="text-lg font-bold text-gray-900">Historical direction analytics</h2>
          <div className="flex gap-1">
            {(['spx', 'spy'] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setActiveKey(key)}
                className={`px-3 py-1 rounded text-xs font-medium border ${
                  activeKey === key
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
              >
                {key.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {activeStats && activeStats.period_start ? (
          <BaseCard className="p-4">
            <p className="text-xs text-gray-500 mb-3">
              Observation period {activeStats.period_start} → {activeStats.period_end} · sample size{' '}
              {activeStats.sample_size} sessions
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
              <StatCell label="Up days" value={String(activeStats.up_days)} />
              <StatCell label="Down days" value={String(activeStats.down_days)} />
              <StatCell label="Flat days" value={String(activeStats.flat_days)} />
              <StatCell label="Up frequency" value={fmtPct((activeStats.up_frequency ?? 0) * 100)} />
              <StatCell
                label="Down frequency"
                value={fmtPct((activeStats.down_frequency ?? 0) * 100)}
              />
              <StatCell label="Avg up return" value={fmtPct(activeStats.avg_up_return_pct)} />
              <StatCell label="Avg down return" value={fmtPct(activeStats.avg_down_return_pct)} />
              <StatCell label="Max gain" value={fmtPct(activeStats.max_gain_pct)} />
              <StatCell label="Max decline" value={fmtPct(activeStats.max_decline_pct)} />
              <StatCell label="Period return" value={fmtPct(activeStats.total_return_pct)} />
            </div>
          </BaseCard>
        ) : (
          unavailable('Statistics unavailable for the selected instrument.')
        )}
      </div>

      {/* §6 — charts */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">
          {activeKey.toUpperCase()} history &amp; rolling analytics
        </h2>
        {history && history.series.length > 0 ? (
          <DirectionCharts
            series={history.series}
            rolling={rolling?.points ?? []}
            window={rolling?.window ?? 20}
          />
        ) : (
          unavailable('No historical series available.')
        )}
        {history?.error && <p className="text-xs text-red-500 mt-2">{history.error}</p>}
        {history?.source && (
          <p className="text-xs text-gray-500 mt-2">
            Source: <span className="font-medium">{history.source}</span> · status{' '}
            <span className="font-medium">{history.data_status}</span>
          </p>
        )}
      </div>

      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">SPX vs SPY comparison</h2>
        {comparison && comparison.aligned.length > 0 ? (
          <SpxSpyComparison
            aligned={comparison.aligned}
            spxSource={comparison.spx_source}
            spySource={comparison.spy_source}
            note={comparison.note}
          />
        ) : (
          unavailable('Comparison unavailable.')
        )}
      </div>

      {/* §11 — dynamic market-cap leaderboard */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Corporate market-cap leaderboard</h2>
        {leaderboard && leaderboard.companies.length > 0 ? (
          <MarketCapLeaderboard
            companies={leaderboard.companies}
            generatedAt={leaderboard.generated_at}
            note={leaderboard.note}
          />
        ) : (
          unavailable('Leaderboard unavailable.')
        )}
      </div>

      {/* §12 — descriptive market-cap race (no forecasts) */}
      <div className="mb-6">
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <h2 className="text-lg font-bold text-gray-900">Market-cap race</h2>
          <label className="text-xs text-gray-600">
            Comparison period
            <select
              className="ml-2 border border-gray-300 rounded px-2 py-1 text-sm text-gray-900"
              value={raceDays}
              onChange={(event) => setRaceDays(Number(event.target.value))}
            >
              {[30, 90, 180, 365, 730].map((days) => (
                <option key={days} value={days}>
                  Last {days} days
                </option>
              ))}
            </select>
          </label>
        </div>
        {race && race.rows.length > 0 ? (
          <MarketCapRace
            rows={race.rows}
            note={race.note}
            periodDays={race.period_days}
            observationStart={race.observation_start}
          />
        ) : (
          unavailable('Market-cap race unavailable.')
        )}
      </div>

      {/* §14 — cross-company ranking timeline from stored rank snapshots */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Ranking timeline</h2>
        {rankHistory.length > 0 ? (
          <RankTimeline series={rankHistory} />
        ) : (
          unavailable('Rank history unavailable.')
        )}
      </div>

      {/* §14 — per-company stored market-cap history */}
      <div className="mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Company market-cap history</h2>
        {companyOptions.length > 0 ? (
          <CompanyCapHistory companies={companyOptions} />
        ) : (
          unavailable('Company history unavailable.')
        )}
      </div>

      {/* §13 — hypothetical scenario calculator */}
      <div className="mb-6">
        <ScenarioCalculator companies={companyOptions} />
      </div>

      {/* §7 — policy event study (observational) */}
      <div className="mb-6">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h2 className="text-lg font-bold text-gray-900">
            Central-bank event study — {activeKey.toUpperCase()}
          </h2>
          <BaseBadge variant="info" size="sm">
            OBSERVATIONAL
          </BaseBadge>
          <div className="flex gap-1 ml-2">
            {(['spx', 'spy'] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setActiveKey(key)}
                className={`px-2 py-0.5 rounded text-xs font-medium border ${
                  activeKey === key
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300'
                }`}
              >
                {key.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-gray-500 mb-2">
          SPX uses the index level (^GSPC); SPY uses the ETF. The two are never
          substituted for one another.
        </p>
        {studyLoading && !eventStudy ? (
          <BaseCard className="p-6">
            <p className="text-center text-gray-500">Loading event study…</p>
          </BaseCard>
        ) : eventStudy && eventStudy.results.length > 0 ? (
          <BaseCard className="p-4">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 uppercase">
                    <th className="py-2 pr-4">Decision</th>
                    <th className="py-2 pr-4">Direction</th>
                    <th className="py-2 pr-4">Δbps</th>
                    {studyWindows.map((window) => (
                      <th key={window} className="py-2 pr-4">
                        {window}D
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {eventStudy.results.map((row) => (
                    <tr key={String(row.decision_timestamp)} className="border-t border-gray-100">
                      <td className="py-2 pr-4 text-gray-900">
                        {datestring(row.decision_timestamp)}
                        {row.decision_session && (
                          <span className="block text-[10px] text-gray-500">
                            session {String(row.decision_session)}
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-4">{String(row.direction ?? '—')}</td>
                      <td className="py-2 pr-4">{String(row.change_bps ?? '—')}</td>
                      {studyWindows.map((window) => (
                        <td key={window} className="py-2 pr-4">
                          {pctCell(row[`change_${window}d`])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-500 mt-3">
              {eventStudy.note} Market leg: {eventStudy.market_source ?? 'N/A'} (
              {eventStudy.market_status ?? 'N/A'}).
            </p>
          </BaseCard>
        ) : (
          unavailable(eventStudy?.reason ?? 'Event study unavailable.')
        )}
      </div>

      <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded">
        <p className="text-sm text-yellow-800">
          <strong>Disclaimer:</strong> Index and ETF values are real provider closes for the latest
          available trading session. Market capitalisations are either reported by the provider or
          computed as price × shares outstanding and labelled accordingly. Rankings are computed
          from stored observations, not hardcoded. Hypothetical scenarios are arithmetic under an
          assumption and are not predictions. For informational purposes only; not investment
          advice.
        </p>
      </div>
    </div>
  );
};

function datestring(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString();
}

function pctCell(value: number | string | null | undefined): string {
  // Event-window changes are already expressed in percent by the backend.
  if (value === null || value === undefined) return '—';
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`;
}

export default MarketIntelligencePage;
