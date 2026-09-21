/**
 * Phase 17 (spec §7, §8, §9, §10) — market impact for one news event.
 *
 * The card is built around three honesty rules:
 *
 * 1. A window is only drawn when the backend says `window_available`. Windows
 *    that lack real bars on both sides are listed as unavailable with the
 *    reason the backend gave.
 * 2. The wording is always "price movement observed after publication" — never
 *    "this news moved the price".
 * 3. Forecast probability movement comes from Phase 14's real traded history.
 *    A market that never traded produces no row, and the card says so instead of
 *    showing `0%`.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, RefreshCw, Target } from "lucide-react";
import {
  WINDOW_LABELS,
  analyzeImpact,
  fetchEventImpactWindows,
  fetchProbabilityMovements,
  fixed,
  magnitudeClass,
  signed,
  type EntityType,
  type ImpactWindowAnalysis,
  type MarketImpactEvent,
  type ObservationWindow,
  type ProbabilityMovement,
} from "../../lib/breakingNews";
import ImpactSparkline from "./ImpactSparkline";

interface Props {
  /** Stored breaking event id; when absent the card measures on demand. */
  newsId?: string | null;
  articleId: number | null;
  entity: string;
  entityType?: EntityType;
  publishedAt: string;
  title: string;
  /** Called when the analyst asks for a window the backend has not measured yet. */
  onRefreshRequested?: () => void;
}

