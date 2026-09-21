/**
 * Phase 17 (spec §4) — breaking ticker.
 *
 * A compact strip of the highest-scoring events in the window. Each entry shows
 * the publisher's own timestamp age, so the strip can never imply a story is
 * newer than it is. Clicking an entry selects it in the feed.
 *
 * The animation is CSS-driven and pauses on hover/focus, which keeps it readable
 * (and stops it stealing focus in an accessibility sense) without any timers.
 */
import { useMemo } from "react";
import { Radio, Zap } from "lucide-react";
import { levelClass, timeAgo, type BreakingNewsEvent, type StreamTransport } from "../../lib/breakingNews";

interface Props {
  items: BreakingNewsEvent[];
  onSelect?: (event: BreakingNewsEvent) => void;
  transport?: StreamTransport;
  max?: number;
}

const TRANSPORT_LABEL: Record<StreamTransport, string> = {
  websocket: "WebSocket",
  sse: "Server-Sent Events",
  polling: "polling fallback",
  connecting: "connecting…",
};

export default function BreakingNewsTicker({ items, onSelect, transport, max = 12 }: Props) {
  const entries = useMemo(() => items.slice(0, max), [items, max]);

  if (entries.length === 0) {
    return (
      <div className="bn-ticker bn-ticker-empty">
        <Zap size={14} aria-hidden />
        <span>No breaking events in the current window.</span>
      </div>
    );
  }

  return (
    <div className="bn-ticker" role="marquee" aria-label="Breaking news ticker">
      <span className="bn-ticker-tag">
        <Zap size={13} aria-hidden /> BREAKING
      </span>
      <div className="bn-ticker-viewport">
        <div className="bn-ticker-track">
          {[0, 1].map((pass) => (
            <ul key={pass} aria-hidden={pass === 1} className="bn-ticker-list">
              {entries.map((event) => (
                <li key={`${pass}-${event.id}`}>
                  <button type="button" className="bn-ticker-item" onClick={() => onSelect?.(event)}>
                    <span className={`bn-ticker-level ${levelClass(event.breaking_level)}`}>{event.breaking_level}</span>
                    <span className="bn-ticker-title">{event.title}</span>
                    <span className="bn-ticker-meta">
                      {event.publisher || "publisher unavailable"} · {event.time_ago ?? timeAgo(event.published_at)}
                      {event.cluster_size > 1 && ` · ${event.cluster_size} sources`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>
      {transport && (
        <span className="bn-ticker-transport" title="Live transport in use">
          <Radio size={12} aria-hidden /> {TRANSPORT_LABEL[transport]}
        </span>
      )}
    </div>
  );
}
