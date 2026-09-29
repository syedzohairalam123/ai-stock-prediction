/**
 * Phase 21B §9/§10 — live esports activity ticker.
 *
 * Consumes the Phase 21A WebSocket event stream (through the store) and renders
 * esports activity — not trading activity. It selects ONLY the `events` slice,
 * so an incoming snapshot or scoreboard update never re-renders the ticker, and
 * each entry is memoized (§10). A new event never re-renders the page around it.
 */
import { memo } from "react";
import { Radio } from "lucide-react";

import { relTime, type EsportsEvent } from "../../lib/esports";
import { useEsportsStore, selectTickerEvents } from "../../store/useEsportsStore";

function sentence(event: EsportsEvent): string {
  const p = event.payload || {};
  const a = typeof p.team_a_name === "string" ? p.team_a_name : null;
  const b = typeof p.team_b_name === "string" ? p.team_b_name : null;
  switch (event.type) {
    case "SCORE_CHANGED":
      if (a || b) {
        return `${a ?? "Team A"} ${p.team_a_score ?? "?"} – ${p.team_b_score ?? "?"} ${b ?? "Team B"}`;
      }
      return `Score changed · ${p.team_a_score ?? "?"} – ${p.team_b_score ?? "?"}`;
    case "MAP_STARTED":
      return typeof p.map_name === "string"
        ? `Map ${p.map_number ?? ""} started · ${p.map_name}`.trim()
        : `Map ${p.map_number ?? ""} started`.trim();
    case "MAP_ENDED":
      return `Map ended · ${p.team_a_score ?? "?"} – ${p.team_b_score ?? "?"}`;
    case "ROUND_ENDED":
      return typeof p.winner === "string" ? `Round ended · ${p.winner} won` : "Round ended";
    case "ROUND_STARTED":
      return `Round ${p.round_number ?? ""} started`.trim();
    case "MATCH_STARTED":
      return "Match started";
    case "MATCH_ENDED":
      return "Match ended";
    case "MATCH_PAUSED":
      return "Match paused";
    case "MATCH_RESUMED":
      return "Match resumed";
    case "PLAYER_EVENT":
      return typeof p.player_event_type === "string" ? `Player event · ${p.player_event_type}` : "Player event detected";
    case "OBJECTIVE_EVENT":
      return typeof p.objective_type === "string" ? `Objective · ${p.objective_type}` : "Objective event";
    default:
      return event.type.replace(/_/g, " ").toLowerCase();
  }
}

const TickerItem = memo(function TickerItem({ event }: { event: EsportsEvent }) {
  return (
    <li className="esp-ticker-item">
      <Radio size={11} aria-hidden="true" className="esp-ticker-icon" />
      <span className="esp-ticker-text">{sentence(event)}</span>
      <span className="esp-ticker-time">{relTime(event.timestamp)}</span>
      <span className="esp-ticker-source">{event.source}</span>
    </li>
  );
});

function ActivityTickerBase() {
  const events = useEsportsStore(selectTickerEvents);
  const visible = events.slice(0, 18);

  return (
    <section className="esp-ticker" aria-label="Live esports activity" aria-live="polite">
      <span className="esp-ticker-label">
        <Radio size={12} aria-hidden="true" /> Live activity
      </span>
      {visible.length === 0 ? (
        <span className="esp-ticker-empty">Waiting for live esports events…</span>
      ) : (
        <ul className="esp-ticker-track">
          {visible.map((event) => (
            <TickerItem key={event.id} event={event} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default memo(ActivityTickerBase);
