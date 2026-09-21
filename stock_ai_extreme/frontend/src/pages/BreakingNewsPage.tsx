/**
 * Phase 17 — Real-Time Breaking News + Trending Topics + Market Impact
 * Intelligence.
 *
 * This is *not* a rebuild of Phase 8's news page. Phase 8 answers "what has been
 * published"; this desk answers three different questions:
 *
 * 1. Which of the last-24-hour events are genuinely breaking (scored, clustered,
 *    not just "latest")?
 * 2. What happened in the market around each of them — only where real
 *    timestamped bars exist on both sides of publication?
 * 3. Which topics are actually accelerating right now, by measurable activity?
 *
 * Everything on the page is derived from real publisher timestamps, real stored
 * articles, real Phase 14 trade history and real provider bars. Where a number
 * could not be measured, the UI says so — it never fills the gap with a
 * plausible-looking value.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Database,
  Flame,
  Layers,
  Newspaper,
  Radio,
  RefreshCw,
  ShieldCheck,
  Zap,
} from "lucide-react";
import BreakingNewsFeed from "../components/breakingNews/BreakingNewsFeed";
import BreakingNewsTicker from "../components/breakingNews/BreakingNewsTicker";
import HotTopicsSidebar from "../components/breakingNews/HotTopicsSidebar";
import SourceList from "../components/breakingNews/SourceList";
import TopicCard from "../components/breakingNews/TopicCard";
import {
  fetchBreakingFeed,
  fetchBreakingHealth,
  fetchClusters,
  fetchSources,
  fetchTopics,
  fixed,
  formatDateTime,
  refreshBreakingNews,
  timeAgo,
  useBreakingNewsStream,
  type BreakingFeedResponse,
  type BreakingHealth,
  type BreakingLevel,
  type BreakingNewsEvent,
  type Cluster,
  type IngestReport,
  type SourcesResponse,
  type TopicsResponse,
} from "../lib/breakingNews";

type View = "feed" | "topics" | "clusters" | "sources";

const VIEWS: Array<{ key: View; label: string; icon: typeof Newspaper }> = [
  { key: "feed", label: "Breaking feed", icon: Zap },
  { key: "topics", label: "Hot topics", icon: Flame },
  { key: "clusters", label: "Event clusters", icon: Layers },
  { key: "sources", label: "Sources & reliability", icon: ShieldCheck },
];

const HOUR_CHOICES = [6, 12, 24, 48, 72];
const LEVEL_CHOICES: Array<{ key: BreakingLevel | "ALL"; label: string }> = [
  { key: "ALL", label: "All levels" },
  { key: "BREAKING", label: "Breaking" },
  { key: "SIGNIFICANT", label: "Significant" },
];

/**
 * Policy actors matter for ranking but have no price series, so they are never
 * offered as impact targets (mirrors `entities.NON_PRICEABLE_ENTITIES`).
 */
const POLICY_ENTITIES = new Set(["FED", "ECB", "OPEC", "IMF", "SBP", "SECP"]);

