import { useState } from "react";
import { Activity, AlertTriangle, GitBranch, Loader2, Scale } from "lucide-react";
import { useCorrelationCombine } from "../../hooks/useForecastQueries";
import { describeCorrelationStrength, formatProbability, type CombinationEventInput } from "../../lib/combination";

/**
 * Phase 15.1 — side-by-side independence vs correlation-adjusted probability.
 *
 * The independence estimate is the client's existing product-of-decimals. This
 * panel adds the backend's empirical estimate (Gaussian copula on log-odds
 * histories), the Monte-Carlo confidence interval, the exactly-k distribution
 * and the sensitivity tornado. Nothing here replaces the independence figure —
 * both are shown so the difference is visible.
 */
export default function CorrelationAdjustedPanel({ events }: { events: CombinationEventInput[] }) {
  const combine = useCorrelationCombine();
  const [showMatrix, setShowMatrix] = useState(false);

  const result = combine.data;
  const analysis = result?.analysis ?? null;
  const error = result?.error ?? combine.error?.message ?? null;
  const disabled = events.length < 2 || combine.isPending;

  return (
    <section className="forecast-correlation-panel" aria-live="polite">
      <div className="forecast-correlation-head">
        <h3><Scale size={15} aria-hidden /> Correlation-adjusted</h3>
        <button
          type="button"
          className="forecast-action primary"
          disabled={disabled}
          onClick={() => combine.mutate({ events })}
        >
          {combine.isPending ? <Loader2 size={13} className="forecast-spin" aria-hidden /> : <Activity size={13} aria-hidden />}
          {combine.isPending ? "Analysing…" : "Run analysis"}
        </button>
      </div>

      {events.length < 2 && <p className="forecast-muted">Select at least two live events to estimate their real dependence.</p>}
      {error && <div className="forecast-warning" role="alert"><AlertTriangle size={14} aria-hidden /> {error}</div>}

      {analysis && (
        <>
          <div className="forecast-correlation-compare">
            <div>
              <span>Independent</span>
              <strong>{formatProbability(analysis.independenceProbability)}</strong>
              <small>product of decimals</small>
            </div>
            <div className="accent">
              <span>Correlation-adjusted</span>
              <strong>{formatProbability(analysis.correlationAdjustedProbability)}</strong>
              <small>{analysis.correlationAdjustmentPp >= 0 ? "+" : ""}{analysis.correlationAdjustmentPp.toFixed(1)} pp vs independent</small>
            </div>
          </div>

          <div className="forecast-correlation-meta">
            <span>95% CI <b>{analysis.confidenceInterval95[0].toFixed(1)}–{analysis.confidenceInterval95[1].toFixed(1)}%</b></span>
            <span>P(any) <b>{analysis.atLeastOneProbability.toFixed(1)}%</b></span>
            <span>{analysis.draws.toLocaleString()} draws</span>
          </div>

          <div className="forecast-combo-correlated">
            <span><GitBranch size={13} aria-hidden /> Dependence</span>
            <strong className={analysis.correlationApplied && Math.abs(analysis.correlationAdjustmentPp) >= 5 ? "warning" : ""}>
              {analysis.correlationApplied
                ? `Empirical from ${analysis.correlation.observations} overlapping observations`
                : analysis.correlation.reason ?? "Independence assumed — no usable history"}
            </strong>
          </div>

          {analysis.count > 1 && (
            <button type="button" className="forecast-link-button" onClick={() => setShowMatrix((value) => !value)}>
              {showMatrix ? "Hide correlation matrix" : "Show correlation matrix"}
            </button>
          )}

          {showMatrix && (
            <div className="forecast-correlation-matrix" role="table" aria-label="Pairwise correlation matrix">
              {analysis.correlation.matrix.map((row, rowIndex) => (
                <div key={rowIndex} className="forecast-correlation-matrix-row" role="row">
                  {row.map((value, columnIndex) => (
                    <span
                      key={columnIndex}
                      className={rowIndex === columnIndex ? "diagonal" : ""}
                      title={`${analysis.correlation.eventLabels[rowIndex]} vs ${analysis.correlation.eventLabels[columnIndex]}: ${describeCorrelationStrength(value)}`}
                    >
                      {value.toFixed(2)}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}

          {analysis.sensitivity && analysis.sensitivity.tornado.length > 0 && (
            <div className="forecast-sensitivity">
              <h4>Sensitivity (±{analysis.sensitivity.deltaPp} pp per event)</h4>
              <div className="forecast-sensitivity-rows">
                {analysis.sensitivity.tornado.map((row) => (
                  <div key={`${row.index}-${row.label}`} className="forecast-sensitivity-row">
                    <span className="forecast-sensitivity-label">{row.label}</span>
                    <span className="forecast-sensitivity-track" aria-hidden>
                      <span
                        className="forecast-sensitivity-bar"
                        style={{ width: `${Math.min(100, Math.abs(row.swing) * 2)}%` }}
                      />
                    </span>
                    <strong>{row.swing.toFixed(1)} pp</strong>
                  </div>
                ))}
              </div>
              <div className="forecast-comparison-grid">
                {analysis.sensitivity.scenarios.map((scenario) => (
                  <div key={scenario.name}>
                    <span>{scenario.name}</span>
                    <strong>{scenario.probability.toFixed(1)}%</strong>
                  </div>
                ))}
              </div>
            </div>
          )}

          <p className="forecast-combo-note">{analysis.disclaimer}</p>
        </>
      )}
    </section>
  );
}
