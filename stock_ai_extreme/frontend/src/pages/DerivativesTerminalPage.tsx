/**
 * Derivatives Terminal Page for Phase 16 - Advanced Live Perpetual Futures Analytics + Paper Simulation Engine
 * 
 * This is the main derivatives trading terminal interface for educational analytics and paper simulation.
 * No real-money execution is supported.
 */

import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';

// API base URL
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

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
}

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
      const response = await fetch(`${API_BASE}/api/derivatives/quotes/${selectedInstrument.id}`);
      if (!response.ok) throw new Error('Failed to fetch quote');
      return response.json();
    },
    enabled: !!selectedInstrument,
    refetchInterval: 5000, // Refresh every 5 seconds
  });

  const instruments = instrumentsData?.instruments || [];
  const quote = quoteData?.quote;
  const microstructure = quoteData?.microstructure;

  const handleInstrumentSelect = (instrument: DerivativeInstrument) => {
    setSelectedInstrument(instrument);
    setActiveTab('quote');
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
                      <div className={`text-sm ${quote.change_percent_24h >= 0 ? 'text-green-500' : 'text-red-500'}`}>
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
                    <MetricCard label="24h Volume" value={quote.volume_24h?.toLocaleString()} />
                    <MetricCard label="Open Interest" value={quote.open_interest?.toLocaleString()} />
                    <MetricCard label="Funding Rate" value={quote.funding_rate ? `${(quote.funding_rate * 100).toFixed(4)}%` : 'N/A'} />
                    <MetricCard label="Index Price" value={formatPrice(quote.index_price, selectedInstrument.price_precision)} />
                    <MetricCard label="Source" value={quote.source} />
                    <MetricCard label="Last Update" value={new Date(quote.timestamp).toLocaleTimeString()} />
                  </div>
                )}

                {activeTab === 'depth' && (
                  <div className="text-center text-gray-500 py-8">
                    Market depth visualization - Order book coming soon
                  </div>
                )}

                {activeTab === 'funding' && (
                  <div className="text-center text-gray-500 py-8">
                    Funding rate analytics coming soon
                  </div>
                )}

                {activeTab === 'oi' && (
                  <div className="text-center text-gray-500 py-8">
                    Open interest analytics coming soon
                  </div>
                )}

                {activeTab === 'analytics' && (
                  <div className="text-center text-gray-500 py-8">
                    Advanced analytics coming soon
                  </div>
                )}

                {activeTab === 'risk' && (
                  <div className="text-center text-gray-500 py-8">
                    Risk metrics visualization coming soon
                  </div>
                )}

                {activeTab === 'simulation' && (
                  <div className="text-center text-gray-500 py-8">
                    Paper simulation tool coming soon
                  </div>
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

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="text-sm text-gray-400 mb-1">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}
