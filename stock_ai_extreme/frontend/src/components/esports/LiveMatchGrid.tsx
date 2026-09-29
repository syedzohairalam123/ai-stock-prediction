/**
 * Phase 21B §6/§21/§22/§23 — the live match grid.
 *
 * Owns the loading, empty and error presentations so every caller shows the
 * same honest messages. `LiveMatchCard` is memoized and the grid is memoized on
 * its props, so an incoming ticker event never re-renders the list (§10).
 */
import { memo } from "react";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";

import type { EsportsMatch } from "../../lib/esports";
import LiveMatchCard from "./LiveMatchCard";
import { MatchGridSkeleton } from "./EsportsSkeletons";

export interface LiveMatchGridProps {
  matches: EsportsMatch[];
  loading?: boolean;
  error?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
  onRetry?: () => void;
  showGame?: boolean;
}

function LiveMatchGridBase({
  matches,
  loading = false,
  error = null,
  emptyTitle = "No live matches currently available.",
  emptyDescription,
  onRetry,
  showGame = true,
}: LiveMatchGridProps) {
  if (loading && matches.length === 0) {
    return <MatchGridSkeleton />;
  }

  if (error && matches.length === 0) {
    return (
      <div className="esp-state esp-state--error" role="alert">
        <AlertTriangle size={28} aria-hidden="true" />
        <h3>Could not load matches</h3>
        <p>{error}</p>
        {onRetry && (
          <button type="button" className="esp-btn" onClick={onRetry}>
            <RefreshCw size={14} aria-hidden="true" /> Try again
          </button>
        )}
      </div>
    );
  }

  if (matches.length === 0) {
    return (
      <div className="esp-state esp-state--empty" role="status">
        <Inbox size={28} aria-hidden="true" />
        <h3>{emptyTitle}</h3>
        {emptyDescription && <p>{emptyDescription}</p>}
        {onRetry && (
          <button type="button" className="esp-btn" onClick={onRetry}>
            <RefreshCw size={14} aria-hidden="true" /> Refresh
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="esp-grid">
      {matches.map((match) => (
        <LiveMatchCard key={match.id} match={match} showGame={showGame} />
      ))}
    </div>
  );
}

export default memo(LiveMatchGridBase);