export default function NewsImpactCard({
  newsId,
  articleId,
  entity,
  entityType = "STOCK",
  publishedAt,
  title,
  onRefreshRequested,
}: Props) {
  const [analysis, setAnalysis] = useState<ImpactWindowAnalysis | null>(null);
  const [movements, setMovements] = useState<ProbabilityMovement[] | null>(null);
  const [window_, setWindow] = useState<ObservationWindow>("1h");
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [probabilityState, setProbabilityState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [probabilityError, setProbabilityError] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    setState("loading");
    setError(null);
    try {
      // A stored event is measured through its own endpoint (so every window it
      // has already recorded is reused); an ad-hoc entity is measured live.
      const result = newsId
        ? await fetchEventImpactWindows(newsId, refresh)
        : await analyzeImpact({
            article_id: articleId ?? undefined,
            entity,
            entity_type: entityType,
            published_at: publishedAt,
            refresh,
          });
      setAnalysis(result);
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Impact analysis failed");
      setState("error");
    }
  }, [newsId, articleId, entity, entityType, publishedAt]);

  useEffect(() => {
    void load(false);
  }, [load]);

  const loadProbability = useCallback(async () => {
    if (!articleId) {
      setMovements([]);
      setProbabilityState("ready");
      return;
    }
    setProbabilityState("loading");
    setProbabilityError(null);
    try {
      const rows = await fetchProbabilityMovements({ article_id: articleId });
      setMovements(rows);
      setProbabilityState("ready");
    } catch (err) {
      setProbabilityError(err instanceof Error ? err.message : "Probability lookup failed");
      setProbabilityState("error");
    }
  }, [articleId]);

  useEffect(() => {
    // Auto-attempt for linked events; a failure here is reported, never hidden.
    void loadProbability();
  }, [loadProbability]);

  const byWindow = useMemo(() => {
    const map = new Map<string, MarketImpactEvent>();
    (analysis?.windows ?? []).forEach((row) => map.set(row.observation_window, row));
    return map;
  }, [analysis]);

  const selected = byWindow.get(window_) ?? null;
  const unavailable = analysis?.unavailable_windows ?? [];

  const analyzeAdHoc = async () => {
    setState("loading");
    setError(null);
    try {
      const result = await analyzeImpact({
        article_id: articleId ?? undefined,
        entity,
        entity_type: entityType,
        observation_window: window_,
        // The publisher timestamp is the anchor, so this works for an entity the
        // stored event did not originally associate with.
        published_at: publishedAt,
      });
      setAnalysis((current) => {
        if (!current) return result;
        // Merge so a freshly measured window joins the windows already on screen
        // instead of replacing them.
        const merged = new Map(current.windows.map((row) => [row.observation_window, row]));
        result.windows.forEach((row) => merged.set(row.observation_window, row));
        return {
          ...current,
          windows: [...merged.values()],
          unavailable_windows: [
            ...new Set([
              ...current.unavailable_windows.filter((label) => !merged.has(label)),
              ...result.unavailable_windows,
            ]),
          ],
        };
      });
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ad-hoc impact analysis failed");
      setState("error");
    }
  };

  return (
    <section className="bn-impact" aria-live="polite">
      <header className="bn-impact-head">
        <h4>
          <Activity size={14} aria-hidden /> Market impact — {entity}
        </h4>
        <div className="bn-impact-actions">
          <button type="button" onClick={() => void load(true)} disabled={state === "loading"}>
            <RefreshCw size={12} className={state === "loading" ? "bn-spin" : undefined} aria-hidden />
            Re-measure
          </button>
          {onRefreshRequested && (
            <button type="button" onClick={onRefreshRequested}>
              <Target size={12} aria-hidden /> Ingest + analyse
            </button>
          )}
        </div>
      </header>

      {state === "error" && (
        <div className="bn-warning" role="alert">
          <AlertTriangle size={13} aria-hidden /> {error}
        </div>
      )}

      <div className="bn-window-tabs" role="tablist" aria-label="Observation window">
        {(Object.keys(WINDOW_LABELS) as ObservationWindow[]).map((key) => {
          const available = byWindow.has(key);
          return (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={window_ === key}
              className={`bn-window-tab${window_ === key ? " active" : ""}${available ? "" : " unavailable"}`}
              title={
                available
                  ? `${WINDOW_LABELS[key]} window — real bars on both sides of publication`
                  : `${WINDOW_LABELS[key]} window — not enough timestamped data`
              }
              onClick={() => setWindow(key)}
            >
              {key}
            </button>
          );
        })}
      </div>

      {state === "loading" && !analysis && <p className="bn-muted">Measuring real bars around publication…</p>}

      {selected ? (
        <div className="bn-impact-body">
          <div className="bn-impact-metrics">
            <div>
              <span className="bn-k">Observed move</span>
              <span className={`bn-v ${(selected.price_change_percent ?? 0) >= 0 ? "bn-pos" : "bn-neg"}`}>
                {signed(selected.price_change_percent, 3, "%")}
              </span>
            </div>
            <div>
              <span className="bn-k">Magnitude</span>
              <span className={`bn-badge ${magnitudeClass(selected.impact_magnitude)}`}>
                {selected.impact_magnitude}
              </span>
            </div>
            <div>
              <span className="bn-k">Before → after</span>
              <span className="bn-v-sm">
                {describePoint(selected.market_data_before)} → {describePoint(selected.market_data_after)}
              </span>
            </div>
            <div>
              <span className="bn-k">Bars (before/after)</span>
              <span className="bn-v-sm">
                {selected.bars_before} / {selected.bars_after}
              </span>
            </div>
            <div>
              <span className="bn-k">Unusualness (σ)</span>
              <span className="bn-v-sm">{fixed(selected.correlation_score, 2)}</span>
            </div>
            <div>
              <span className="bn-k">Volatility</span>
              <span className="bn-v-sm">{signed(selected.realized_volatility_percent, 3, "%")}</span>
            </div>
            <div>
              <span className="bn-k">Max favourable / adverse</span>
              <span className="bn-v-sm">
                {signed(selected.max_favorable_excursion_percent, 2, "%")} /{" "}
                {signed(selected.max_adverse_excursion_percent, 2, "%")}
              </span>
            </div>
            <div>
              <span className="bn-k">Provider</span>
              <span className="bn-v-sm">
                {selected.provider_symbol ?? "unresolved"} · {selected.data_source ?? "source unavailable"}
              </span>
            </div>
          </div>

          <ImpactSparkline
            points={selected.series}
            publishedAt={selected.news_published_at}
            ariaLabel={`${entity} observed bars around publication of ${title}`}
          />

          <p className="bn-note">{selected.notes}</p>
          {selected.confidence !== null && (
            <p className="bn-note">
              Measurement confidence {fixed(selected.confidence, 2)} (derived from bar counts and provider status).
            </p>
          )}
          <p className="bn-note bn-note-strong">
            Price movement observed after publication. Correlation does not imply causation.
          </p>
        </div>
      ) : (
        state !== "loading" && (
          <div className="bn-impact-body">
            <p className="bn-muted">
              No window of this event holds enough real timestamped bars for {entity}
              {unavailable.length > 0 && ` — unavailable: ${unavailable.join(", ")}`}.
            </p>
            <button type="button" className="bn-btn" onClick={() => void analyzeAdHoc()}>
              Measure this entity for the {window_} window
            </button>
          </div>
        )
      )}

      <div className="bn-probability">
        <h5>Forecast probability movement (Phase 14 traded history)</h5>
        {probabilityState === "loading" && <p className="bn-muted">Reading traded probability history…</p>}
        {probabilityState === "error" && (
          <div className="bn-warning" role="alert">
            <AlertTriangle size={13} aria-hidden /> {probabilityError}
          </div>
        )}
        {probabilityState === "ready" && (movements?.length ?? 0) === 0 && (
          <p className="bn-muted">
            No traded probability movement recorded for this event. Markets whose token never traded around
            publication are not given an invented before/after pair.
          </p>
        )}
        {probabilityState === "ready" &&
          (movements ?? []).map((row) => (
            <div key={row.id} className="bn-probability-row">
              <div className="bn-probability-title">
                {row.market_url ? (
                  <a href={row.market_url} target="_blank" rel="noopener noreferrer">
                    {row.market_name ?? row.market_id}
                  </a>
                ) : (
                  row.market_name ?? row.market_id
                )}
                <span className={`bn-badge ${magnitudeClass(row.impact_magnitude)}`}>{row.impact_magnitude}</span>
              </div>
              <div className="bn-probability-metrics">
                <span>Before {fixed(row.probability_before, 1)}%</span>
                <span>After {fixed(row.probability_after, 1)}%</span>
                <span className={(row.probability_change ?? 0) >= 0 ? "bn-pos" : "bn-neg"}>
                  Change {signed(row.probability_change, 1, " pts")}
                </span>
                <span>Window {row.observation_window}</span>
              </div>
              <p className="bn-note">
                Anchor {row.news_published_at} · source {row.source_name ?? "unavailable"}
                {row.source_url && (
                  <>
                    {" · "}
                    <a href={row.source_url} target="_blank" rel="noopener noreferrer">
                      trade history
                    </a>
                  </>
                )}
              </p>
            </div>
          ))}
      </div>
    </section>
  );
}

function describePoint(point: Record<string, unknown> | null): string {
  if (!point) return "unavailable";
  const price = point.price ?? point.close ?? point.last;
  const timestamp = point.timestamp;
  if (typeof price !== "number") return "unavailable";
  const clock =
    typeof timestamp === "string"
      ? new Date(timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : "time unavailable";
  return `${price.toFixed(4)} @ ${clock}`;
}
