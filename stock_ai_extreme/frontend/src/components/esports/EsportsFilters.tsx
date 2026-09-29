/**
 * Phase 21B §24/§25 — search & filters.
 *
 * Game, live, upcoming, status, tournament, date and region filters plus a text
 * search. The filter value is fully controlled by the page, which keeps it in
 * the URL, so refreshing restores the exact view (§25) and the backend does the
 * actual filtering for large datasets (§24).
 */
import { Search, X } from "lucide-react";

import { GAME_LABELS, HUB_GAMES, type EsportsTournament, type MatchStatusValue } from "../../lib/esports";

export interface EsportsFiltersValue {
  game: string | null;
  live: boolean;
  upcoming: boolean;
  status: MatchStatusValue | null;
  tournamentId: string | null;
  dateFrom: string | null;
  dateTo: string | null;
  region: string | null;
  q: string;
}

export const EMPTY_FILTERS: EsportsFiltersValue = {
  game: null,
  live: false,
  upcoming: false,
  status: null,
  tournamentId: null,
  dateFrom: null,
  dateTo: null,
  region: null,
  q: "",
};

const STATUS_OPTIONS: { value: MatchStatusValue | ""; label: string }[] = [
  { value: "", label: "Any status" },
  { value: "LIVE", label: "Live" },
  { value: "UPCOMING", label: "Upcoming" },
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "PAUSED", label: "Paused" },
  { value: "MAP_BREAK", label: "Map break" },
  { value: "COMPLETED", label: "Completed" },
];

export default function EsportsFilters({
  value,
  onChange,
  onClear,
  tournaments = [],
}: {
  value: EsportsFiltersValue;
  onChange: (patch: Partial<EsportsFiltersValue>) => void;
  onClear: () => void;
  tournaments?: EsportsTournament[];
}) {
  const hasFilters =
    Boolean(value.game) ||
    value.live ||
    value.upcoming ||
    Boolean(value.status) ||
    Boolean(value.tournamentId) ||
    Boolean(value.dateFrom) ||
    Boolean(value.dateTo) ||
    Boolean(value.region) ||
    Boolean(value.q);

  return (
    <form className="esp-filters" role="search" aria-label="Match filters" onSubmit={(e) => e.preventDefault()}>
      <label className="esp-field">
        <span>Game</span>
        <select value={value.game ?? ""} onChange={(e) => onChange({ game: e.target.value || null })}>
          <option value="">All games</option>
          {HUB_GAMES.map((gameId) => (
            <option key={gameId} value={gameId}>
              {GAME_LABELS[gameId]}
            </option>
          ))}
        </select>
      </label>

      <label className="esp-field">
        <span>Status</span>
        <select
          value={value.status ?? ""}
          onChange={(e) => onChange({ status: (e.target.value as MatchStatusValue) || null })}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.label} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="esp-field">
        <span>Tournament</span>
        <select
          value={value.tournamentId ?? ""}
          onChange={(e) => onChange({ tournamentId: e.target.value || null })}
        >
          <option value="">All tournaments</option>
          {tournaments.map((tournament) => (
            <option key={tournament.id} value={tournament.id}>
              {tournament.name}
            </option>
          ))}
        </select>
      </label>

      <label className="esp-field">
        <span>From</span>
        <input type="date" value={value.dateFrom ?? ""} onChange={(e) => onChange({ dateFrom: e.target.value || null })} />
      </label>

      <label className="esp-field">
        <span>To</span>
        <input type="date" value={value.dateTo ?? ""} onChange={(e) => onChange({ dateTo: e.target.value || null })} />
      </label>

      <label className="esp-field">
        <span>Region</span>
        <input
          type="text"
          placeholder="e.g. EU"
          value={value.region ?? ""}
          onChange={(e) => onChange({ region: e.target.value || null })}
        />
      </label>

      <label className="esp-field esp-field--search">
        <span>Search</span>
        <span className="esp-search-input">
          <Search size={13} aria-hidden="true" />
          <input
            type="search"
            placeholder="Team, tournament, id…"
            value={value.q}
            onChange={(e) => onChange({ q: e.target.value })}
          />
        </span>
      </label>

      <div className="esp-filter-toggles" role="group" aria-label="Quick filters">
        <button
          type="button"
          className={`esp-toggle${value.live ? " active" : ""}`}
          aria-pressed={value.live}
          onClick={() => onChange({ live: !value.live })}
        >
          Live only
        </button>
        <button
          type="button"
          className={`esp-toggle${value.upcoming ? " active" : ""}`}
          aria-pressed={value.upcoming}
          onClick={() => onChange({ upcoming: !value.upcoming })}
        >
          Upcoming only
        </button>
        {hasFilters && (
          <button type="button" className="esp-toggle esp-toggle--clear" onClick={onClear}>
            <X size={12} aria-hidden="true" /> Clear
          </button>
        )}
      </div>
    </form>
  );
}
