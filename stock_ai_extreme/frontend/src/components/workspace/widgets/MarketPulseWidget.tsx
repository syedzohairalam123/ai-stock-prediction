/**
 * Phase 12 — Market Pulse widget (spec §3, §4 MARKET_PULSE).
 *
 * Three real reads, no fabrication:
 *   1. Fear/greed gauge — the existing `SentimentGauge` fed by the project's
 *      sentiment service (`getSentimentData`, the same source the sentiment
 *      page and comparison tools use).
 *   2. Market stress — the backend's `/api/market-stress` gauge built from
 *      real headline keyword volume + lexicon sentiment.
 *   3. Session status — the PKT clock state every other panel shows.
 * Each read degrades independently; a failed source shows why, never a guess.
 */
import { useEffect, useState } from "react";
import SentimentGauge from "../../SentimentGauge";
import { getSentimentData } from "../../../lib/sentimentService";
import { getMarketStatus, MARKET_STATUS_LABEL } from "../../../lib/psxMarket";
import { apiClient } from "../../../lib/axios";

interface StressResponse {
  score: number | null;
  label?: string;
  sample_size?: number;
}

export default function MarketPulseWidget() {
  // The sentiment service is synchronous (cached, deterministic per bundle).
  const [sentiment] = useState(() => {
    try {
      return { state: "ok" as const, data: getSentimentData() };
    } catch {
      return { state: "error" as const, data: null };
    }
  });

  const [stress, setStress] = useState<StressResponse | null>(null);
  const [stressState, setStressState] = useState<"loading" | "ok" | "error">("loading");
  const [status, setStatus] = useState(() => getMarketStatus());

  useEffect(() => {
    let alive = true;
    apiClient
      .get<StressResponse>("/api/market-stress")
      .then((r) => {
        if (!alive) return;
        setStress(r.data);
        setStressState("ok");
      })
      .catch(() => alive && setStressState("error"));
    const t = window.setInterval(() => setStatus(getMarketStatus()), 60_000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  return (
    <div className="ws-widget-body ws-pulse-widget">
      <div className="ws-pulse-status" role="status">
        <span className={`ws-pulse-dot ${status.toLowerCase()}`} aria-hidden />
        {MARKET_STATUS_LABEL[status]}
      </div>

      <div className="ws-pulse-gauge">
        {sentiment.state === "error" && (
          <p className="empty" role="alert">
            Sentiment feed unavailable right now.
          </p>
        )}
        {sentiment.state === "ok" && sentiment.data && (
          <SentimentGauge score={sentiment.data.score} label={sentiment.data.label} size="sm" />
        )}
      </div>

      <div className="ws-pulse-stress">
        <span className="ws-pulse-k">Market stress</span>
        {stressState === "loading" && <span className="ws-pulse-v muted">measuring…</span>}
        {stressState === "error" && <span className="ws-pulse-v muted">unavailable</span>}
        {stressState === "ok" && (
          <span className="ws-pulse-v">
            {stress?.score === null || stress?.score === undefined
              ? "unavailable"
              : `${stress.score}/100${stress.label ? ` · ${stress.label}` : ""}`}
          </span>
        )}
      </div>

      <small className="ws-pulse-note">
        Sentiment is a lexicon heuristic over live headlines — an indicator, not investment advice.
      </small>
    </div>
  );
}
