/**
 * Phase 12 — Catalysts & News widget (spec §3, §4 CATALYSTS_NEWS).
 *
 * Real live headlines with lexicon sentiment for a selectable PSX ticker or
 * the broader market (^GSPC), reusing the StockDashboard's proven `NewsPanel`.
 * A compact scope switcher edits the widget's own `settings.ticker` through
 * the workspace store — widget isolation stays intact.
 */
import { useEffect, useState } from "react";
import NewsPanel from "../../NewsPanel";

const SCOPES = ["", "OGDC", "LUCK", "HBL", "MEBL", "SYS", "PSO", "ENGRO"] as const;

export default function CatalystsNewsWidget({ settings, onSettingsChange }: WidgetSettingsProps) {
  const [ticker, setTicker] = useState<string>(typeof settings?.ticker === "string" ? settings.ticker : "");
  // Local mirror syncs when the stored settings change externally (preset swap).
  useEffect(() => {
    setTicker(typeof settings?.ticker === "string" ? settings.ticker : "");
  }, [settings?.ticker]);

  const scope = ticker.trim().toUpperCase() || "^GSPC";
  const isMarket = !ticker.trim();

  return (
    <div className="ws-widget-body ws-news-widget">
      <div className="ws-news-scope" role="group" aria-label="News scope">
        <select
          value={ticker}
          onChange={(e) => {
            setTicker(e.target.value);
            onSettingsChange?.({ ticker: e.target.value });
          }}
          aria-label="News ticker scope"
        >
          <option value="">Whole market</option>
          {SCOPES.filter(Boolean).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <span className={`ws-news-scope-chip ${isMarket ? "market" : "ticker"}`}>{scope}</span>
      </div>
      <NewsPanel ticker={scope} />
    </div>
  );
}

interface WidgetSettingsProps {
  settings?: Record<string, unknown>;
  onSettingsChange?: (patch: Record<string, unknown>) => void;
}
