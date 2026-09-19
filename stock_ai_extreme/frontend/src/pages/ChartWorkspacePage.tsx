/**
 * Phase 11 — `/charts`: the professional charting & technical-analysis page.
 *
 * Thin page shell around `ChartWorkspace`. Its only logic is deep-linking, done
 * the same way the rest of the terminal does it (`/market?index=…&tf=…`):
 * incoming `?symbol=&tf=&layout=&chart=` params seed the workspace once, then the
 * active chart's symbol/timeframe are kept in the URL so a view can be shared or
 * reloaded. Param writes use `replace` so panning between symbols does not spam
 * the history stack.
 */
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import ChartWorkspace from "../components/charting/ChartWorkspace";
import { CHART_IDS } from "../lib/charting/defaults";
import { inferEntityType } from "../lib/charting/dataSource";
import { isStockRange, type StockRange } from "../lib/timeframes";
import { selectChart, useChartStore } from "../store/useChartStore";

export default function ChartWorkspacePage() {
  const [params, setParams] = useSearchParams();

  const layout = useChartStore((s) => s.layout);
  const activeId = useChartStore((s) => s.activeId);
  const activeChart = useChartStore((s) => selectChart(s, s.activeId));
  const setLayout = useChartStore((s) => s.setLayout);
  const setActiveChart = useChartStore((s) => s.setActiveChart);
  const setSymbol = useChartStore((s) => s.setSymbol);
  const setEntityType = useChartStore((s) => s.setEntityType);
  const setTimeframe = useChartStore((s) => s.setTimeframe);

  const seeded = useRef(false);

  // Seed from the URL exactly once per mount.
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;

    const chartParam = params.get("chart");
    const targetId = CHART_IDS.find((id) => id === chartParam) ?? (chartParam === "b" ? CHART_IDS[1] : null);
    if (targetId) setActiveChart(targetId);

    const layoutParam = params.get("layout");
    if (layoutParam === "split" || layoutParam === "single") setLayout(layoutParam);

    const symbol = params.get("symbol");
    if (symbol) {
      setSymbol(targetId ?? activeId, symbol);
      setEntityType(targetId ?? activeId, inferEntityType(symbol));
    }

    const tf = params.get("tf");
    if (isStockRange(tf)) setTimeframe(targetId ?? activeId, tf as StockRange);
    // Intentionally mount-only: afterwards the store is the source of truth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL describing the active chart (shareable / reloadable).
  useEffect(() => {
    const next = new URLSearchParams(params);
    let changed = false;
    const describe = () => {
      if (next.get("symbol") !== activeChart.symbol) {
        next.set("symbol", activeChart.symbol);
        changed = true;
      }
      if (next.get("tf") !== activeChart.timeframe) {
        next.set("tf", activeChart.timeframe);
        changed = true;
      }
      if (next.get("layout") !== layout) {
        next.set("layout", layout);
        changed = true;
      }
      const chartKey = activeId === CHART_IDS[1] ? "b" : "a";
      if (next.get("chart") !== chartKey) {
        next.set("chart", chartKey);
        changed = true;
      }
    };
    describe();
    if (changed) setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChart.symbol, activeChart.timeframe, layout, activeId]);

  return (
    <main className="chart-page">
      <div className="psx-page-head">
        <div>
          <p>Professional charting & technical analysis</p>
          <h1>Charts</h1>
        </div>
        <span className="chart-meta-chip brand" title="Indicators: SMA 20/50, EMA, VWAP, Bollinger Bands">
          SMA · EMA · VWAP · Bollinger
        </span>
      </div>

      <ChartWorkspace />
    </main>
  );
}
