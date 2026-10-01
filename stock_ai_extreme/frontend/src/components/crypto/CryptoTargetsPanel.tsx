/**
 * Phase 22C — TARGETS subcategory (spec §10–§13, §17, §36).
 *
 * Three real, backend-calculated surfaces:
 *   • the derived reference ladder (real historical swing structure);
 *   • the target comparison table (status / distance / touches / last touch);
 *   • the threshold analyzer — a factual on-date observation shown separately
 *     from a MODELLED probability estimate.
 *
 * Statuses come from the backend (`evaluate_target`); the frontend can never
 * mark a target reached. Distances are server-calculated against the live price.
 */
import { useMemo, useState } from "react";

import type { EvaluatedTarget, LadderLevel, TargetsResponse, ThresholdResponse } from "../../lib/crypto";
import {
  useCryptoOnDate,
  useCryptoThreshold,
} from "../../hooks/useCryptoQueries";
import { formatDateTime, formatPercent, formatPrice, NA, originLabel } from "../../lib/cryptoFormat";
import { CryptoEmpty, CryptoPanel, CryptoStat, CryptoWidgetError } from "./CryptoStates";

const TARGET_FILTERS: { id: string; label: string; days: number | null }[] = [
  { id: "ALL", label: "ALL", days: null },
  { id: "24H", label: "24H", days: 1 },
  { id: "7D", label: "7D", days: 7 },
  { id: "30D", label: "30D", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "1Y", label: "1Y", days: 365 },
];

const STATUS_TONE: Record<string, string> = {
  ACTIVE: "native",
  REACHED: "live",
  MISSED: "warn",
  EXPIRED: "warn",
  INVALIDATED: "danger",
};

