/**
 * Phase 22A — provider sources & health (spec §3, §52/§53).
 *
 * Shows which real, keyless providers are configured, their roles and native
 * intervals, and lets the user issue a live reachability probe. A provider that
 * does not answer is shown as DOWN — never masked.
 */
import { useState } from "react";

import type { ProviderHealthEntry, SourcesResponse } from "../../lib/crypto";
import { CryptoService } from "../../lib/crypto";
import { NA } from "../../lib/cryptoFormat";

export interface CryptoSourcesPanelProps {
  sources: SourcesResponse | undefined;
  health: ProviderHealthEntry[] | undefined;
  loading: boolean;
  error: string | null;
}

export function CryptoSourcesPanel({ sources, health, loading, error }: CryptoSourcesPanelProps) {
  const [probing, setProbing] = useState(false);
  const [probeResult, setProbeResult] = useState<ProviderHealthEntry[] | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  async function runProbe() {
    setProbing(true);
    setProbeError(null);
    try {
      const res = await CryptoService.probeHealth();
      setProbeResult(
        res.data.providers.map((p) => ({
          provider: p.provider,
          status: p.available ? "AVAILABLE" : p.status,
          detail: p.detail,
          latency_ms: p.latency_ms,
        }))
      );
    } catch (e) {
      setProbeError(e instanceof Error ? e.message : "probe failed");
    } finally {
      setProbing(false);
    }
  }

  const rows = probeResult ?? health ?? [];

  return (
    <section className="panel crypto-sources-panel">
      <div className="crypto-panel-head">
        <h2>Data sources</h2>
        <button type="button" className="crypto-probe-btn" onClick={runProbe} disabled={probing}>
          {probing ? "Probing…" : "Probe providers"}
        </button>
      </div>

      {error && <div className="warn-banner" role="alert">{error}</div>}
      {probeError && <div className="warn-banner" role="alert">{probeError}</div>}
      {loading && !sources && <p className="empty">Loading sources…</p>}

      {sources && (
        <div className="crypto-table-wrap">
          <table className="crypto-table">
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">Role</th>
                <th scope="col">Native intervals</th>
                <th scope="col">Streaming</th>
                <th scope="col">Base URL</th>
              </tr>
            </thead>
            <tbody>
              {sources.sources.map((s) => (
                <tr key={s.provider}>
                  <td><b>{s.provider}</b></td>
                  <td>{s.role}</td>
                  <td className="crypto-mono">{s.native_intervals.join(", ") || NA}</td>
                  <td>{s.streaming ? "yes" : "no"}</td>
                  <td className="crypto-mono dim">{s.base_url ?? NA}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="crypto-subhead">Provider health</h3>
      <div className="crypto-health-row">
        {rows.length === 0 && <span className="empty">No health data yet.</span>}
        {rows.map((h) => (
          <div key={h.provider} className={`crypto-health ${healthTone(h.status)}`}>
            <span className="crypto-health-name">{h.provider}</span>
            <span className="crypto-health-status">{h.status}</span>
            {h.latency_ms != null && <span className="crypto-health-lat">{Math.round(h.latency_ms)} ms</span>}
            {h.detail && <span className="crypto-health-detail">{h.detail}</span>}
          </div>
        ))}
      </div>

      {sources?.note && <p className="crypto-note">{sources.note}</p>}
    </section>
  );
}

function healthTone(status: string | null | undefined): string {
  switch ((status ?? "").toUpperCase()) {
    case "AVAILABLE":
    case "UP":
      return "ok";
    case "DEGRADED":
      return "warn";
    case "DOWN":
      return "down";
    default:
      return "";
  }
}

export default CryptoSourcesPanel;
