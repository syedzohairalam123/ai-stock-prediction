/**
 * Phase 21B §16 — WebSocket connection status.
 *
 * Shows CONNECTED / RECONNECTING / DISCONNECTED. When the stream is down the
 * banner states "Live connection lost" so no stale value is mistaken for a
 * live one, and offers a manual reconnect.
 */
import { AlertTriangle, RefreshCw, Wifi, WifiOff } from "lucide-react";

import { relTime } from "../../lib/esports";
import { useEsportsStore } from "../../store/useEsportsStore";

export default function ConnectionStatus({ onReconnect }: { onReconnect?: () => void }) {
  const connection = useEsportsStore((s) => s.connection);
  const lastMessageAt = useEsportsStore((s) => s.lastMessageAt);

  const lost = connection === "disconnected" || connection === "reconnecting";
  const Icon = connection === "connected" ? Wifi : connection === "connecting" ? Wifi : WifiOff;

  return (
    <div
      className={`esp-conn esp-conn--${connection}`}
      role="status"
      aria-live="polite"
      title={lastMessageAt ? `Last message ${relTime(lastMessageAt)}` : "No messages yet"}
    >
      <Icon size={13} aria-hidden="true" />
      <span className="esp-conn-label">
        {connection === "connected"
          ? "Live stream connected"
          : connection === "connecting"
            ? "Connecting to live stream…"
            : connection === "reconnecting"
              ? "Live connection lost — reconnecting…"
              : "Live connection lost"}
      </span>
      {lost && <AlertTriangle size={12} aria-hidden="true" className="esp-conn-warn" />}
      {onReconnect && lost && (
        <button type="button" className="esp-conn-retry" onClick={onReconnect}>
          <RefreshCw size={12} aria-hidden="true" /> Reconnect
        </button>
      )}
    </div>
  );
}
