/**
 * Phase 19 §9 — the Market Discovery page (`/discover`).
 *
 * Four feeds (Trending · New · Popular · Recently updated) over one unified
 * entity model, switchable without a page reload (React Query + URL state),
 * with the full §7 filter set, tag navigation (§13), personalization (§14),
 * source health, and a transparent view of the scoring engine (§4).
 *
 * Honesty rules visible on this page:
 *  - every unavailable metric renders "N/A";
 *  - the source panel shows per-source status and failures instead of a
 *    silent empty grid;
 *  - the engine panel publishes the weights and saturations actually used;
 *  - personalization is opt-in and only ever uses explicit actions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import BaseBadge from "../components/BaseBadge";
import DiscoveryCard from "../components/discover/DiscoveryCard";
import DiscoveryFilters, { type DiscoveryFiltersValue } from "../components/discover/DiscoveryFilters";
import { useDiscoveryFeed, useDiscoveryTaxonomy, useRecordDiscoveryEvent } from "../hooks/useDiscoveryQueries";
import {
  MODE_DESCRIPTIONS,
  MODE_LABELS,
  NA,
  getPreferredCategories,
  togglePreferredCategory,
  type DiscoverableEntity,
  type DiscoveryMode,
  type DiscoveryQueryParams,
  type EntityType,
} from "../lib/discovery";

const MODES: DiscoveryMode[] = ["trending", "new", "popular", "recent"];
const PAGE_SIZE = 24;

const RANGE_MS: Record<Exclude<DiscoveryFiltersValue["range"], "">, number> = {
  "24h": 24 * 3600_000,
  "7d": 7 * 24 * 3600_000,
  "30d": 30 * 24 * 3600_000,
};

function isMode(value: string | null): value is DiscoveryMode {
  return value !== null && (MODES as string[]).includes(value);
}

export default function DiscoverPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const recordEvent = useRecordDiscoveryEvent();

  // ---- filters, deep-linked through the URL (shareable discovery views) ----
  const mode: DiscoveryMode = isMode(searchParams.get("mode")) ? (searchParams.get("mode") as DiscoveryMode) : "trending";
  const filters: DiscoveryFiltersValue = {
    category: searchParams.get("category"),
    tag: searchParams.get("tag"),
    type: (searchParams.get("type") as EntityType | null) ?? null,
    status: searchParams.get("status"),
    source: searchParams.get("source"),
    range: (searchParams.get("range") as DiscoveryFiltersValue["range"]) ?? "",
    q: searchParams.get("q") ?? "",
    personalize: searchParams.get("personalize") === "1",
  };
  const [preferred, setPreferred] = useState<string[]>(() => getPreferredCategories());
  const [page, setPage] = useState(0);

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(patch).forEach(([key, value]) => {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      });
      setSearchParams(next, { replace: true });
      setPage(0);
    },
    [searchParams, setSearchParams]
  );

  const setFilters = useCallback(
    (patch: Partial<DiscoveryFiltersValue>) => {
      const mapped: Record<string, string | null> = {};
      if ("category" in patch) mapped.category = patch.category ?? null;
      if ("tag" in patch) mapped.tag = patch.tag ?? null;
      if ("type" in patch) mapped.type = patch.type ?? null;
      if ("status" in patch) mapped.status = patch.status ?? null;
      if ("source" in patch) mapped.source = patch.source ?? null;
      if ("range" in patch) mapped.range = patch.range || null;
      if ("q" in patch) mapped.q = patch.q || null;
      if ("personalize" in patch) mapped.personalize = patch.personalize ? "1" : null;
      patchParams(mapped);
    },
    [patchParams]
  );

  const clearFilters = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    ["category", "tag", "type", "status", "source", "range", "q", "personalize"].forEach((k) =>
      next.delete(k)
    );
    setSearchParams(next, { replace: true });
    setPage(0);
  }, [searchParams, setSearchParams]);

  const hasActiveFilters = Boolean(
    filters.category ||
      filters.tag ||
      filters.type ||
      filters.status ||
      filters.source ||
      filters.range ||
      filters.q
  );

  // ---- query params for the feed -----------------------------------------
  const since = useMemo(() => {
    if (!filters.range) return null;
    return new Date(Date.now() - RANGE_MS[filters.range]).toISOString();
  }, [filters.range]);

  const queryParams: DiscoveryQueryParams = useMemo(
    () => ({
      mode,
      category: filters.category,
      tag: filters.tag,
      type: filters.type,
      status: filters.status,
      source: filters.source,
      since,
      q: filters.q || null,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      personalize: filters.personalize,
      prefer: filters.personalize ? preferred : [],
    }),
    [mode, filters, since, page, preferred]
  );

  const feedQuery = useDiscoveryFeed(queryParams);
  const taxonomyQuery = useDiscoveryTaxonomy();
  const feed = feedQuery.data;

  // ---- accumulated grid (load-more appends instead of replacing) ---------
  const [visible, setVisible] = useState<DiscoverableEntity[]>([]);
  useEffect(() => {
    if (!feed) return;
    if (feed.offset === 0) {
      setVisible(feed.items);
      return;
    }
    setVisible((previous) => {
      const known = new Set(previous.map((item) => item.id));
      return [...previous, ...feed.items.filter((item) => !known.has(item.id))];
    });
  }, [feed]);

  const handleOpen = useCallback(
    (entity: DiscoverableEntity) => {
      recordEvent.mutate({ entityId: entity.id, kind: "view" });
    },
    [recordEvent]
  );

  const handleTogglePreferred = useCallback(
    (category: string) => setPreferred(togglePreferredCategory(category)),
    []
  );

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["discovery"] });
  }, [queryClient]);

  const firstLoad = feedQuery.isPending && !feed;
  const engine = feed?.engine;
  const personalization = feed?.personalization;

  return (
    <main className="disc-page">
      <div className="psx-page-head">
        <div>
          <p>Phase 19 · Market discovery</p>
          <h1>Discover</h1>
        </div>
        <div className="disc-head-actions">
          {feed && (
            <BaseBadge variant="info">
              {feed.total} {feed.total === 1 ? "entity" : "entities"}
            </BaseBadge>
          )}
          <button className="disc-refresh" onClick={refresh} disabled={feedQuery.isFetching}>
            <span className={feedQuery.isFetching ? "disc-spin" : ""} aria-hidden="true">
              ⟳
            </span>
            Refresh
          </button>
        </div>
      </div>

      {/* Mode tabs — switching never reloads the page (spec §9) */}
      <div className="disc-modes" role="tablist" aria-label="Discovery feed mode">
        {MODES.map((candidate) => (
          <button
            key={candidate}
            role="tab"
            aria-selected={mode === candidate}
            className={`disc-mode ${mode === candidate ? "active" : ""}`}
            onClick={() => patchParams({ mode: candidate === "trending" ? null : candidate })}
          >
            {MODE_LABELS[candidate]}
          </button>
        ))}
      </div>
      <p className="disc-mode-desc">{MODE_DESCRIPTIONS[mode]}</p>

      <DiscoveryFilters
        value={filters}
        taxonomy={taxonomyQuery.data}
        preferred={preferred}
        onChange={setFilters}
        onTogglePreferred={handleTogglePreferred}
        onClear={clearFilters}
      />

      {/* Honest meta strip: source health, exclusions, personalization */}
      <div className="disc-meta-strip">
        {(feed?.sources ?? []).map((source) => (
          <span
            key={source.source}
            className={`disc-source-chip ${source.status.toLowerCase()}`}
            title={
              source.reason ??
              `${source.count}${source.requested ? `/${source.requested}` : ""} entities${
                source.failed.length ? ` · failed: ${source.failed.slice(0, 6).join(", ")}` : ""
              }`
            }
          >
            {source.source} · {source.status} · {source.count}
          </span>
        ))}
        {mode === "new" && (feed?.excludedNoCreatedAt ?? 0) > 0 && (
          <span className="disc-note-chip">
            {feed?.excludedNoCreatedAt} entities excluded — no real creation timestamp (spec §2)
          </span>
        )}
        {filters.personalize && (
          <span className="disc-note-chip personal" title={personalization?.note}>
            Personalized: {personalization?.signals.join(", ")} · +{((personalization?.boost ?? 0) * 100).toFixed(0)}% rank boost
          </span>
        )}
      </div>

      <div className="disc-layout">
        <section className="disc-results" aria-label="Discovery results">
          {feedQuery.isError && !feed && (
            <div className="disc-error" role="alert">
              <p>Discovery data could not be loaded: {(feedQuery.error as Error).message}</p>
              <button onClick={refresh}>Try again</button>
            </div>
          )}

          {firstLoad && (
            <div className="disc-grid" aria-hidden="true">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="disc-card skeleton">
                  <div className="skeleton" style={{ height: 18, width: "60%", marginBottom: 10 }} />
                  <div className="skeleton" style={{ height: 14, width: "85%", marginBottom: 8 }} />
                  <div className="skeleton" style={{ height: 34, width: "100%" }} />
                </div>
              ))}
            </div>
          )}

          {!firstLoad && visible.length === 0 && !feedQuery.isError && (
            <div className="disc-empty" role="status">
              <p>
                {hasActiveFilters
                  ? "No entities match these filters."
                  : mode === "new"
                    ? "No entity currently publishes a real creation timestamp."
                    : "No entities to show yet."}
              </p>
              {hasActiveFilters && (
                <button onClick={clearFilters}>Clear filters</button>
              )}
            </div>
          )}

          {visible.length > 0 && (
            <>
              <div className="disc-grid">
                {visible.map((entity) => (
                  <DiscoveryCard
                    key={entity.id}
                    entity={entity}
                    mode={mode}
                    onTagClick={(tag) => setFilters({ tag: filters.tag === tag ? null : tag })}
                    onCategoryClick={(category) =>
                      setFilters({ category: filters.category === category ? null : category })
                    }
                    onOpen={handleOpen}
                  />
                ))}
              </div>

              <div className="disc-pager">
                <span>
                  Showing {visible.length} of {feed?.total ?? 0}
                  {feed?.recordedSearches ? ` · ${feed.recordedSearches} search match(es) recorded` : ""}
                  {feed?.sampledObservations ? ` · ${feed.sampledObservations} observation(s) sampled` : ""}
                </span>
                {feed?.hasMore && (
                  <button
                    onClick={() => setPage((current) => current + 1)}
                    disabled={feedQuery.isFetching}
                  >
                    Load more
                  </button>
                )}
              </div>
            </>
          )}
        </section>

        <aside className="disc-aside" aria-label="Discovery context">
          {/* Source health — failures are shown, never hidden (spec §17) */}
          <details className="disc-panel" open>
            <summary>Data sources</summary>
            <ul className="disc-source-list">
              {(feed?.sources ?? []).map((source) => (
                <li key={source.source} className={source.status.toLowerCase()}>
                  <div className="disc-source-head">
                    <strong>{source.source}</strong>
                    <span>{source.status}</span>
                  </div>
                  <p>
                    {source.count}
                    {source.requested ? ` of ${source.requested}` : ""} entities
                    {source.failed.length > 0 && ` · ${source.failed.length} failed`}
                  </p>
                  {source.reason && <p className="disc-source-reason">{source.reason}</p>}
                  {source.failed.length > 0 && (
                    <p className="disc-source-reason">Failed: {source.failed.slice(0, 10).join(", ")}</p>
                  )}
                </li>
              ))}
              {!feed?.sources?.length && <li className="muted">Waiting for the first collection pass…</li>}
            </ul>
          </details>

          {/* Trending topics from the live corpus (tag navigation, §13) */}
          <details className="disc-panel" open>
            <summary>Top sub-tags</summary>
            <div className="disc-aside-tags">
              {(taxonomyQuery.data?.tags ?? []).slice(0, 24).map((tag) => (
                <button
                  key={tag.name}
                  className={`disc-tag-chip ${filters.tag === tag.name ? "active" : ""}`}
                  onClick={() => setFilters({ tag: filters.tag === tag.name ? null : tag.name })}
                >
                  {tag.name} <em>{tag.count}</em>
                </button>
              ))}
              {!taxonomyQuery.data?.tags?.length && <span className="muted">{NA}</span>}
            </div>
          </details>

          {/* Scoring transparency: weights + saturations actually in use */}
          <details className="disc-panel">
            <summary>How scores are computed</summary>
            {engine && (
              <>
                <ul className="disc-weight-list">
                  {Object.entries(engine.trendWeights).map(([name, weight]) => (
                    <li key={name}>
                      <span>{name}</span>
                      <span className="disc-weight-bar">
                        <i style={{ width: `${(weight * 100).toFixed(0)}%` }} />
                      </span>
                      <span>{weight.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
                <p className="disc-panel-note">{engine.note}</p>
                <p className="disc-panel-note">
                  Recency half-life: {engine.recencyHalfLifeHours}h. Components with no measurement are
                  excluded and the remaining weights renormalized — every card lists which.
                </p>
              </>
            )}
            {(feed?.notes ?? []).map((note) => (
              <p key={note} className="disc-panel-note">
                {note}
              </p>
            ))}
          </details>

          {personalization?.note && (
            <details className="disc-panel">
              <summary>Personalization</summary>
              <p className="disc-panel-note">{personalization.note}</p>
              <p className="disc-panel-note">
                Toggle it on with the <strong>Personalize</strong> switch, and star categories to pin
                them. Stored locally in this browser.
              </p>
            </details>
          )}
        </aside>
      </div>

      <footer className="disc-page-foot">
        <p>
          Real sources only: live quotes (provider chain), Polymarket public forecast markets, and the
          ingested news corpus. Popularity counts are events this application actually recorded — a
          metric no source publishes shows as {NA}. Discovery ranks and labels data; it is not
          investment advice and never predicts an outcome.
        </p>
      </footer>
    </main>
  );
}
