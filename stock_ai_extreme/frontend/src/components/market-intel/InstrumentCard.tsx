/**
 * Phase 23B — Instrument Card (spec §5)
 *
 * A separate card for the index (SPX) and the ETF (SPY). It shows the latest
 * available *trading-session close*, the absolute and percentage change, the
 * direction, the trading date, the source and the data status. The card states
 * explicitly that the value is a close, never a live intraday quote, so a
 * closed market is never presented as a live price.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { DataSourceBadge } from '../macro';
import { formatPercent, formatPrice } from './api';

export interface InstrumentInfo {
  key: string;
  symbol: string;
  name: string;
  kind: 'INDEX' | 'ETF' | string;
  currency: string;
  is_index: boolean;
}

export interface LatestSession {
  instrument: string;
  symbol: string;
  instrument_kind: string;
  trading_date: string;
  close: number | null;
  previous_close: number | null;
  absolute_change: number | null;
  return_pct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | null;
  source: string;
  source_timestamp: string | null;
  quote_basis?: string;
  note?: string;
  is_latest_available_session?: boolean;
}

interface InstrumentCardProps {
  info: InstrumentInfo;
  latest: LatestSession | null;
  source?: string | null;
  status?: string | null;
  error?: string | null;
}

const directionClasses = (direction: string | null | undefined): string => {
  if (direction === 'UP') return 'bg-green-100 text-green-800';
  if (direction === 'DOWN') return 'bg-red-100 text-red-800';
  if (direction === 'FLAT') return 'bg-gray-100 text-gray-800';
  return 'bg-gray-100 text-gray-600';
};

export const InstrumentCard: React.FC<InstrumentCardProps> = ({
  info,
  latest,
  source,
  status,
  error,
}) => {
  const changeColor =
    latest?.direction === 'UP'
      ? 'text-green-600'
      : latest?.direction === 'DOWN'
      ? 'text-red-600'
      : 'text-gray-600';

  return (
    <BaseCard className="p-5" variant="bordered">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-gray-900">{info.symbol}</h3>
            <BaseBadge variant={info.is_index ? 'info' : 'secondary'} size="sm">
              {info.kind}
            </BaseBadge>
          </div>
          <p className="text-xs text-gray-500">{info.name}</p>
        </div>
        {latest?.direction && (
          <span className={`px-2 py-1 rounded text-xs font-semibold ${directionClasses(latest.direction)}`}>
            {latest.direction}
          </span>
        )}
      </div>

      {error && !latest ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : latest ? (
        <>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold text-gray-900">
              {formatPrice(latest.close)}
            </span>
            <span className={`text-sm font-semibold ${changeColor}`}>
              {latest.absolute_change !== null && latest.absolute_change !== undefined
                ? `${latest.absolute_change >= 0 ? '+' : ''}${formatPrice(latest.absolute_change)}`
                : 'N/A'}{' '}
              ({formatPercent(latest.return_pct)})
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-1 text-xs text-gray-600">
            <span>
              Trading date:{' '}
              <span className="font-medium text-gray-800">{latest.trading_date}</span>
            </span>
            <span>
              Prev close:{' '}
              <span className="font-medium text-gray-800">{formatPrice(latest.previous_close)}</span>
            </span>
          </div>
          <div className="mt-3">
            <DataSourceBadge source={source ?? latest.source} status={status ?? undefined} />
          </div>
          <p className="text-[11px] text-gray-500 mt-2">
            {latest.note ?? 'Latest available trading-session close — not a live intraday quote.'}
          </p>
        </>
      ) : (
        <p className="text-sm text-gray-500">No observation available.</p>
      )}
    </BaseCard>
  );
};

export default InstrumentCard;
