/**
 * Phase 23A — Data Source Badge Component (spec §18)
 *
 * Every displayed value must say where it came from. This badge renders the
 * source name, an optional freshness/status chip, and a link to the exact
 * source document when one exists (FRED series page, official central-bank
 * calendar, prediction-market event). The external-provider detail stays in
 * the API payload; the UI only presents it, so nothing is implied to be the
 * central bank's own statement when it is not.
 */
import React from 'react';
import BaseBadge from '../BaseBadge';
import { ExternalLink } from 'lucide-react';

interface DataSourceBadgeProps {
  source: string | null | undefined;
  sourceUrl?: string | null;
  /** e.g. LIVE / RECENT / HISTORICAL / SOURCE-REPORTED. */
  status?: string | null;
  label?: string;
  className?: string;
}

export const DataSourceBadge: React.FC<DataSourceBadgeProps> = ({
  source,
  sourceUrl,
  status,
  label = 'Source',
  className = '',
}) => {
  if (!source && !sourceUrl) return null;
  return (
    <span className={`inline-flex items-center gap-2 flex-wrap ${className}`}>
      <span className="text-xs text-gray-500">
        {label}: <span className="font-medium text-gray-700">{source ?? 'N/A'}</span>
      </span>
      {status && (
        <BaseBadge variant="outline" size="sm">
          {status}
        </BaseBadge>
      )}
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
          title={`Verify at ${source ?? 'the source'}`}
        >
          verify <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </span>
  );
};

export default DataSourceBadge;
