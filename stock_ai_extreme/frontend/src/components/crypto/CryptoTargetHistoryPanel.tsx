/**
 * Phase 22D — Target event timeline (spec §11, §40).
 *
 * The append-only record of every real observation that changed a target's
 * state: creation, a candle that touched the level, a due date that elapsed, a
 * status change to REACHED/MISSED/EXPIRED, or an explicit user invalidation.
 *
 * Every row carries the source timestamp and the observed price from the
 * backend; the frontend never sets a target state (a target can only be
 * invalidated explicitly, and that call is logged here too).
 */
import type { TargetHistoryResponse } from "../../lib/crypto";
import { useCryptoTargetHistory } from "../../hooks/useCryptoQueries";
import { formatDateTime, formatPrice, NA } from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoWidgetError } from "./CryptoStates";

interface TargetEvent {
  id: number | string;
  target_id: string;
  symbol: string;
  event_type: string;
  status: string;
  observed_price: number | null;
  observed_at: string;
  source: string | null;
  detail: Record<string, unknown>;
}

function asEvent(row: Record<string, unknown>): TargetEvent {
  return {
    id: (row.id as number | string) ?? "",
    target_id: String(row.target_id ?? ""),
    symbol: String(row.symbol ?? ""),
    event_type: String(row.event_type ?? ""),
    status: String(row.status ?? ""),
    observed_price:
      typeof row.observed_price === "number" && Number.isFinite(row.observed_price)
        ? (row.observed_price as number)
        : null,
    observed_at: String(row.observed_at ?? ""),
    source: (row.source as string | null) ?? null,
    detail: (row.detail as Record<string, unknown>) ?? {},
  };
}

const EVENT_TONE: Record<string, string> = {
  REACHED: "live",
  TOUCH: "live",
  CROSSED: "live",
  MISSED: "warn",
  EXPIRED: "warn",
  INVALIDATED: "danger",
  ACTIVE: "native",
};

export interface CryptoTargetHistoryPanelProps {
  symbol: string;
  enabled?: boolean;
}

export function CryptoTargetHistoryPanel({
  symbol,
  enabled = true,
}: CryptoTargetHistoryPanelProps) {
  const history = useCryptoTargetHistory(symbol, enabled);
  const data = history.data as TargetHistoryResponse | undefined;
  const events = (data?.events ?? []).map(asEvent);

  return (
    <CryptoPanel
      title={`Target event timeline · ${symbol}`}
      badge={
        data ? (
          <span className="crypto-chip">
            {data.event_count} events · {data.target_count} targets
          </span>
        ) : undefined
      }
      className="crypto-target-history-panel"
    >
      {history.isLoading && !data && <CryptoEmpty reason="Reading the target event log…" />}
      {history.isError && (
        <CryptoWidgetError
          title="TARGET HISTORY UNAVAILABLE"
          message={(history.error as Error).message}
          onRetry={() => history.refetch()}
        />
      )}
      {!history.isLoading && !history.isError && events.length === 0 && (
        <CryptoEmpty
          title="NO VERIFIED DATA"
          reason="No target events have been recorded for this asset yet."
          hint="A row appears here only when a real candle observation or an explicit action changed a target's state."
        />
      )}
      {events.length > 0 && (
        <div className="crypto-table-wrap">
          <table className="crypto-table">
            <caption className="sr-only">
              Append-only target event log with real source timestamps
            </caption>
            <thead>
              <tr>
                <th scope="col">Observed at</th>
                <th scope="col">Event</th>
                <th scope="col">Status</th>
                <th scope="col">Target</th>
                <th scope="col">Observed price</th>
                <th scope="col">Source</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={`${event.id}`}>
                  <td>{formatDateTime(event.observed_at)}</td>
                  <td>
                    <span className={`crypto-chip ${EVENT_TONE[event.event_type] ?? ""}`}>
                      {event.event_type}
                    </span>
                  </td>
                  <td>{event.status || NA}</td>
                  <td className="crypto-mono dim" title={event.target_id}>
                    {shortId(event.target_id)}
                  </td>
                  <td>{event.observed_price != null ? formatPrice(event.observed_price) : NA}</td>
                  <td>{event.source ?? NA}</td>
                  <td className="dim">{summarizeDetail(event.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.note && <p className="crypto-note">{data.note}</p>}
    </CryptoPanel>
  );
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id || NA;
}

function summarizeDetail(detail: Record<string, unknown>): string {
  const parts: string[] = [];
  const price = detail.target_price ?? detail.threshold ?? null;
  if (typeof price === "number") parts.push(`level ${formatPrice(price)}`);
  const direction = detail.direction;
  if (typeof direction === "string" && direction) parts.push(direction);
  const touches = detail.touch_count ?? detail.touches;
  if (typeof touches === "number") parts.push(`${touches} touch${touches === 1 ? "" : "es"}`);
  const reason = detail.reason;
  if (typeof reason === "string" && reason) parts.push(reason);
  if (parts.length === 0) {
    const keys = Object.keys(detail);
    return keys.length > 0 ? keys.join(", ") : NA;
  }
  return parts.join(" · ");
}

export default CryptoTargetHistoryPanel;
