/**
 * Derivatives Terminal Page for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine
 * 
 * This is the main derivatives trading terminal interface for educational analytics and paper simulation.
 * No real-money execution is supported.
 */

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

const configuredApiUrl = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '');
const API_BASE = /\/api$/i.test(configuredApiUrl) ? configuredApiUrl.slice(0, -4) : configuredApiUrl;

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

// Types
interface DerivativeInstrument {
  id: string;
  symbol: string;
  display_name: string;
  asset_class: string;
  underlying: string;
  quote_currency: string;
  exchange: string;
  status: string;
  contract_type: string;
  tick_size: number;
  lot_size: number;
  price_precision: number;
  quantity_precision: number;
}

interface DerivativeQuote {
  instrument_id: string;
  timestamp: string;
  last_price: number;
  source: string;
  status: string;
  bid?: number;
  ask?: number;
  spread?: number;
  mark_price?: number;
  index_price?: number;
  change_24h?: number;
  change_percent_24h?: number;
  high_24h?: number;
  low_24h?: number;
  volume_24h?: number;
  open_interest?: number;
  funding_rate?: number;
  data_mode?: string;
}

interface DepthLevel { price: number; quantity: number; cumulative_quantity?: number; }
interface MarketDepth { bids: DepthLevel[]; asks: DepthLevel[]; source: string; data_mode?: string; status?: string; timestamp: string; }
interface FundingData { current_funding_rate?: number; predicted_funding_rate?: number; next_funding_time?: string; last_funding_rate?: number; funding_interval_hours?: number; historical_rates: Array<{ timestamp?: string; funding_rate?: number }>; source: string; data_mode?: string; status?: string; }
interface OpenInterestData { current_open_interest?: number; open_interest_value?: number; open_interest_change_24h?: number; open_interest_change_percent_24h?: number; historical_oi: Array<{ timestamp?: string; open_interest?: number }>; source: string; data_mode?: string; status?: string; }
interface AdvancedAnalytics { volatility?: number; returns_mean?: number; returns_std?: number; rolling_volatility_7d?: number; rolling_volatility_30d?: number; moving_average_7d?: number; moving_average_30d?: number; max_drawdown?: number; sharpe_ratio?: number; sortino_ratio?: number; z_score?: number; volume_anomaly_score?: number; price_momentum?: number; rsi?: number; bollinger_upper?: number; bollinger_lower?: number; bollinger_middle?: number; }
interface RiskMetrics { historical_volatility?: number; max_historical_drawdown?: number; recent_price_range?: number; value_at_risk_95?: number; expected_shortfall_95?: number; data_quality_score?: number; liquidity_indicator?: number; market_stress_indicator?: number; correlation_benchmark?: number; beta?: number; disclaimer?: string; }
interface Simulation { id?: string; instrument_id: string; scenario_name: string; direction: 'LONG' | 'SHORT'; entry_price: number; exit_price?: number; quantity: number; leverage: number; gross_pnl?: number; gross_pnl_percent?: number; status: string; }

interface MarketMicrostructure {
  instrument_id: string;
  timestamp: string;
  bid_ask_spread?: number;
  mid_price?: number;
  spread_percent?: number;
  bid_depth?: number;
  ask_depth?: number;
  depth_imbalance?: number;
  liquidity_score?: number;
}

type AssetClass = 'STOCKS' | 'CRYPTO' | 'INDICES' | 'COMMODITIES';