export default function BreakingNewsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = (searchParams.get("view") as View) ?? "feed";

  const [hours, setHours] = useState(24);
  const [level, setLevel] = useState<BreakingLevel | "ALL">("ALL");
  const [minScore, setMinScore] = useState(0);
  const [category, setCategory] = useState("");
  const [entity, setEntity] = useState("");

  const [feed, setFeed] = useState<BreakingFeedResponse | null>(null);
  const [feedLoading, setFeedLoading] = useState(true);
  const [feedError, setFeedError] = useState<string | null>(null);

  const [topics, setTopics] = useState<TopicsResponse | null>(null);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [topicsError, setTopicsError] = useState<string | null>(null);

  const [sources, setSources] = useState<SourcesResponse | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  const [clusters, setClusters] = useState<Cluster[] | null>(null);
  const [clustersLoading, setClustersLoading] = useState(false);
  const [clustersError, setClustersError] = useState<string | null>(null);

  const [health, setHealth] = useState<BreakingHealth | null>(null);
  const [selected, setSelected] = useState<BreakingNewsEvent | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [ingestReport, setIngestReport] = useState<IngestReport | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadFeed = useCallback(async () => {
    setFeedLoading(true);
    try {
      const response = await fetchBreakingFeed({
        hours,
        level: level === "ALL" ? undefined : level,
        minScore,
        category: category.trim() || undefined,
        entity: entity.trim() || undefined,
        limit: 60,
      });
      setFeed(response);
      setFeedError(null);
      // Selection is by id: keep the freshest copy of the selected event.
      setSelected((current) => (current ? response.items.find((item) => item.id === current.id) ?? current : null));
    } catch (err) {
      setFeedError(err instanceof Error ? err.message : "Failed to load the breaking feed");
    } finally {
      setFeedLoading(false);
    }
  }, [hours, level, minScore, category, entity]);

  const loadTopics = useCallback(async () => {
    setTopicsLoading(true);
    try {
      setTopics(await fetchTopics({ limit: 40 }));
      setTopicsError(null);
    } catch (err) {
      setTopicsError(err instanceof Error ? err.message : "Failed to load topics");
    } finally {
      setTopicsLoading(false);
    }
  }, []);

  const loadSources = useCallback(async () => {
    setSourcesLoading(true);
    try {
      setSources(await fetchSources());
      setSourcesError(null);
    } catch (err) {
      setSourcesError(err instanceof Error ? err.message : "Failed to load sources");
    } finally {
      setSourcesLoading(false);
    }
  }, []);

  const loadClusters = useCallback(async () => {
    setClustersLoading(true);
    try {
      setClusters(await fetchClusters(hours, 1));
      setClustersError(null);
    } catch (err) {
      setClustersError(err instanceof Error ? err.message : "Failed to load event clusters");
    } finally {
      setClustersLoading(false);
    }
  }, [hours]);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await fetchBreakingHealth());
    } catch {
      setHealth(null);
    }
  }, []);

  // Initial + filter-driven load. Real-time pushes land through the stream hook.
  useEffect(() => {
    void loadFeed();
  }, [loadFeed]);

  useEffect(() => {
    void loadTopics();
    void loadHealth();
  }, [loadTopics, loadHealth]);

  useEffect(() => {
    if (view === "sources") void loadSources();
    if (view === "clusters") void loadClusters();
    if (view === "topics") void loadTopics();
  }, [view, loadSources, loadClusters, loadTopics]);

  const stream = useBreakingNewsStream({
    onUpdate: () => {
      void loadFeed();
      void loadHealth();
    },
  });

  const ingest = useCallback(
    async (analyzeImpacts: boolean) => {
      setIngesting(true);
      setNotice(null);
      try {
        const report = await refreshBreakingNews({ live: true, analyzeImpacts });
        setIngestReport(report);
        setNotice(
          report.stored_articles === 0
            ? "Ingest finished: no new articles were stored (feeds returned only material already in the corpus)."
            : `Ingest finished: ${report.stored_articles} new articles, ${report.breaking_events} events, ${report.topics_updated} topics.`,
        );
        await Promise.all([loadFeed(), loadTopics(), loadHealth()]);
      } catch (err) {
        setNotice(err instanceof Error ? err.message : "Ingest failed");
      } finally {
        setIngesting(false);
      }
    },
    [loadFeed, loadTopics, loadHealth],
  );

  const impactTargetsFor = useCallback((event: BreakingNewsEvent) => {
    const types = (event.market_associations?.["entity_types"] ?? {}) as Record<string, string>;
    const targets: Array<{ entity: string; entityType: "STOCK" | "INDEX" | "COMMODITY" | "FOREX" | "CRYPTO" }> = [];
    const push = (value: string, fallback: "STOCK" | "INDEX") => {
      const name = value?.trim().toUpperCase();
      if (!name || POLICY_ENTITIES.has(name) || targets.some((t) => t.entity === name)) return;
      const kind = (types[name] ?? fallback).toUpperCase();
      if (kind === "FORECAST") return;
      targets.push({
        entity: name,
        entityType: (kind === "INDEX" || kind === "COMMODITY" || kind === "FOREX" || kind === "CRYPTO" ? kind : "STOCK"),
      });
    };
    event.affected_entities.forEach((value) => push(value, "STOCK"));
    event.affected_indices.forEach((value) => push(value, "INDEX"));
    return targets;
  }, []);

  const setView = (next: View) => {
    const params = new URLSearchParams(searchParams);
    params.set("view", next);
    setSearchParams(params, { replace: true });
  };

  const selectFromTicker = (event: BreakingNewsEvent) => {
    setSelected(event);
    setView("feed");
    if (typeof document !== "undefined") {
      document.getElementById(`bn-event-${event.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const items = feed?.items ?? [];
  const meta = feed?.meta ?? null;

  const tickerItems = useMemo(
    () => items.filter((item) => item.breaking_level !== "NORMAL").slice(0, 12),
    [items],
  );

  return (
    <div className="bn-page">
      <header className="bn-hero">
        <div className="bn-hero-main">
          <h1>
            <Zap size={20} aria-hidden /> Breaking news desk
          </h1>
          <p>
            Real publisher timestamps, clustered events, observed market movement and data-derived trends. No synthetic
            headlines, no invented impact numbers.
          </p>
        </div>
        <div className="bn-hero-stats" aria-live="polite">
          <Stat icon={Database} label="Corpus (24h)" value={health ? String(health.corpus_articles_24h) : "—"} />
          <Stat icon={Zap} label="Events" value={health ? String(health.breaking_events) : "—"} />
          <Stat icon={Flame} label="Topics" value={health ? String(health.topics) : "—"} />
          <Stat icon={Activity} label="Impact rows" value={health ? String(health.market_impact_events) : "—"} />
          <Stat
            icon={Bot}
            label="AI summaries"
            value={health ? (health.ai_summarization.available ? "available" : "unavailable") : "—"}
            hint={health ? `min score ${health.ai_summarization.min_score}` : undefined}
          />
          <Stat
            icon={Radio}
            label="Transport"
            value={stream.transport}
            hint={stream.lastMessageAt ? `last message ${formatDateTime(stream.lastMessageAt)}` : undefined}
          />
        </div>
      </header>

      <BreakingNewsTicker items={tickerItems} onSelect={selectFromTicker} transport={stream.transport} />

      {stream.error && (
        <div className="bn-warning" role="status">
          <AlertTriangle size={13} aria-hidden /> Live stream degraded: {stream.error}. Polling will still update the desk.
        </div>
      )}

      {notice && (
        <div className="bn-notice" role="status">
          {notice}
        </div>
      )}

      {ingestReport && (
        <div className="bn-report">
          <div className="bn-report-head">
            <strong>Last ingest</strong>
            <span>
              {ingestReport.duration_ms.toFixed(0)} ms · {ingestReport.stored_articles} stored ·{" "}
              {ingestReport.corpus_articles} in corpus · {ingestReport.breaking_events} events ·{" "}
              {ingestReport.topics_updated} topics · {ingestReport.impact_events} impacts ·{" "}
              {ingestReport.probability_movements} probability rows
            </span>
          </div>
          <ul className="bn-report-providers">
            {ingestReport.providers.map((provider) => (
              <li key={provider.name}>
                <span className={provider.ok ? "bn-pos" : "bn-neg"}>{provider.ok ? "ok" : "failed"}</span>
                <span>{provider.name}</span>
                <span className="bn-muted">
                  {provider.fetched} fetched · {provider.normalized} normalised · {provider.rejected} rejected ·{" "}
                  {provider.duplicates} duplicates
                  {provider.duration_ms !== null && ` · ${provider.duration_ms.toFixed(0)} ms`}
                </span>
                {provider.error && <span className="bn-neg">{provider.error}</span>}
                {Object.keys(provider.missing_fields).length > 0 && (
                  <span className="bn-muted">
                    missing:{" "}
                    {Object.entries(provider.missing_fields)
                      .map(([field, count]) => `${field}×${count}`)
                      .join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {ingestReport.errors.length > 0 && (
            <p className="bn-neg">Provider errors: {ingestReport.errors.join(" | ")}</p>
          )}
          {ingestReport.warnings.length > 0 && <p className="bn-muted">Warnings: {ingestReport.warnings.join(" | ")}</p>}
        </div>
      )}

      <div className="bn-toolbar">
        <nav className="bn-view-tabs" aria-label="Desk views">
          {VIEWS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              className={`bn-view-tab${view === key ? " active" : ""}`}
              aria-current={view === key ? "page" : undefined}
              onClick={() => setView(key)}
            >
              <Icon size={13} aria-hidden /> {label}
            </button>
          ))}
        </nav>

        <div className="bn-filters">
          <div className="bn-filter-group" role="group" aria-label="Time window">
            {HOUR_CHOICES.map((value) => (
              <button
                key={value}
                type="button"
                className={`bn-pill${hours === value ? " active" : ""}`}
                onClick={() => setHours(value)}
              >
                {value}h
              </button>
            ))}
          </div>

          <select
            aria-label="Breaking level"
            value={level}
            onChange={(event) => setLevel(event.target.value as BreakingLevel | "ALL")}
          >
            {LEVEL_CHOICES.map((choice) => (
              <option key={choice.key} value={choice.key}>
                {choice.label}
              </option>
            ))}
          </select>

          <label className="bn-filter-inline">
            min score
            <input
              type="range"
              min={0}
              max={100}
              value={minScore}
              onChange={(event) => setMinScore(Number(event.target.value))}
            />
            <span>{minScore}</span>
          </label>

          <input
            type="search"
            placeholder="category"
            aria-label="Filter by category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          />
          <input
            type="search"
            placeholder="entity / ticker"
            aria-label="Filter by entity"
            value={entity}
            onChange={(event) => setEntity(event.target.value)}
          />

          <button type="button" className="bn-btn" onClick={() => void loadFeed()} disabled={feedLoading}>
            <RefreshCw size={12} className={feedLoading ? "bn-spin" : undefined} aria-hidden /> Rebuild
          </button>
          <button type="button" className="bn-btn primary" onClick={() => void ingest(true)} disabled={ingesting}>
            <RefreshCw size={12} className={ingesting ? "bn-spin" : undefined} aria-hidden />
            {ingesting ? "Ingesting live feeds…" : "Ingest + analyse"}
          </button>
        </div>
      </div>

      {view === "feed" && (
        <div className="bn-layout">
          <div className="bn-layout-main">
            {meta && (
              <p className="bn-disclaimer">
                {meta.disclaimer} Window: last {meta.hours}h · minimum score {meta.min_score}.
              </p>
            )}
            <BreakingNewsFeed
              items={items}
              meta={meta}
              loading={feedLoading}
              error={feedError}
              transport={stream.transport}
              selectedId={selected?.id ?? null}
              onSelect={setSelected}
              onRefresh={() => void loadFeed()}
              onIngest={() => void ingest(false)}
              ingesting={ingesting}
              impactTargetsFor={impactTargetsFor}
            />
          </div>
          <aside className="bn-layout-side">
            <HotTopicsSidebar
              topics={topics?.topics ?? []}
              loading={topicsLoading}
              error={topicsError}
              meta={topics?.meta ?? null}
              onRefresh={() => void loadTopics()}
              limit={12}
            />
            <section className="bn-card">
              <header className="bn-card-head">
                <h3>
                  <BarChart3 size={15} aria-hidden /> Detector configuration
                </h3>
              </header>
              {health ? (
                <ul className="bn-config">
                  <li>
                    <span className="bn-k">Breaking threshold</span>
                    <span>{fixed(health.settings.breaking_threshold, 1)}</span>
                  </li>
                  <li>
                    <span className="bn-k">Significant threshold</span>
                    <span>{fixed(health.settings.significant_threshold, 1)}</span>
                  </li>
                  {Object.entries(health.settings.detection_weights).map(([key, value]) => (
                    <li key={key}>
                      <span className="bn-k">{key.replace(/_/g, " ")}</span>
                      <span>{fixed(value, 3)}</span>
                    </li>
                  ))}
                  <li>
                    <span className="bn-k">Observation windows</span>
                    <span>{health.observation_windows.join(", ")}</span>
                  </li>
                  <li>
                    <span className="bn-k">Market providers</span>
                    <span>{health.providers_configured ? "configured" : "not configured"}</span>
                  </li>
                </ul>
              ) : (
                <p className="bn-muted">Health endpoint unavailable.</p>
              )}
            </section>
            <section className="bn-card">
              <header className="bn-card-head">
                <h3>
                  <ShieldCheck size={15} aria-hidden /> Publisher reliability
                </h3>
                <button type="button" className="bn-ghost-btn" onClick={() => void loadSources()}>
                  Load
                </button>
              </header>
              <SourceList data={sources} loading={sourcesLoading} error={sourcesError} initial={6} />
            </section>
          </aside>
        </div>
      )}

      {view === "topics" && (
        <section className="bn-card">
          <header className="bn-card-head">
            <h3>
              <Flame size={15} aria-hidden /> Ranked topics
            </h3>
            <span className="bn-muted">
              {topics ? `${topics.topics.length} topics · window ${String(topics.meta["window_hours"] ?? "—")}h` : "—"}
            </span>
          </header>
          {topicsError && <p className="bn-warning">{topicsError}</p>}
          {topicsLoading && <p className="bn-muted">Loading topics…</p>}
          {!topicsLoading && (topics?.topics.length ?? 0) === 0 && (
            <p className="bn-muted">
              No topics yet. Topics are extracted from stored articles during an ingest, so this list is empty until the
              desk has seen real news.
            </p>
          )}
          <div className="bn-topic-grid">
            {(topics?.topics ?? []).map((topic) => (
              <TopicCard key={topic.id} topic={topic} variant="full" />
            ))}
          </div>
        </section>
      )}

      {view === "clusters" && (
        <section className="bn-card">
          <header className="bn-card-head">
            <h3>
              <Layers size={15} aria-hidden /> Event clusters
            </h3>
            <button type="button" className="bn-ghost-btn" onClick={() => void loadClusters()} disabled={clustersLoading}>
              <RefreshCw size={12} className={clustersLoading ? "bn-spin" : undefined} aria-hidden /> Refresh
            </button>
          </header>
          <p className="bn-muted">
            One row per event, not per article. The shared terms explain why these publishers were grouped: they are the
            TF-IDF terms and entity overlap the clusterer actually used.
          </p>
          {clustersError && <p className="bn-warning">{clustersError}</p>}
          {!clustersLoading && (clusters?.length ?? 0) === 0 && (
            <p className="bn-muted">No clusters in this window.</p>
          )}
          {(clusters?.length ?? 0) > 0 && (
            <table className="bn-table">
              <thead>
                <tr>
                  <th scope="col">Event</th>
                  <th scope="col">Size</th>
                  <th scope="col">Publishers</th>
                  <th scope="col">First → last</th>
                  <th scope="col">Span</th>
                  <th scope="col">Shared terms</th>
                </tr>
              </thead>
              <tbody>
                {clusters!.map((cluster) => (
                  <tr key={cluster.cluster_id}>
                    <td>
                      {cluster.title}
                      {cluster.symbols.length > 0 && (
                        <span className="bn-chip-row">
                          {cluster.symbols.slice(0, 5).map((symbol) => (
                            <span key={symbol} className="bn-chip">
                              {symbol}
                            </span>
                          ))}
                        </span>
                      )}
                    </td>
                    <td>{cluster.cluster_size}</td>
                    <td>{cluster.publishers.join(", ") || "unavailable"}</td>
                    <td>
                      {timeAgo(cluster.first_seen)} → {timeAgo(cluster.last_seen)}
                    </td>
                    <td>{fixed(cluster.time_span_hours, 2)}h</td>
                    <td>{cluster.terms.slice(0, 8).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {view === "sources" && (
        <section className="bn-card">
          <header className="bn-card-head">
            <h3>
              <ShieldCheck size={15} aria-hidden /> Sources, reliability & feed health
            </h3>
            <button type="button" className="bn-ghost-btn" onClick={() => void loadSources()} disabled={sourcesLoading}>
              <RefreshCw size={12} className={sourcesLoading ? "bn-spin" : undefined} aria-hidden /> Refresh
            </button>
          </header>
          <SourceList data={sources} loading={sourcesLoading} error={sourcesError} initial={40} />
        </section>
      )}

      <footer className="bn-footnote">
        <p>
          Market impact rows are only produced where a provider returned real timestamped bars on both sides of the
          publisher timestamp, and a probability movement row only where the Phase 14 market actually traded. Movements
          are observed, not causal.
        </p>
        {health && (
          <p className="bn-muted">
            Last build {formatDateTime(health.last_build_at)} · database {health.database} · phase {health.phase}
          </p>
        )}
      </footer>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Newspaper;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="bn-stat" title={hint}>
      <Icon size={13} aria-hidden />
      <span className="bn-k">{label}</span>
      <span className="bn-stat-v">{value}</span>
    </div>
  );
}
