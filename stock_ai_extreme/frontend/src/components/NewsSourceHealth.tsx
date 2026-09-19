/**
 * Phase 8 — Source Health
 *
 * Spec K (source integrity) made visible.
 *
 * Every feed the desk knows about is listed with the result of its last real
 * fetch: HTTP status, item count and the error if it failed. Feeds that are
 * deliberately switched off are shown too, with the reason — a publisher that
 * blocks this server is a real coverage gap, and hiding it would imply
 * completeness the desk does not have.
 *
 * Nothing here is an estimate. If the last ingest has not run, the rows say
 * "Not fetched" rather than inventing a green tick.
 */

import { useState } from "react";
import BaseBadge from "./BaseBadge";
import {
  NewsSourceHealth as SourceHealth,
  NewsSourcesResponse,
  sourceStatusMeta,
} from "../lib/newsService";
import { formatRelativeTime } from "../utils/dateFormat";

interface NewsSourceHealthProps {
  data: NewsSourcesResponse | null;
  loading?: boolean;
  error?: string | null;
}

type Filter = "all" | "ok" | "problem";

function statusVariant(status: SourceHealth["status"]) {
  return sourceStatusMeta(status).variant;
}

export default function NewsSourceHealth({ data, loading, error }: NewsSourceHealthProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [expanded, setExpanded] = useState(false);

  const sources = data?.sources ?? [];
  const visible = sources.filter((source) => {
    if (filter === "ok") return source.status === "OK";
    if (filter === "problem") return source.status !== "OK";
    return true;
  });
  const shown = expanded ? visible : visible.slice(0, 6);

  return (
    <section className="news-sources" aria-labelledby="news-sources-heading">
      <header className="news-sources-head">
        <div>
          <h2 id="news-sources-heading">Source health</h2>
          <p>
            Real fetch results per publisher feed
            {data?.summary.last_ingest_at
              ? ` · last ingest ${formatRelativeTime(data.summary.last_ingest_at)}`
              : " · no ingest recorded yet"}
          </p>
        </div>

        {data && (
          <div className="news-sources-summary">
            <BaseBadge variant={data.summary.healthy_feeds > 0 ? "success" : "danger"}>
              {data.summary.healthy_feeds}/{data.summary.enabled_feeds} live
            </BaseBadge>
            <BaseBadge variant="default">{data.summary.items_available} items</BaseBadge>
            {data.summary.paid_sources_configured.length > 0 && (
              <BaseBadge variant="info">
                keys: {data.summary.paid_sources_configured.join(", ")}
              </BaseBadge>
            )}
          </div>
        )}
      </header>

      <div className="news-sources-filters" role="group" aria-label="Filter sources by status">
        {(["all", "ok", "problem"] as Filter[]).map((value) => (
          <button
            key={value}
            type="button"
            className={`news-sources-filter${filter === value ? " is-active" : ""}`}
            aria-pressed={filter === value}
            onClick={() => {
              setFilter(value);
              setExpanded(false);
            }}
          >
            {value === "all" ? `All (${sources.length})` : null}
            {value === "ok" ? `Live (${sources.filter((s) => s.status === "OK").length})` : null}
            {value === "problem" ? `Issues (${sources.filter((s) => s.status !== "OK").length})` : null}
          </button>
        ))}
      </div>

      {loading && (
        <div className="news-sources-list" aria-busy="true">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="news-sources-row loading">
              <div className="skeleton skeleton-text skeleton-text-sm" />
              <div className="skeleton skeleton-text skeleton-text-xs" />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <p className="news-sources-empty" role="status">
          Source health is unavailable — {error}
        </p>
      )}

      {!loading && !error && sources.length === 0 && (
        <p className="news-sources-empty" role="status">
          No feeds have been reported yet.
        </p>
      )}

      {!loading && !error && sources.length > 0 && (
        <>
          <ul className="news-sources-list">
            {shown.map((source) => {
              const meta = sourceStatusMeta(source.status);
              return (
                <li key={source.key} className="news-sources-row">
                  <span className={`news-sources-dot news-sources-dot-${statusVariant(source.status)}`} aria-hidden="true" />
                  <span className="news-sources-name">
                    {source.name}
                    <span className="news-sources-key">{source.region} · {source.key}</span>
                  </span>
                  <span className="news-sources-status">
                    <BaseBadge variant={meta.variant} size="sm">
                      {meta.label}
                    </BaseBadge>
                  </span>
                  <span className="news-sources-items">
                    {source.items}
                    <span className="sr-only"> items</span>
                  </span>
                  <span className="news-sources-detail">
                    {source.error
                      ? source.error
                      : source.http_status
                        ? `HTTP ${source.http_status}`
                        : "—"}
                  </span>
                </li>
              );
            })}
          </ul>

          {visible.length > 6 && (
            <button
              type="button"
              className="news-sources-toggle"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
            >
              {expanded ? "Show fewer feeds" : `Show all ${visible.length} feeds`}
            </button>
          )}
        </>
      )}

      <p className="news-sources-note">
        A feed that fails contributes no articles — no placeholder story is ever
        created to fill a gap. Disabled feeds are listed with the reason rather
        than removed.
      </p>
    </section>
  );
}
