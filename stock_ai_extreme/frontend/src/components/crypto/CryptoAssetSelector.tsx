/**
 * Phase 22A — asset selector.
 *
 * Driven by the backend's documented catalogue (`GET /assets`) — the UI never
 * hardcodes a coin list. Filter by symbol/name or industry; selecting an asset
 * re-points every panel and the live subscription.
 */
import { useMemo, useState } from "react";

import type { CryptoAsset } from "../../lib/crypto";

export interface CryptoAssetSelectorProps {
  assets: CryptoAsset[];
  selected: string;
  onSelect: (symbol: string) => void;
  loading: boolean;
}

export function CryptoAssetSelector({ assets, selected, onSelect, loading }: CryptoAssetSelectorProps) {
  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState<string>("");

  const industries = useMemo(
    () => Array.from(new Set(assets.map((a) => a.industry))).sort(),
    [assets]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return assets.filter((a) => {
      if (industry && a.industry !== industry) return false;
      if (!q) return true;
      return (
        a.symbol.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q) ||
        a.display.toLowerCase().includes(q)
      );
    });
  }, [assets, query, industry]);

  return (
    <section className="panel crypto-selector" aria-label="Asset selector">
      <div className="crypto-panel-head">
        <h2>Assets</h2>
        <span className="crypto-chip">{assets.length} tracked</span>
      </div>

      <div className="crypto-selector-controls">
        <input
          type="search"
          placeholder="Search BTC, Ethereum, SOL…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search assets"
        />
        <select value={industry} onChange={(e) => setIndustry(e.target.value)} aria-label="Filter by industry">
          <option value="">All industries</option>
          {industries.map((i) => (
            <option key={i} value={i}>
              {i}
            </option>
          ))}
        </select>
      </div>

      {loading && assets.length === 0 && <p className="empty">Loading asset catalogue…</p>}

      <div className="crypto-asset-list" role="listbox" aria-label="Crypto assets">
        {filtered.map((asset) => {
          const active = asset.symbol === selected;
          return (
            <button
              key={asset.symbol}
              type="button"
              role="option"
              aria-selected={active}
              className={`crypto-asset ${active ? "active" : ""}`}
              onClick={() => onSelect(asset.symbol)}
              title={`${asset.name} · ${asset.industry}`}
            >
              <span className="crypto-asset-symbol">{asset.symbol}</span>
              <span className="crypto-asset-name">{asset.name}</span>
              <span className="crypto-asset-industry">{asset.industry}</span>
              {asset.streaming && <span className="crypto-dot" title="Real-time stream available" />}
            </button>
          );
        })}
        {!loading && filtered.length === 0 && <p className="empty">No asset matches that search.</p>}
      </div>
    </section>
  );
}

export default CryptoAssetSelector;