export interface CryptoTargetsPanelProps {
  symbol: string;
  timeframe: string;
  data: TargetsResponse | undefined;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function CryptoTargetsPanel({
  symbol,
  timeframe,
  data,
  loading,
  error,
  onRetry,
}: CryptoTargetsPanelProps) {
  const [filter, setFilter] = useState("ALL");
  const days = TARGET_FILTERS.find((f) => f.id === filter)?.days ?? null;

  const targets = useMemo(() => {
    const rows = data?.targets ?? [];
    if (days === null) return rows;
    const cutoff = Date.now() - days * 86400_000;
    return rows.filter((row) => {
      const stamp = row.last_touched_at ?? row.target.created_at;
      const time = stamp ? new Date(stamp).getTime() : NaN;
      return Number.isFinite(time) ? time >= cutoff : true;
    });
  }, [data?.targets, days]);

  return (
    <>
      <CryptoPanel
        title={`Target ladder · ${symbol}`}
        badge={
          data ? (
            <span className="crypto-chip">
              {data.active_count} active · {data.reached_count} reached · {data.lookback_days}d lookback
            </span>
          ) : undefined
        }
        className="crypto-targets-panel"
      >
        {loading && !data && <CryptoEmpty reason="Loading target levels…" />}
        {error && <CryptoWidgetError title="TARGETS UNAVAILABLE" message={error} onRetry={onRetry} />}
        {!loading && !error && !data && <CryptoEmpty reason="No target data was returned for this asset." />}

        {data && data.derived_ladder.length === 0 && data.targets.length === 0 && (
          <CryptoEmpty
            reason="No analytical target levels are available yet."
            hint="Derived levels need at least 30 real candles of history; user targets appear once recorded."
          />
        )}

        {data && data.derived_ladder.length > 0 && (
          <div className="crypto-table-wrap">
            <table className="crypto-table">
              <caption className="sr-only">Derived reference ladder from real historical price structure</caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">Level</th>
                  <th scope="col">Type</th>
                  <th scope="col">Distance</th>
                  <th scope="col">Distance %</th>
                  <th scope="col">Observed at</th>
                  <th scope="col">Methodology</th>
                </tr>
              </thead>
              <tbody>
                {data.derived_ladder.map((level: LadderLevel) => (
                  <tr key={`${level.rank}-${level.target_price}`}>
                    <td>{level.rank}</td>
                    <td>
                      <b>{formatPrice(level.target_price)}</b>{" "}
                      <span className={level.direction === "above" ? "pos" : "neg"}>
                        {level.direction === "above" ? "↑" : "↓"}
                      </span>
                    </td>
                    <td>{level.level_type}</td>
                    <td>{formatPrice(level.distance)}</td>
                    <td className={level.distance_percent >= 0 ? "pos" : "neg"}>
                      {formatPercent(level.distance_percent)}
                    </td>
                    <td>{formatDateTime(level.observed_at)}</td>
                    <td className="dim">{level.methodology}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data?.note && <p className="crypto-note">{data.note}</p>}
      </CryptoPanel>

      <CryptoPanel
        title={`Target comparison · ${timeframe}`}
        badge={
          <div className="crypto-horizon-control" role="group" aria-label="Target history filter">
            {TARGET_FILTERS.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={item.id === filter}
                className={item.id === filter ? "active" : undefined}
                onClick={() => setFilter(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
        className="crypto-targets-compare"
      >
        {!loading && data && targets.length === 0 && (
          <CryptoEmpty reason={`No targets fall within the ${filter} window.`} />
        )}
        {targets.length > 0 && (
          <div className="crypto-table-wrap">
            <table className="crypto-table">
              <caption className="sr-only">Recorded targets evaluated against real candles</caption>
              <thead>
                <tr>
                  <th scope="col">Target</th>
                  <th scope="col">Dir.</th>
                  <th scope="col">Current distance</th>
                  <th scope="col">Distance %</th>
                  <th scope="col">Historical touches</th>
                  <th scope="col">Last touch</th>
                  <th scope="col">Status</th>
                  <th scope="col">Modelled estimate</th>
                </tr>
              </thead>
              <tbody>
                {targets.map((row: EvaluatedTarget) => (
                  <tr key={row.target.id}>
                    <td><b>{formatPrice(row.target.target_price)}</b></td>
                    <td>{row.target.direction}</td>
                    <td>{formatPrice(row.proximity?.distance ?? null)}</td>
                    <td className={(row.proximity?.distance ?? 0) >= 0 ? "pos" : "neg"}>
                      {formatPercent(row.proximity?.distance_percent ?? null)}
                    </td>
                    <td>{row.touch_count ?? NA}</td>
                    <td>{row.last_touched_at ? formatDateTime(row.last_touched_at) : NA}</td>
                    <td>
                      <span className={`crypto-chip ${STATUS_TONE[row.status] ?? ""}`}>{row.status}</span>
                    </td>
                    <td className="dim">see threshold analyzer</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CryptoPanel>

      <CryptoThresholdAnalyzer
        symbol={symbol}
        timeframe={timeframe}
        currentPrice={data?.current_price ?? null}
      />
    </>
  );
}

export interface CryptoThresholdAnalyzerProps {
  symbol: string;
  timeframe: string;
  currentPrice: number | null;
}

export function CryptoThresholdAnalyzer({
  symbol,
  timeframe,
  currentPrice,
}: CryptoThresholdAnalyzerProps) {
  const [thresholdInput, setThresholdInput] = useState<string>("");
  const [date, setDate] = useState<string>("");
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [runOnDate, setRunOnDate] = useState(false);

  const threshold = thresholdInput.trim() === "" ? null : Number(thresholdInput);
  const validThreshold = threshold !== null && Number.isFinite(threshold) && threshold > 0 ? threshold : null;

  const modelled = useCryptoThreshold(symbol, timeframe, validThreshold, 5);
  const onDate = useCryptoOnDate(symbol, date || null, validThreshold, runOnDate && Boolean(date));

  return (
    <CryptoPanel title="Threshold analyzer" className="crypto-threshold-panel">
      <div className="crypto-threshold-form">
        <label>
          Threshold price
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="any"
            placeholder={currentPrice ? `e.g. ${Math.round(currentPrice * 1.05)}` : "e.g. 85000"}
            value={thresholdInput}
            onChange={(event) => setThresholdInput(event.target.value)}
          />
        </label>
        <label>
          Direction
          <select value={direction} onChange={(event) => setDirection(event.target.value as "above" | "below")}>
            <option value="above">Above</option>
            <option value="below">Below</option>
          </select>
        </label>
        <label>
          Target date (observed result)
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </label>
        <button
          type="button"
          className="crypto-probe-btn"
          disabled={!date || !validThreshold}
          onClick={() => setRunOnDate(true)}
        >
          Check date
        </button>
      </div>

      <div className="crypto-threshold-split">
        <div className="crypto-threshold-block observed">
          <h4>
            Observed result <span className="crypto-chip">source data</span>
          </h4>
          {!validThreshold && <p className="empty">Enter a threshold price to evaluate.</p>}
          {validThreshold && !date && (
            <p className="empty">Pick a target date to retrieve the factual historical observation.</p>
          )}
          {runOnDate && onDate.isLoading && <p className="empty">Reading historical observation…</p>}
          {runOnDate && onDate.isError && (
            <CryptoWidgetError
              title="OBSERVATION UNAVAILABLE"
              message={(onDate.error as Error).message}
              onRetry={() => onDate.refetch()}
            />
          )}
          {runOnDate && onDate.data && (
            <ObservedResult data={onDate.data} threshold={validThreshold} direction={direction} />
          )}
        </div>

        <div className="crypto-threshold-block modelled">
          <h4>
            Modelled estimate <span className="crypto-model-chip">MODELLED PROBABILITY</span>
          </h4>
          {!validThreshold && <p className="empty">Enter a threshold price to compute a probability.</p>}
          {validThreshold && modelled.isLoading && <p className="empty">Computing modelled probability…</p>}
          {validThreshold && modelled.isError && (
            <CryptoWidgetError
              title="MODEL ESTIMATE UNAVAILABLE"
              message={(modelled.error as Error).message}
              onRetry={() => modelled.refetch()}
            />
          )}
          {validThreshold && modelled.data && <ModelledResult data={modelled.data} />}
        </div>
      </div>
    </CryptoPanel>
  );
}

function ObservedResult({
  data,
  threshold,
  direction,
}: {
  data: Record<string, unknown>;
  threshold: number | null;
  direction: "above" | "below";
}) {
  const status = String(data.status ?? "");
  const answer = data.answer;
  const observation = (data.observation ?? null) as Record<string, unknown> | null;
  const date = data.date as string | undefined;

  if (status !== "ANSWERED") {
    return (
      <CryptoEmpty
        title="NO DATA AVAILABLE"
        reason={String(data.reason ?? "The source history does not cover that date.")}
      />
    );
  }

  return (
    <div className="crypto-threshold-result">
      <div className={`crypto-threshold-answer ${answer ? "pos" : "neg"}`} role="status">
        {answer ? "YES" : "NO"} — the asset was {answer ? "" : "not "}
        {direction} {formatPrice(threshold)} on {date}
      </div>
      {observation && (
        <div className="crypto-stat-grid compact">
          <CryptoStat label="Observed at" value={formatDateTime(observation.observation_timestamp as string)} />
          <CryptoStat label="Close" value={formatPrice(observation.close as number)} />
          <CryptoStat label="High" value={formatPrice(observation.high as number)} />
          <CryptoStat label="Low" value={formatPrice(observation.low as number)} />
          <CryptoStat label="Source" value={String(observation.origin ?? NA)} />
          <CryptoStat label="Evidence" value={String(data.evidence ?? NA)} />
        </div>
      )}
    </div>
  );
}

function ModelledResult({ data }: { data: ThresholdResponse }) {
  const probabilities = data.probabilities;
  const calibration = data.calibration;

  if (!probabilities) {
    return (
      <CryptoEmpty
        title="MODELLED PROBABILITY UNAVAILABLE"
        reason={String(data.reason ?? "Not enough history to support a probability estimate.")}
      />
    );
  }

  return (
    <div className="crypto-threshold-result">
      <div className="crypto-stat-grid compact">
        <CryptoStat
          label="Empirical"
          value={probabilities.empirical != null ? `${(probabilities.empirical * 100).toFixed(1)}%` : NA}
          sub={`${probabilities.samples} h-step returns`}
        />
        <CryptoStat
          label="Lognormal (GBM)"
          value={probabilities.model_gbm != null ? `${(probabilities.model_gbm * 100).toFixed(1)}%` : NA}
        />
        <CryptoStat
          label="Distance"
          value={formatPercent((data.distance_percent as number) ?? null)}
        />
        <CryptoStat
          label="Current price"
          value={formatPrice((data.current_price as number) ?? null)}
          sub={originLabel((data.origin as string) ?? null)}
        />
      </div>
      {calibration && calibration.status === "OK" && (
        <div className="crypto-stat-grid compact">
          <CryptoStat label="Brier score" value={fmtNum(calibration.brier_score)} sub="lower is better" />
          <CryptoStat
            label="Brier skill"
            value={fmtNum(calibration.brier_skill_score)}
            sub="vs base-rate forecast"
          />
          <CryptoStat label="Calibration samples" value={String(calibration.samples ?? NA)} />
        </div>
      )}
      <p className="crypto-note">
        {data.note ?? "Analytical estimate — not a guaranteed outcome."}
      </p>
    </div>
  );
}

function fmtNum(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : NA;
}

export default CryptoTargetsPanel;
