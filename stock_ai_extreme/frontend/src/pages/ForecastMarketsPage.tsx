import { useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock3, Database, Filter, Gauge, RefreshCw, Save, Sparkles, Trash2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useForecastMarkets } from "../hooks/useForecastQueries";
import { CombinationCalculator, CombinationService, CombinationStorage, CorrelationService, formatProbability, type CombinationEventInput, type CombinationOutcome, type CombinationRecord, type CombinationSelection } from "../lib/combination";
import CorrelationAdjustedPanel from "../components/forecast/CorrelationAdjustedPanel";
import { FORECAST_CATEGORIES, type ForecastCategory, type ForecastMarket, type ForecastStatus } from "../lib/forecasting";

type FilterValue = "ALL" | ForecastStatus;

type ForecastSelectionState = CombinationSelection & { marketTitle?: string; marketStatus?: ForecastStatus; freshness?: "Current" | "Recently Updated" | "Stale"; liveProbability?: number | null };

function relativeTime(value: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

function statusLabel(status: ForecastStatus): string {
  return status.replace("_", " ");
}

function MarketCard({ market, onAddSelection }: { market: ForecastMarket; onAddSelection: (market: ForecastMarket, outcome: CombinationOutcome) => void; }) {
  const delta = market.history.length > 1 ? market.yesProbability - market.history[market.history.length - 2].yesProbability : null;
  const isResolved = market.status === "RESOLVED";
  return <article className="forecast-card">
    <div className="forecast-card-top"><span className="forecast-category">{market.category}</span><span className={`forecast-status ${market.status.toLowerCase()}`}>{statusLabel(market.status)}</span></div>
    <Link to={`/forecast/${market.id}`} className="forecast-question">{market.title}</Link>
    <p className="forecast-description">{market.description}</p>
    <div className="forecast-probability-head"><strong>YES {market.yesProbability.toFixed(0)}%</strong><strong>NO {market.noProbability.toFixed(0)}%</strong></div>
    <div className="forecast-probability-bar" aria-label={`YES ${market.yesProbability.toFixed(0)} percent, NO ${market.noProbability.toFixed(0)} percent`}><span style={{ width: `${market.yesProbability}%` }} /><span style={{ width: `${market.noProbability}%` }} /></div>
    <div className="forecast-card-meta"><span>{delta === null ? "No prior movement" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)} pp`} since prior update</span><span>{relativeTime(market.updatedAt)}</span></div>
    <div className="forecast-card-foot"><span><Clock3 size={13} aria-hidden /> Closes {new Date(market.closeTime).toLocaleDateString()}</span><span className={`forecast-mode ${market.dataMode.toLowerCase()}`}><Database size={12} aria-hidden /> {market.dataMode}</span><Link to={`/forecast/${market.id}`} aria-label={`Open ${market.title}`}>Open <ArrowRight size={13} aria-hidden /></Link></div>
    <div className="forecast-card-actions">
      <button type="button" className="forecast-action primary" onClick={() => onAddSelection(market, "YES")} disabled={isResolved || market.status === "CLOSED"} aria-label={`Add YES probability for ${market.title}`}>
        Add YES
      </button>
      <button type="button" className="forecast-action" onClick={() => onAddSelection(market, "NO")} disabled={isResolved || market.status === "CLOSED"} aria-label={`Add NO probability for ${market.title}`}>
        Add NO
      </button>
    </div>
  </article>;
}

export default function ForecastMarketsPage() {
  const query = useForecastMarkets();
  const [category, setCategory] = useState<ForecastCategory | "ALL">("ALL");
  const [status, setStatus] = useState<FilterValue>("ALL");
  const [endingSoon, setEndingSoon] = useState(false);
  const [recentlyUpdated, setRecentlyUpdated] = useState(false);
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false);
  const [combinationName, setCombinationName] = useState("Combination 1");
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [selections, setSelections] = useState<CombinationSelection[]>([]);
  const [savedCombinations, setSavedCombinations] = useState<CombinationRecord[]>(() => CombinationStorage.load());

  const markets = useMemo(() => (query.data ?? []).filter((market) => category === "ALL" || market.category === category).filter((market) => status === "ALL" || market.status === status).filter((market) => !endingSoon || new Date(market.closeTime).getTime() - Date.now() < 7 * 86_400_000).filter((market) => !recentlyUpdated || Date.now() - new Date(market.updatedAt).getTime() < 24 * 86_400_000), [category, endingSoon, query.data, recentlyUpdated, status]);

  const marketMap = useMemo(() => new Map((query.data ?? []).map((market) => [market.id, market])), [query.data]);

  const effectiveSelections = useMemo<ForecastSelectionState[]>(() => selections.map((selection) => {
    const market = marketMap.get(selection.marketId);
    const liveProbability = market ? CombinationCalculator.calculateOutcomeProbability(market, selection.outcome) : null;
    const probability = liveProbability ?? selection.probability;
    const marketStatus = market?.status;
    const freshness = market ? CombinationService.getFreshnessStatus(market.updatedAt) : "Stale";
    return {
      ...selection,
      probability,
      marketTitle: market?.title ?? selection.marketId,
      marketStatus,
      freshness,
      liveProbability,
    };
  }), [marketMap, selections]);

  const hasNonLiveSelection = effectiveSelections.some((selection) => selection.liveProbability === null);
  const hasStaleSelection = effectiveSelections.some((selection) => selection.freshness === "Stale");
  const liveCombined = effectiveSelections.length > 0 && !hasNonLiveSelection ? CombinationService.calculateCombinedProbabilityFromSelections(effectiveSelections) : null;
  const savedCombined = effectiveSelections.length > 0 ? CombinationService.calculateCombinedProbabilityFromSnapshot(effectiveSelections) : null;
  const correlation = CorrelationService.detectPotentialCorrelation(effectiveSelections, Array.from(marketMap.values()));

  const correlationEvents = useMemo<CombinationEventInput[]>(() => effectiveSelections
    .filter((selection) => selection.marketStatus !== "RESOLVED")
    .map((selection) => ({ marketId: selection.marketId, outcome: selection.outcome, probability: selection.probability, label: selection.marketTitle ?? selection.marketId })), [effectiveSelections]);

  const comparisonSummary = useMemo(() => {
    const probabilities = effectiveSelections.map((selection) => selection.probability);
    return {
      single: probabilities[0] ?? null,
      pair: probabilities.length >= 2 ? CombinationCalculator.calculateCombinedProbability(probabilities.slice(0, 2)) : null,
      triple: probabilities.length >= 3 ? CombinationCalculator.calculateCombinedProbability(probabilities.slice(0, 3)) : null,
    };
  }, [effectiveSelections]);

  const handleAddSelection = (market: ForecastMarket, outcome: CombinationOutcome) => {
    try {
      const next = CombinationService.addSelection(effectiveSelections, market, outcome);
      setSelections(next);
      setAnalysisError(null);
      setMobilePanelOpen(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Calculation failure: selection could not be added.";
      setAnalysisError(message);
    }
  };

  const handleRemoveSelection = (marketId: string) => {
    setSelections((current) => CombinationService.removeSelection(current, marketId));
    setAnalysisError(null);
  };

  const handleSaveCombination = () => {
    if (effectiveSelections.length === 0) {
      setAnalysisError("Add forecast events to begin an analysis.");
      return;
    }
    const finalName = combinationName.trim() || `Combination ${savedCombinations.length + 1}`;
    const createdAt = new Date().toISOString();
    const record: CombinationRecord = {
      id: `combo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: finalName,
      selections: effectiveSelections.map((selection) => ({ ...selection })),
      probabilitySnapshot: liveCombined ?? savedCombined ?? 0,
      createdAt,
      updatedAt: createdAt,
    };
    try {
      CombinationStorage.saveCombination(record);
      setSavedCombinations(CombinationStorage.loadCombinations());
      setCombinationName(finalName);
      setAnalysisError(null);
    } catch {
      setAnalysisError("Storage failure: this analysis could not be saved in browser storage.");
    }
  };

  const handleLoadCombination = (record: CombinationRecord) => {
    const nextSelections = record.selections.map((selection) => ({
      marketId: selection.marketId,
      outcome: selection.outcome,
      probability: selection.probability,
      probabilitySnapshot: selection.probabilitySnapshot,
      addedAt: selection.addedAt,
    }));
    setSelections(nextSelections);
    setCombinationName(record.name);
    setMobilePanelOpen(true);
    setAnalysisError(null);
  };

  const handleRenameCombination = (recordId: string) => {
    const target = savedCombinations.find((record) => record.id === recordId);
    if (!target) return;
    const nextValue = window.prompt("Rename this saved analysis", target.name)?.trim();
    if (!nextValue) return;
    const renamed = CombinationStorage.rename(recordId, nextValue);
    if (renamed) {
      setSavedCombinations(CombinationStorage.loadCombinations());
      if (combinationName === target.name) {
        setCombinationName(renamed.name);
      }
    }
  };

  const handleDeleteCombination = (recordId: string) => {
    try {
      CombinationStorage.delete(recordId);
      setSavedCombinations(CombinationStorage.loadCombinations());
    } catch {
      setAnalysisError("Storage failure: this saved analysis could not be deleted.");
    }
  };

  return <section className="forecast-page">
    <header className="forecast-page-head"><div><p>Event-driven analysis · non-monetary</p><h1>Forecast Markets</h1><span>Probability visualization for educational research. No wagering, balances, payouts or monetary activity.</span></div><button className="forecast-refresh" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={15} className={query.isFetching ? "forecast-spin" : ""} aria-hidden /> Refresh</button></header>
    <div className="forecast-filterbar"><div className="forecast-filter-title"><Filter size={15} aria-hidden /> Discover</div><label>Category<select value={category} onChange={(event) => setCategory(event.target.value as ForecastCategory | "ALL")}><option value="ALL">All categories</option>{FORECAST_CATEGORIES.map((item) => <option key={item}>{item}</option>)}</select></label><label>Status<select value={status} onChange={(event) => setStatus(event.target.value as FilterValue)}><option value="ALL">All statuses</option>{["UPCOMING", "OPEN", "CLOSED", "SUSPENDED", "RESOLVED"].map((item) => <option key={item}>{statusLabel(item as ForecastStatus)}</option>)}</select></label><label className="forecast-check"><input type="checkbox" checked={recentlyUpdated} onChange={(event) => setRecentlyUpdated(event.target.checked)} /> Recently updated</label><label className="forecast-check"><input type="checkbox" checked={endingSoon} onChange={(event) => setEndingSoon(event.target.checked)} /> Ending soon</label><span className="forecast-count">{markets.length} markets</span></div>
    {query.isLoading && <div className="forecast-state"><Gauge size={22} aria-hidden /> Loading forecast markets...</div>}
    {query.isError && <div className="forecast-state error" role="alert">Forecast service unavailable. Check the API connection and retry.</div>}
    {!query.isLoading && !query.isError && markets.length === 0 && <div className="forecast-state"><Activity size={22} aria-hidden /> No markets match these filters.</div>}

    <div className="forecast-combination-layout">
      <div className="forecast-grid">{markets.map((market) => <MarketCard key={market.id} market={market} onAddSelection={handleAddSelection} />)}</div>

      <aside className={`forecast-combination-panel ${mobilePanelOpen ? "open" : ""}`} aria-live="polite">
        <div className="forecast-combination-header">
          <div>
            <p>Combination analysis</p>
            <h2>COMBINATION</h2>
          </div>
          <button type="button" className="forecast-combination-close" onClick={() => setMobilePanelOpen(false)} aria-label="Close combination analysis">
            <X size={15} aria-hidden />
          </button>
        </div>

        {analysisError && <div className="forecast-warning" role="alert"><AlertTriangle size={14} aria-hidden /> {analysisError}</div>}

        {effectiveSelections.length === 0 ? (
          <div className="forecast-combination-empty">
            <Sparkles size={18} aria-hidden />
            <p>Add forecast events to begin an analysis.</p>
          </div>
        ) : (
          <>
            <div className="forecast-combination-summary">
              <div className="forecast-summary-stat">
                <span>Selections</span>
                <strong>{effectiveSelections.length}</strong>
              </div>
              <div className="forecast-summary-stat accent">
                <span>Combined</span>
                <strong>{liveCombined === null ? "—" : `${liveCombined.toFixed(1)}%`}</strong>
              </div>
            </div>

            {hasNonLiveSelection && <div className="forecast-warning" role="status"><AlertTriangle size={14} aria-hidden /> A selected market is missing or resolved. It remains visible for snapshot analysis but is excluded from the current live estimate.</div>}
            {hasStaleSelection && <div className="forecast-warning" role="status"><Clock3 size={14} aria-hidden /> One or more selected probabilities are stale. Refresh the forecast feed before treating the current estimate as timely.</div>}

            <div className="forecast-combination-list">
              {effectiveSelections.map((selection) => (
                <div key={`${selection.marketId}-${selection.outcome}`} className="forecast-combo-item">
                  <div className="forecast-combo-item-top">
                    <div>
                      <h3>{selection.marketTitle ?? selection.marketId}</h3>
                      <small>{selection.marketStatus}</small>
                    </div>
                    <button type="button" className="forecast-combo-remove" onClick={() => handleRemoveSelection(selection.marketId)} aria-label={`Remove ${selection.marketTitle ?? selection.marketId}`}>
                      Remove
                    </button>
                  </div>
                  <div className="forecast-combo-row"><span>Outcome</span><strong>{selection.outcome}</strong></div>
                  <div className="forecast-combo-row"><span>Probability</span><strong>{formatProbability(selection.probability)}</strong></div>
                  <div className="forecast-combo-row"><span>Snapshot</span><strong>{formatProbability(selection.probabilitySnapshot)}</strong></div>
                  <div className="forecast-combo-row"><span>Snapshot time</span><strong>{new Date(selection.addedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</strong></div>
                  <div className="forecast-combo-row"><span>Freshness</span><strong>{selection.freshness ?? "Stale"}</strong></div>
                </div>
              ))}
            </div>

            <div className="forecast-combination-analysis-box">
              <div className="forecast-combo-metrics">
                <span>Individual probabilities</span>
                <div>{effectiveSelections.map((selection) => <em key={`${selection.marketId}-${selection.outcome}-prob`}>{selection.probability.toFixed(1)}%</em>)}</div>
              </div>
              <div className="forecast-combo-result">
                <span>Estimated combined probability</span>
                <strong>{liveCombined === null ? "—" : `${liveCombined.toFixed(1)}%`}</strong>
              </div>
              <div className="forecast-combo-label">Assumption: Independent events</div>
              <p className="forecast-combo-note">Estimated combined probability assumes the selected events are independent. Real-world dependencies can make this estimate inaccurate.</p>
              <div className="forecast-combo-correlated">
                <span>Correlation</span>
                <strong className={correlation.status === "POTENTIAL_CORRELATION" ? "warning" : ""}>{correlation.message}</strong>
              </div>
              <CorrelationAdjustedPanel events={correlationEvents} />
              {savedCombined !== null && savedCombined !== liveCombined && <div className="forecast-combo-snapshot-delta"><span>Saved snapshot</span><strong>{savedCombined.toFixed(1)}%</strong></div> }
            </div>

            <div className="forecast-comparison-box">
              <h3>Comparison mode</h3>
              <div className="forecast-comparison-grid">
                <div><span>Single-event</span><strong>{comparisonSummary.single === null ? "—" : `${comparisonSummary.single.toFixed(1)}%`}</strong></div>
                <div><span>Two-event combined</span><strong>{comparisonSummary.pair === null ? "—" : `${comparisonSummary.pair.toFixed(1)}%`}</strong></div>
                <div><span>Three-event combined</span><strong>{comparisonSummary.triple === null ? "—" : `${comparisonSummary.triple.toFixed(1)}%`}</strong></div>
              </div>
            </div>
          </>
        )}

        <div className="forecast-combination-save">
          <label htmlFor="combination-name">Analysis name</label>
          <input id="combination-name" value={combinationName} onChange={(event) => setCombinationName(event.target.value)} placeholder="Combination name" aria-label="Combination analysis name" />
          <button type="button" className="forecast-save-button" onClick={handleSaveCombination} disabled={effectiveSelections.length === 0}>
            <Save size={15} aria-hidden /> Save
          </button>
        </div>

        <div className="forecast-saved-combinations">
          <h3>Saved simulations</h3>
          {savedCombinations.length === 0 ? <p className="forecast-muted">No saved simulation yet.</p> : savedCombinations.map((record) => (
            <div key={record.id} className="forecast-saved-record">
              <div>
                <strong>{record.name}</strong>
                <small>{new Date(record.createdAt).toLocaleString()}</small>
              </div>
              <div className="forecast-record-actions">
                <button type="button" onClick={() => handleLoadCombination(record)}>Open</button>
                <button type="button" onClick={() => handleRenameCombination(record.id)}>Rename</button>
                <button type="button" onClick={() => handleDeleteCombination(record.id)} className="danger">Delete</button>
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>

    <footer className="forecast-disclaimer"><Database size={15} aria-hidden /><span>Data mode is shown on every card. Simulated fallback records are clearly labeled and contain no invented source URLs. Modelled probability is not certainty.</span></footer>
  </section>;
}

