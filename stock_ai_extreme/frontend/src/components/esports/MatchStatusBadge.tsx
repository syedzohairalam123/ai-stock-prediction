/**
 * Phase 21B §4 — living match status.
 *
 * Text + icon + colour, so the state is never carried by colour alone. The
 * label comes from the source's own status value via `statusMeta`, and the
 * icon is decorative (`aria-hidden`) because the text already names the state.
 */
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  HelpCircle,
  PauseCircle,
  Radio,
  Timer,
} from "lucide-react";

import { statusMeta, type MatchStatusValue } from "../../lib/esports";

const ICONS: Record<MatchStatusValue, typeof Radio> = {
  LIVE: Radio,
  PAUSED: PauseCircle,
  MAP_BREAK: Timer,
  UPCOMING: CalendarClock,
  SCHEDULED: CalendarClock,
  COMPLETED: CheckCircle2,
  CANCELLED: AlertTriangle,
  POSTPONED: AlertTriangle,
  UNKNOWN: HelpCircle,
};

export default function MatchStatusBadge({
  status,
  size = "md",
}: {
  status: string | null | undefined;
  size?: "sm" | "md";
}) {
  const meta = statusMeta(status);
  const Icon = ICONS[(status || "UNKNOWN").toUpperCase() as MatchStatusValue] ?? HelpCircle;
  return (
    <span
      className={`esp-status esp-status--${meta.tone} esp-status--${size}`}
      data-status={(status || "UNKNOWN").toUpperCase()}
    >
      <Icon size={size === "sm" ? 11 : 13} aria-hidden="true" className={meta.tone === "live" ? "esp-status-pulse" : ""} />
      <span>{meta.label}</span>
    </span>
  );
}
