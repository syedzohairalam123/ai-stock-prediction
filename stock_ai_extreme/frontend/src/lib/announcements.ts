/**
 * Phase 4 — PSX Announcements, Filings & AI Intelligence (frontend data layer).
 *
 * Architecture mirrors the backend contract 1:1:
 *   - AnnouncementService  : typed fetch + normalizers for /api/psx/announcements
 *   - AIAnalysisService    : client-side presentation of the labeled AI analysis
 *                            (event → badge meta, sentiment → icon+label, structured rows)
 *
 * HONESTY CONTRACT (enforced end-to-end):
 *   - `sourceStatus` LIVE/UNAVAILABLE/SIMULATED is always surfaced to the user,
 *     never hidden. The UI can render a real feed vs demo feed distinctly.
 *   - `structured` fields are `string | null`: null means "not in the source
 *     filing" and the UI shows nothing — never a fabricated placeholder.
 *   - AI-generated content is always rendered with a visible AI label + disclaimer.
 */

import { getJSON } from "./api";

// ---------------------------------------------------------------------------
// Types (mirror backend app/announcements.py)
// ---------------------------------------------------------------------------

export const ANN_EVENTS = [
  "RIGHTS_ISSUE", "BONUS_SHARES", "DIVIDEND", "AGM", "EGM",
  "INSIDER_SALE", "INSIDER_PURCHASE", "MANAGEMENT_CHANGE", "BOARD_CHANGE",
  "FINANCIAL_RESULTS", "PROFIT_WARNING", "ACQUISITION", "MERGER",
  "CONTRACT_AWARD", "CORPORATE_ACTION", "REGULATORY_NOTICE", "OTHER",
] as const;
export type AnnEvent = (typeof ANN_EVENTS)[number];

export const ANN_SENTIMENTS = ["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"] as const;
export type AnnSentiment = (typeof ANN_SENTIMENTS)[number];

export type AnnSource = "company" | "simulated";
export type AnnSourceStatus = "LIVE" | "UNAVAILABLE" | "SIMULATED" | "STALE";

export interface SentimentMeta {
  icon: string;
  label: string;
}

export interface StructuredEventInfo {
  eps: string | null;
  dividend: string | null;
  bonus: string | null;
  rights: string | null;
  person: string | null;
  action: string | null;
  shares: string | null;
  price: string | null;
  total_value: string | null;
  effective_date: string | null;
  book_closure_from: string | null;
  book_closure_to: string | null;
}

export interface Announcement {
  id: string;
  company: string;
  ticker: string | null;
  ticker_confident: boolean;
  published: string; // ISO date
  title: string;
  body: string;
  event: AnnEvent;
  sentiment: AnnSentiment;
  sentiment_meta: SentimentMeta;
  highlights: string[];
  structured: StructuredEventInfo;
  analysis_engine: string;
  source: AnnSource;
  source_status: AnnSourceStatus;
  source_url: string;
  pdf_url: string | null;
  image_url: string | null;
}

