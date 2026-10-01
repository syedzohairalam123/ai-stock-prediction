/**
 * Phase 22A — crypto display helpers.
 *
 * One place for price/volume/time formatting and status tone, so no component
 * re-implements them (spec §69). Every helper returns an explicit `N/A` for a
 * genuinely unavailable value — never `0`, `--` ambiguity or an empty string.
 */
import type { DataStatusValue, QualityValue } from "./crypto";

export const NA = "N/A";

export type StatusTone = "live" | "recent" | "delayed" | "stale" | "historical" | "unavailable";

/** Tone for a freshness label (spec §54). */
export function statusTone(status: string | null | undefined): StatusTone {
  switch ((status ?? "").toUpperCase()) {
    case "LIVE":
      return "live";
    case "RECENT":
      return "recent";
    case "DELAYED":
      return "delayed";
    case "STALE":
      return "stale";
    case "HISTORICAL":
      return "historical";
    default:
      return "unavailable";
  }
}

export const QUALITY_TONE: Record<QualityValue, StatusTone> = {
  HIGH: "live",
  MEDIUM: "recent",
  LOW: "delayed",
  UNAVAILABLE: "unavailable",
};

/**
 * Price formatter with magnitude-aware precision: a $0.00001234 token and an
 * $84,000 coin must both stay readable without ever rounding to a fake 0.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NA;
  const abs = Math.abs(value);
  let digits: number;
  if (abs === 0) digits = 2;
  else if (abs < 0.0001) digits = 8;
  else if (abs < 0.01) digits = 6;
  else if (abs < 1) digits = 5;
  else if (abs < 100) digits = 3;
  else if (abs < 10_000) digits = 2;
  else digits = 2;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: Math.min(digits, 2),
    maximumFractionDigits: digits,
  });
}

/** Compact magnitude for volume/quote-volume (1.6B, 24.3M, 810.2K). */
export function formatCompact(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NA;
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(digits)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(digits)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(digits)}K`;
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** Signed percentage with an explicit +/- and sign-based tone class. */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NA;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** Percentage without a forced sign (used for volatility / spread). */
export function formatPercentPlain(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NA;
  return `${value.toFixed(digits)}%`;
}

export function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "mut";
  return value >= 0 ? "pos" : "neg";
}

/**
 * Local-timezone display for a UTC/ISO timestamp (spec §13). The backend stores
 * UTC; the browser renders the viewer's own timezone.
 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Honest relative age from the source (never invents "now"). */
export function relTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return NA;
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Duration in a compact human form for gaps / bar sizes. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return NA;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds < 2_592_000) return `${(seconds / 86400).toFixed(1)}d`;
  if (seconds < 31_536_000) return `${(seconds / 2_592_000).toFixed(1)}mo`;
  return `${(seconds / 31_536_000).toFixed(1)}y`;
}

/** Label for a value origin so a MODELLED/CALCULATED number is never hidden (§99). */
export function originLabel(origin: string | null | undefined): string {
  switch ((origin ?? "").toUpperCase()) {
    case "SOURCE":
      return "source";
    case "CALCULATED":
      return "calculated";
    case "MODELLED":
      return "modelled";
    case "DERIVED":
      return "derived";
    default:
      return "unknown";
  }
}

/** Freshness meta chip class name shared with the rest of the terminal. */
export function statusChipClass(status: DataStatusValue | string | null | undefined): string {
  return `freshness ${statusTone(status)}`;
}
