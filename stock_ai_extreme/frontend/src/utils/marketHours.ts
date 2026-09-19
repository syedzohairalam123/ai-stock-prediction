/**
 * PSE (Pakistan Stock Exchange) trading session clock.
 *
 * The exchange trades Monday–Friday, 09:30–15:30 Pakistan Standard Time
 * (UTC+05:00, no daylight saving). This is a *schedule* reading, not a feed —
 * holidays are not modelled — so the UI labels it as the session window rather
 * than claiming live market state. Once an answer comes back, the backend's own
 * `market_status` (which the context builder records per request) supersedes it.
 */

export type PseSessionStatus = 'OPEN' | 'CLOSED' | 'WEEKEND';

const PKT_OFFSET_MINUTES = 5 * 60;
const SESSION_OPEN_MINUTES = 9 * 60 + 30; // 09:30 PKT
const SESSION_CLOSE_MINUTES = 15 * 60 + 30; // 15:30 PKT

export function getPseSessionStatus(now: Date = new Date()): PseSessionStatus {
  // Shift the instant into PKT and read it back in UTC fields.
  const pkt = new Date(now.getTime() + PKT_OFFSET_MINUTES * 60_000);
  const weekday = pkt.getUTCDay();
  if (weekday === 0 || weekday === 6) return 'WEEKEND';

  const minutes = pkt.getUTCHours() * 60 + pkt.getUTCMinutes();
  return minutes >= SESSION_OPEN_MINUTES && minutes < SESSION_CLOSE_MINUTES ? 'OPEN' : 'CLOSED';
}