export interface AnnouncementsPage {
  items: Announcement[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_more: boolean;
  next_page: number | null;
  prev_page: number | null;
  source: AnnSource;
  source_status: AnnSourceStatus;
  mode: string;
  fetched_at: string | null;
  ai_disclaimer: string;
  source_disclaimer: string;
  error?: string;
}

export interface AnnouncementDetail {
  item: Announcement;
  source: AnnSource;
  source_status: AnnSourceStatus;
  fetched_at: string | null;
  ai_disclaimer: string;
  source_disclaimer: string;
}

export interface AnnouncementFilters {
  source?: AnnSource;
  event?: string;      // AnnEvent | "ALL"
  sentiment?: string;  // AnnSentiment | "ALL"
  ticker?: string;
  company?: string;
  search?: string;
  dateFrom?: string;   // ISO yyyy-mm-dd
  dateTo?: string;
  page?: number;
  pageSize?: number;
}

// ---------------------------------------------------------------------------
// Presentation metadata for events & sentiments (icons — never color alone)
// ---------------------------------------------------------------------------

export const EVENT_META: Record<AnnEvent, { icon: string; label: string }> = {
  RIGHTS_ISSUE: { icon: "◐", label: "Rights Issue" },
  BONUS_SHARES: { icon: "⊕", label: "Bonus Shares" },
  DIVIDEND: { icon: "₨", label: "Dividend" },
  AGM: { icon: "🏛", label: "AGM" },
  EGM: { icon: "🏛", label: "EGM" },
  INSIDER_SALE: { icon: "↗", label: "Insider Sale" },
  INSIDER_PURCHASE: { icon: "↘", label: "Insider Purchase" },
  MANAGEMENT_CHANGE: { icon: "👤", label: "Management Change" },
  BOARD_CHANGE: { icon: "⚑", label: "Board Change" },
  FINANCIAL_RESULTS: { icon: "📊", label: "Financial Results" },
  PROFIT_WARNING: { icon: "⚠", label: "Profit Warning" },
  ACQUISITION: { icon: "⤴", label: "Acquisition" },
  MERGER: { icon: "⇄", label: "Merger" },
  CONTRACT_AWARD: { icon: "✔", label: "Contract Award" },
  CORPORATE_ACTION: { icon: "⚙", label: "Corporate Action" },
  REGULATORY_NOTICE: { icon: "§", label: "Regulatory Notice" },
  OTHER: { icon: "•", label: "Other" },
};

export const SENTIMENT_UI: Record<AnnSentiment, SentimentMeta> = {
  POSITIVE: { icon: "▲", label: "Positive sentiment" },
  NEGATIVE: { icon: "▼", label: "Negative sentiment" },
  MIXED: { icon: "◆", label: "Mixed sentiment" },
  NEUTRAL: { icon: "●", label: "Neutral sentiment" },
};

/** Which structured fields to render, in display order, with human labels. */
const STRUCTURED_FIELD_DEFS: { key: keyof StructuredEventInfo; label: string }[] = [
  { key: "person", label: "Person" },
  { key: "action", label: "Action" },
  { key: "shares", label: "Shares" },
  { key: "price", label: "Price" },
  { key: "total_value", label: "Total Value" },
  { key: "effective_date", label: "Effective Date" },
  { key: "eps", label: "EPS" },
  { key: "dividend", label: "Dividend" },
  { key: "bonus", label: "Bonus" },
  { key: "rights", label: "Rights" },
  { key: "book_closure_from", label: "Book Closure From" },
  { key: "book_closure_to", label: "Book Closure To" },
];

/** Only fields present in the source are returned — never fabricate rows.
 *
 * `eventLabel` (when supplied) prepends the classified EVENT row, but only if
 * there is at least one other extracted field — so the structured block stays a
 * set of real facts rather than becoming boilerplate on every filing. */
export function structuredRows(
  info: StructuredEventInfo,
  eventLabel?: string
): { label: string; value: string }[] {
  const rows = STRUCTURED_FIELD_DEFS
    .filter(({ key }) => {
      const v = info[key];
      return v !== null && v !== undefined && String(v).trim() !== "";
    })
    .map(({ key, label }) => ({ label, value: String(info[key]) }));
  if (eventLabel && rows.length > 0) {
    return [{ label: "Event", value: eventLabel }, ...rows];
  }
  return rows;
}

export function eventMeta(event: AnnEvent): { icon: string; label: string } {
  return EVENT_META[event] ?? EVENT_META.OTHER;
}

export function sentimentMeta(sentiment: AnnSentiment): SentimentMeta {
  return SENTIMENT_UI[sentiment] ?? SENTIMENT_UI.NEUTRAL;
}

// ---------------------------------------------------------------------------
// AnnouncementService — typed API access (single fetch funnel)
// ---------------------------------------------------------------------------

export const AnnouncementService = {
  async fetchPage(filters: AnnouncementFilters = {}, signal?: AbortSignal): Promise<AnnouncementsPage> {
    const p = new URLSearchParams();
    p.set("source", filters.source ?? "company");
    if (filters.event && filters.event !== "ALL") p.set("event", filters.event);
    if (filters.sentiment && filters.sentiment !== "ALL") p.set("sentiment", filters.sentiment);
    if (filters.ticker) p.set("ticker", filters.ticker.toUpperCase());
    if (filters.company) p.set("company", filters.company);
    if (filters.search?.trim()) p.set("search", filters.search.trim());
    if (filters.dateFrom) p.set("date_from", filters.dateFrom);
    if (filters.dateTo) p.set("date_to", filters.dateTo);
    p.set("page", String(filters.page ?? 1));
    p.set("page_size", String(filters.pageSize ?? 20));
    return getJSON<AnnouncementsPage>(`/api/psx/announcements?${p.toString()}`, undefined);
  },

  /** Single announcement permalink (`/announcements/:id`). The backend searches
   * the live feed first, then the labelled demo dataset, and 404s honestly when
   * the id has rolled off the feed — it never fabricates a record. */
  async fetchById(id: string): Promise<AnnouncementDetail> {
    return getJSON<AnnouncementDetail>(`/api/psx/announcements/${encodeURIComponent(id)}`);
  },
};

/** Alias matching the task's requested architecture name. */
export const AIAnalysisService = {
  eventMeta,
  sentimentMeta,
  structuredRows,
};

// ---------------------------------------------------------------------------
// Formatting helpers (PSX-specific; no overlap with psxMarket.ts)
// ---------------------------------------------------------------------------

export function fmtAnnDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Honest relative label derived from the filing date (the feed carries a
 * date, not a clock time — we never invent one). */
export function fmtAnnRelative(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (isNaN(d.getTime())) return "";
  const days = Math.round((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months} month${months === 1 ? "" : "s"} ago`;
  const years = Math.round(months / 12);
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

export function fmtFetchedAt(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