export default function DerivativesTerminalPage() {
  const [selectedAssetClass, setSelectedAssetClass] = useState<AssetClass>('CRYPTO');
  const [selectedInstrument, setSelectedInstrument] = useState<DerivativeInstrument | null>(null);
  const [activeTab, setActiveTab] = useState<'quote' | 'depth' | 'funding' | 'oi' | 'analytics' | 'risk' | 'simulation'>('quote');

  // Fetch instruments
  const { data: instrumentsData, isLoading: instrumentsLoading } = useQuery({
    queryKey: ['derivatives-instruments', selectedAssetClass],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/api/derivatives/instruments?asset_class=${selectedAssetClass}`);
      if (!response.ok) throw new Error('Failed to fetch instruments');
      return response.json();
    },
  });

  // Fetch quote for selected instrument
  const { data: quoteData, refetch: refetchQuote } = useQuery({
    queryKey: ['derivatives-quote', selectedInstrument?.id],
    queryFn: async () => {
      if (!selectedInstrument) return null;
      return getJson<{ quote: DerivativeQuote; microstructure?: MarketMicrostructure }>(`/api/derivatives/quotes/${encodeURIComponent(selectedInstrument.id)}`);
    },
    enabled: !!selectedInstrument,
    refetchInterval: 5000, // Refresh every 5 seconds
  });

  const instrumentId = selectedInstrument?.id;
  const depthQuery = useQuery({
    queryKey: ['derivatives-depth', instrumentId],
    queryFn: () => getJson<MarketDepth>(`/api/derivatives/quotes/${encodeURIComponent(instrumentId!)}/depth?depth=20`),
    enabled: Boolean(instrumentId),
    refetchInterval: 5000,
  });
  const fundingQuery = useQuery({
    queryKey: ['derivatives-funding', instrumentId],
    queryFn: () => getJson<FundingData>(`/api/derivatives/funding/${encodeURIComponent(instrumentId!)}`),
    enabled: Boolean(instrumentId),
    refetchInterval: 30000,
  });
  const oiQuery = useQuery({
    queryKey: ['derivatives-oi', instrumentId],
    queryFn: () => getJson<OpenInterestData>(`/api/derivatives/open-interest/${encodeURIComponent(instrumentId!)}`),
    enabled: Boolean(instrumentId),
    refetchInterval: 30000,
  });
  const analyticsQuery = useQuery({
    queryKey: ['derivatives-analytics', instrumentId],
    queryFn: () => getJson<AdvancedAnalytics>(`/api/derivatives/analytics/${encodeURIComponent(instrumentId!)}?days=30`),
    enabled: Boolean(instrumentId) && activeTab === 'analytics',
  });
  const riskQuery = useQuery({
    queryKey: ['derivatives-risk', instrumentId],
    queryFn: () => getJson<RiskMetrics>(`/api/derivatives/risk/${encodeURIComponent(instrumentId!)}?days=90`),
    enabled: Boolean(instrumentId) && activeTab === 'risk',
  });

  const instruments: DerivativeInstrument[] = instrumentsData?.instruments || [];
  const quote = quoteData?.quote;
  const microstructure = quoteData?.microstructure;

  useEffect(() => {
    if (!selectedInstrument && instruments.length > 0) setSelectedInstrument(instruments[0]);
  }, [instruments, selectedInstrument]);

  const handleInstrumentSelect = (instrument: DerivativeInstrument) => {
    setSelectedInstrument(instrument);
    setActiveTab('quote');
  };

  const [simulation, setSimulation] = useState({ scenarioName: 'Research scenario', direction: 'LONG' as 'LONG' | 'SHORT', entryPrice: '', exitPrice: '', quantity: '1', leverage: '1' });
  const [simulationResult, setSimulationResult] = useState<Simulation | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [replay, setReplay] = useState({ startDate: '2025-01-01', endDate: '2025-03-31', direction: 'LONG' as 'LONG' | 'SHORT', entryPrice: '', quantity: '1', leverage: '1' });
  const [replayResult, setReplayResult] = useState<Record<string, number | string> | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);

  const submitSimulation = async () => {
    if (!selectedInstrument || !simulation.entryPrice || !Number(simulation.quantity)) return;
    setSimulationError(null);
    try {
      const result = await fetch(`${API_BASE}/api/derivatives/simulation`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instrument_id: selectedInstrument.id, scenario_name: simulation.scenarioName, direction: simulation.direction, entry_price: Number(simulation.entryPrice), quantity: Number(simulation.quantity), leverage: Number(simulation.leverage) }),
      });
      if (!result.ok) throw new Error(await result.text());
      setSimulationResult(await result.json() as Simulation);
    } catch (error) { setSimulationError(error instanceof Error ? error.message : 'Paper simulation unavailable.'); }
  };

  const closeSimulation = async () => {
    if (!simulationResult?.id || !simulation.exitPrice) return;
    setSimulationError(null);
    try {
      const result = await fetch(`${API_BASE}/api/derivatives/simulation/${encodeURIComponent(simulationResult.id)}/close?exit_price=${encodeURIComponent(simulation.exitPrice)}`, { method: 'POST' });
      if (!result.ok) throw new Error(await result.text());
      setSimulationResult(await result.json() as Simulation);
    } catch (error) { setSimulationError(error instanceof Error ? error.message : 'Unable to close paper scenario.'); }
  };

  const runReplay = async () => {
    if (!selectedInstrument || !replay.entryPrice) return;
    setReplayError(null);
    try {
      const result = await fetch(`${API_BASE}/api/derivatives/simulation/replay`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instrument_id: selectedInstrument.id, start_date: `${replay.startDate}T00:00:00Z`, end_date: `${replay.endDate}T23:59:59Z`, entry_price: Number(replay.entryPrice), direction: replay.direction, quantity: Number(replay.quantity), leverage: Number(replay.leverage) }),
      });
      if (!result.ok) throw new Error(await result.text());
      setReplayResult(await result.json() as Record<string, number | string>);
    } catch (error) { setReplayError(error instanceof Error ? error.message : 'Historical replay unavailable.'); }
  };

  const formatPrice = (price: number | undefined, precision: number = 2) => {
    if (price === undefined || price === null) return 'N/A';
    return price.toFixed(precision);
  };

  const formatPercent = (percent: number | undefined) => {
    if (percent === undefined || percent === null) return 'N/A';
    const sign = percent >= 0 ? '+' : '';
    return `${sign}${percent.toFixed(2)}%`;
  };

  const getFreshnessColor = (status: string) => {
    switch (status) {
      case 'LIVE': return 'text-green-500';
      case 'RECENT': return 'text-blue-500';
      case 'DELAYED': return 'text-yellow-500';
      case 'STALE': return 'text-orange-500';
      case 'UNAVAILABLE': return 'text-red-500';
      default: return 'text-gray-500';
    }
  };

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white">
      {/* Header */}
      <div className="bg-gray-800 border-b border-gray-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Derivatives Terminal</h1>
            <p className="text-gray-400 text-sm">Educational Analytics & Paper Simulation</p>
          </div>
          <div className="flex items-center space-x-4">
            <span className="text-sm text-gray-400">Phase 16 - Perpetual Futures Analytics</span>
            <span className="px-3 py-1 bg-blue-600 text-xs rounded-full">PAPER SIMULATION</span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar - Asset Classes & Instruments */}
        <div className="w-80 bg-gray-800 border-r border-gray-700 flex flex-col">
          {/* Asset Class Selector */}
          <div className="p-4 border-b border-gray-700">
            <h2 className="text-sm font-semibold text-gray-400 mb-3">ASSET CLASS</h2>
            <div className="grid grid-cols-2 gap-2">
              {(['CRYPTO', 'COMMODITIES', 'INDICES', 'STOCKS'] as AssetClass[]).map((assetClass) => (
                <button
                  key={assetClass}
                  onClick={() => setSelectedAssetClass(assetClass)}
                  className={`px-3 py-2 rounded text-sm font-medium transition-colors ${
                    selectedAssetClass === assetClass
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {assetClass}
                </button>
              ))}
            </div>
          </div>

          {/* Instruments List */}
          <div className="flex-1 overflow-y-auto">
            <div className="p-4">
              <h2 className="text-sm font-semibold text-gray-400 mb-3">INSTRUMENTS</h2>
              {instrumentsLoading ? (
                <div className="text-center text-gray-500 py-4">Loading...</div>
              ) : instruments.length === 0 ? (
                <div className="text-center text-gray-500 py-4">No instruments available</div>
              ) : (
                <div className="space-y-2">
                  {instruments.map((instrument: DerivativeInstrument) => (
                    <button
                      key={instrument.id}
                      onClick={() => handleInstrumentSelect(instrument)}
                      className={`w-full text-left p-3 rounded transition-colors ${
                        selectedInstrument?.id === instrument.id
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      <div className="font-medium">{instrument.symbol}</div>
                      <div className="text-xs opacity-75">{instrument.display_name}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Main Panel */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selectedInstrument ? (
            <>
              {/* Instrument Header */}
              <div className="bg-gray-800 border-b border-gray-700 px-6 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-bold">{selectedInstrument.display_name}</h2>
                    <div className="flex items-center space-x-4 text-sm text-gray-400 mt-1">
                      <span>{selectedInstrument.symbol}</span>
                      <span>{selectedInstrument.exchange}</span>
                      <span>{selectedInstrument.contract_type}</span>
                      <span className={getFreshnessColor(quote?.status || 'UNAVAILABLE')}>
                        {quote?.status || 'UNAVAILABLE'}
                      </span>
                    </div>
                  </div>
                  {quote && (
                    <div className="text-right">
                      <div className="text-3xl font-bold">
                        {formatPrice(quote.last_price, selectedInstrument.price_precision)}
                      </div>
                      <div className={`text-sm ${(quote.change_percent_24h ?? 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                        {formatPercent(quote.change_percent_24h)}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Tabs */}
              <div className="bg-gray-800 border-b border-gray-700 px-6">
                <div className="flex space-x-1">
                  {(['quote', 'depth', 'funding', 'oi', 'analytics', 'risk', 'simulation'] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`px-4 py-3 text-sm font-medium transition-colors ${
                        activeTab === tab
                          ? 'bg-gray-700 text-white border-b-2 border-blue-500'
                          : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      {tab.charAt(0).toUpperCase() + tab.slice(1).replace('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>

              {/* Tab Content */}
              <div className="flex-1 overflow-y-auto p-6">
                {activeTab === 'quote' && quote && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <MetricCard label="Bid" value={formatPrice(quote.bid, selectedInstrument.price_precision)} />
                    <MetricCard label="Ask" value={formatPrice(quote.ask, selectedInstrument.price_precision)} />
                    <MetricCard label="Spread" value={formatPrice(quote.spread, selectedInstrument.price_precision)} />
                    <MetricCard label="Mark Price" value={formatPrice(quote.mark_price, selectedInstrument.price_precision)} />
                    <MetricCard label="24h High" value={formatPrice(quote.high_24h, selectedInstrument.price_precision)} />
                    <MetricCard label="24h Low" value={formatPrice(quote.low_24h, selectedInstrument.price_precision)} />
                    <MetricCard label="24h Volume" value={quote.volume_24h == null ? 'Unavailable' : quote.volume_24h.toLocaleString()} />
                    <MetricCard label="Open Interest" value={quote.open_interest == null ? 'Unavailable' : quote.open_interest.toLocaleString()} />
                    <MetricCard label="Funding Rate" value={quote.funding_rate ? `${(quote.funding_rate * 100).toFixed(4)}%` : 'N/A'} />
                    <MetricCard label="Index Price" value={formatPrice(quote.index_price, selectedInstrument.price_precision)} />
                    <MetricCard label="Source" value={quote.source} />
                    <MetricCard label="Last Update" value={new Date(quote.timestamp).toLocaleTimeString()} />
                  </div>
                )}

                {activeTab === 'depth' && (
                  <DepthPanel data={depthQuery.data} loading={depthQuery.isLoading} error={depthQuery.error} precision={selectedInstrument.price_precision} />
                )}

                {activeTab === 'funding' && (
                  <FundingPanel data={fundingQuery.data} loading={fundingQuery.isLoading} error={fundingQuery.error} />
                )}

                {activeTab === 'oi' && (
                  <OpenInterestPanel data={oiQuery.data} loading={oiQuery.isLoading} error={oiQuery.error} />
                )}

                {activeTab === 'analytics' && (
                  <AnalyticsPanel data={analyticsQuery.data} loading={analyticsQuery.isLoading} error={analyticsQuery.error} />
                )}

                {activeTab === 'risk' && (
                  <RiskPanel data={riskQuery.data} loading={riskQuery.isLoading} error={riskQuery.error} />
                )}

                {activeTab === 'simulation' && (
                  <SimulationPanel simulation={simulation} setSimulation={setSimulation} result={simulationResult} error={simulationError} onCreate={submitSimulation} onClose={closeSimulation} replay={replay} setReplay={setReplay} replayResult={replayResult} replayError={replayError} onReplay={runReplay} />
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-gray-500">
                <div className="text-6xl mb-4">📊</div>
                <h3 className="text-xl font-semibold mb-2">Select an Instrument</h3>
                <p>Choose an instrument from the sidebar to view derivatives analytics</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PanelState({ loading, error }: { loading: boolean; error: Error | null }) {
  if (loading) return <div className="derivative-state">Loading verified market data...</div>;
  if (error) return <div className="derivative-state derivative-error" role="alert">{error.message}</div>;
  return null;
}

function DataLabel({ source, mode }: { source?: string; mode?: string }) {
  return <div className="derivative-data-label">Source: {source || 'Unavailable'} · Mode: {mode || 'UNAVAILABLE'}</div>;
}

function DepthPanel({ data, loading, error, precision }: { data?: MarketDepth; loading: boolean; error: Error | null; precision: number }) {
  const totalBid = data?.bids.at(-1)?.cumulative_quantity ?? 0;
  const totalAsk = data?.asks.at(-1)?.cumulative_quantity ?? 0;
  return <div className="derivative-panel"><PanelState loading={loading} error={error} />{data && <>
    <div className="derivative-panel-head"><div><h3>Read-only market depth</h3><DataLabel source={data.source} mode={data.data_mode || data.status} /></div><span>BID {totalBid.toFixed(4)} · ASK {totalAsk.toFixed(4)}</span></div>
    <div className="depth-grid"><DepthTable title="BIDS" rows={data.bids} precision={precision} tone="bid" /><DepthTable title="ASKS" rows={data.asks} precision={precision} tone="ask" /></div>
  </>}</div>;
}

function DepthTable({ title, rows, precision, tone }: { title: string; rows: DepthLevel[]; precision: number; tone: 'bid' | 'ask' }) {
  return <div className="depth-table"><h4 className={tone}>{title}</h4><div className="depth-row depth-header"><span>Price</span><span>Quantity</span><span>Cumulative</span></div>{rows.length === 0 ? <p className="derivative-muted">Order book unavailable from source.</p> : rows.map((row, index) => <div className="depth-row" key={`${tone}-${row.price}-${index}`}><span>{row.price.toFixed(precision)}</span><span>{row.quantity.toFixed(6)}</span><span>{(row.cumulative_quantity ?? 0).toFixed(6)}</span></div>)}</div>;
}

function FundingPanel({ data, loading, error }: { data?: FundingData; loading: boolean; error: Error | null }) {
  return <div className="derivative-panel"><PanelState loading={loading} error={error} />{data && <><div className="derivative-panel-head"><div><h3>Funding analytics</h3><DataLabel source={data.source} mode={data.data_mode || data.status} /></div><span>{data.next_funding_time ? `Next: ${new Date(data.next_funding_time).toLocaleString()}` : 'Next funding not supplied'}</span></div><div className="metric-grid"><MetricCard label="Current funding" value={data.current_funding_rate == null ? 'Unavailable' : `${(data.current_funding_rate * 100).toFixed(4)}%`} /><MetricCard label="Previous funding" value={data.last_funding_rate == null ? 'Unavailable' : `${(data.last_funding_rate * 100).toFixed(4)}%`} /><MetricCard label="Interval" value={data.funding_interval_hours == null ? 'Not supplied' : `${data.funding_interval_hours}h`} /><MetricCard label="Observations" value={data.historical_rates.length} /></div><HistoryRows rows={data.historical_rates.map((row) => ({ timestamp: row.timestamp, value: row.funding_rate }))} suffix="%" multiplier={100} /></>}</div>;
}

function OpenInterestPanel({ data, loading, error }: { data?: OpenInterestData; loading: boolean; error: Error | null }) {
  return <div className="derivative-panel"><PanelState loading={loading} error={error} />{data && <><div className="derivative-panel-head"><div><h3>Open interest analytics</h3><DataLabel source={data.source} mode={data.data_mode || data.status} /></div><span>Historical series: {data.historical_oi.length} points</span></div><div className="metric-grid"><MetricCard label="Current OI" value={data.current_open_interest == null ? 'Unavailable' : data.current_open_interest.toLocaleString()} /><MetricCard label="OI value" value={data.open_interest_value == null ? 'Unavailable' : data.open_interest_value.toLocaleString()} /><MetricCard label="24h change" value={data.open_interest_change_percent_24h == null ? 'Unavailable' : `${data.open_interest_change_percent_24h.toFixed(2)}%`} /></div><HistoryRows rows={data.historical_oi.map((row) => ({ timestamp: row.timestamp, value: row.open_interest }))} /></>}</div>;
}

function AnalyticsPanel({ data, loading, error }: { data?: AdvancedAnalytics; loading: boolean; error: Error | null }) {
  const metrics = data ? [['Volatility', pct(data.volatility)], ['7d rolling vol', pct(data.rolling_volatility_7d)], ['30d rolling vol', pct(data.rolling_volatility_30d)], ['7d moving average', num(data.moving_average_7d)], ['30d moving average', num(data.moving_average_30d)], ['RSI', num(data.rsi)], ['Z-score', num(data.z_score)], ['Momentum', pct(data.price_momentum)], ['Sharpe', num(data.sharpe_ratio)], ['Max drawdown', pct(data.max_drawdown)]] : [];
  return <div className="derivative-panel"><PanelState loading={loading} error={error} />{data && <><h3>Statistical analytics</h3><p className="derivative-muted">Derived from provider-supplied historical candles. Statistics describe history and do not predict outcomes.</p><div className="metric-grid">{metrics.map(([label, value]) => <MetricCard key={label} label={label} value={value} />)}</div></>}</div>;
}

function RiskPanel({ data, loading, error }: { data?: RiskMetrics; loading: boolean; error: Error | null }) {
  const metrics = data ? [['Historical volatility', pct(data.historical_volatility)], ['Max drawdown', pct(data.max_historical_drawdown)], ['Recent range', pct(data.recent_price_range)], ['VaR 95%', pct(data.value_at_risk_95)], ['Expected shortfall', pct(data.expected_shortfall_95)], ['Data quality', ratio(data.data_quality_score)], ['Liquidity', ratio(data.liquidity_indicator)], ['Stress indicator', ratio(data.market_stress_indicator)]] : [];
  return <div className="derivative-panel"><PanelState loading={loading} error={error} />{data && <><h3>Risk visualization</h3><p className="derivative-muted">Educational historical risk measures. They are not guarantees, signals, or investment advice.</p><div className="metric-grid">{metrics.map(([label, value]) => <MetricCard key={label} label={label} value={value} />)}</div><div className="derivative-disclaimer">{data.disclaimer}</div></>}</div>;
}

function HistoryRows({ rows, suffix = '', multiplier = 1 }: { rows: Array<{ timestamp?: string; value?: number }>; suffix?: string; multiplier?: number }) {
  if (!rows.length) return <p className="derivative-muted">Historical observations are unavailable from the selected provider.</p>;
  return <div className="history-list">{rows.slice(-8).reverse().map((row, index) => <div className="history-row" key={`${row.timestamp}-${index}`}><span>{row.timestamp ? new Date(row.timestamp).toLocaleString() : 'Timestamp unavailable'}</span><strong>{row.value == null ? 'Unavailable' : `${(row.value * multiplier).toFixed(6)}${suffix}`}</strong></div>)}</div>;
}

function SimulationPanel({ simulation, setSimulation, result, error, onCreate, onClose, replay, setReplay, replayResult, replayError, onReplay }: any) {
  const field = (label: string, value: string, onChange: (value: string) => void, type = 'text') => <label className="derivative-field">{label}<input type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
  return <div className="derivative-panel"><div className="simulation-banner">PAPER SIMULATION · No orders, balances, settlement, custody, or real-money execution.</div><div className="simulation-grid"><section><h3>Scenario calculator</h3>{field('Scenario name', simulation.scenarioName, (value) => setSimulation({ ...simulation, scenarioName: value }))}<label className="derivative-field">Direction<select value={simulation.direction} onChange={(event) => setSimulation({ ...simulation, direction: event.target.value })}><option value="LONG">LONG</option><option value="SHORT">SHORT</option></select></label>{field('Entry reference', simulation.entryPrice, (value) => setSimulation({ ...simulation, entryPrice: value }), 'number')}{field('Hypothetical quantity', simulation.quantity, (value) => setSimulation({ ...simulation, quantity: value }), 'number')}{field('Educational leverage factor', simulation.leverage, (value) => setSimulation({ ...simulation, leverage: value }), 'number')}<button className="derivative-action" onClick={onCreate}>Create paper scenario</button>{result && <div className="simulation-result"><strong>{result.status}</strong><span>Scenario: {result.scenario_name}</span><span>Reference entry: {result.entry_price}</span>{result.id && result.status === 'ACTIVE' && <>{field('Exit reference', simulation.exitPrice, (value) => setSimulation({ ...simulation, exitPrice: value }), 'number')}<button className="derivative-action secondary" onClick={onClose}>Close paper scenario</button></>}</div>}{error && <p className="derivative-error">{error}</p>}</section><section><h3>Historical replay</h3><p className="derivative-muted">Uses actual provider candles for the selected interval. No synthetic candles are created.</p>{field('Start date', replay.startDate, (value) => setReplay({ ...replay, startDate: value }), 'date')}{field('End date', replay.endDate, (value) => setReplay({ ...replay, endDate: value }), 'date')}{field('Entry reference', replay.entryPrice, (value) => setReplay({ ...replay, entryPrice: value }), 'number')}{field('Quantity', replay.quantity, (value) => setReplay({ ...replay, quantity: value }), 'number')}<button className="derivative-action" onClick={onReplay}>Replay actual history</button>{replayError && <p className="derivative-error">{replayError}</p>}{replayResult && <div className="simulation-result"><span>Entry reference: {String(replayResult.entry_reference)}</span><span>Exit reference: {String(replayResult.exit_reference)}</span><span>Price movement: {String(replayResult.price_movement)}</span><strong>Hypothetical result: {String(replayResult.hypothetical_result)}</strong><span>Data points: {String(replayResult.data_points)}</span></div>}</section></div></div>;
}

const num = (value?: number) => value == null || !Number.isFinite(value) ? 'Unavailable' : value.toFixed(4);
const pct = (value?: number) => value == null || !Number.isFinite(value) ? 'Unavailable' : `${(value * 100).toFixed(2)}%`;
const ratio = (value?: number) => value == null || !Number.isFinite(value) ? 'Unavailable' : `${(value * 100).toFixed(1)}%`;

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="text-sm text-gray-400 mb-1">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
