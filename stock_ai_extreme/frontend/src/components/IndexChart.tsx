import { useEffect, useMemo, useState } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout } from "plotly.js";
import type { OHLCVPoint, Timeframe } from "../lib/psxMarket";
import {
  TIMEFRAMES,
  fmtCompact,
  fmtNum,
  fmtPointTime,
  getHistoryAsync,
  getPeriodStats,
} from "../lib/psxMarket";

type ChartType = "area" | "line" | "candles";

interface Props {
  symbol: string;
  name: string;
  /** Previous close of the selected index — draws the dashed reference line on 1D. */
  prevClose?: number;
  /** Optional controlled timeframe (hoisted so the URL can share/deep-link it). */
  timeframe?: Timeframe;
  onTimeframeChange?: (tf: Timeframe) => void;
}

const UP = "#4ade80";
const DOWN = "#fb7185";
const LINE = "#2dd4bf";

export default function IndexChart({ symbol, name, prevClose, timeframe, onTimeframeChange }: Props) {
  const [tfInternal, setTfInternal] = useState<Timeframe>("1M");
  const tf = timeframe ?? tfInternal;
  const setTf = (t: Timeframe) => {
    setTfInternal(t);
    onTimeframeChange?.(t);
  };
  const [chartType, setChartType] = useState<ChartType>("area");
  const [showVolume, setShowVolume] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [points, setPoints] = useState<OHLCVPoint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setPoints(null);
    getHistoryAsync(symbol, tf)
      .then((p) => alive && setPoints(p))
      .catch((e) => alive && setError(e?.message || "Failed to load chart data"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [symbol, tf]);

  const intraday = tf === "1D";

  const model = useMemo(() => {
    if (!points || points.length === 0) return null;
    const times = points.map((p) => p.time);
    const spacingMs =
      points.length > 1
        ? Math.max(
            60_000,
            new Date(points[1].time.replace(" ", "T")).getTime() -
              new Date(points[0].time.replace(" ", "T")).getTime()
          )
        : 86_400_000;
    return {
      times,
      opens: points.map((p) => p.open),
      highs: points.map((p) => p.high),
      lows: points.map((p) => p.low),
      closes: points.map((p) => p.close),
      volumes: points.map((p) => p.volume),
      barWidthMs: spacingMs * 0.68,
      maxVolume: Math.max(...points.map((p) => p.volume), 1),
      stats: getPeriodStats(points),
      ohlcCustom: points.map((p) => [
        fmtPointTime(p.time, intraday),
        fmtNum(p.open),
        fmtNum(p.high),
        fmtNum(p.low),
        fmtNum(p.close),
        fmtCompact(p.volume),
      ]),
    };
  }, [points, intraday]);

  const lastClose = points?.length ? points[points.length - 1].close : null;
  const stats = model?.stats ?? null;

  const traces = useMemo<Data[]>(() => {
    if (!model) return [];
    const out: Data[] = [];

    if (chartType === "candles") {
      out.push({
        type: "candlestick",
        x: model.times,
        open: model.opens,
        high: model.highs,
        low: model.lows,
        close: model.closes,
        increasing: { line: { color: UP, width: 1.4 } },
        decreasing: { line: { color: DOWN, width: 1.4 } },
        whiskerwidth: 0.4,
        name: name,
        hoverlabel: { bgcolor: "#0d1424", bordercolor: "#31436d", font: { color: "#e6edf7", size: 11 } },
      } as Data);
    } else {
      out.push({
        type: "scatter",
        mode: "lines",
        x: model.times,
        y: model.closes,
        name: name,
        line: {
          color: LINE,
          width: Math.max(1.4, Math.min(2.4, 340 / model.times.length)),
          shape: "spline",
          smoothing: 0.8,
        },
        ...(chartType === "area"
          ? { fill: "tozeroy", fillcolor: "rgba(45,212,191,.10)" }
          : {}),
        customdata: model.ohlcCustom,
        hovertemplate:
          "<b>%{customdata[0]}</b><br>" +
          "Open: %{customdata[1]}<br>" +
          "High: %{customdata[2]}<br>" +
          "Low: %{customdata[3]}<br>" +
          "Close: <b>%{customdata[4]}</b><br>" +
          "Vol: %{customdata[5]}" +
          "<extra></extra>",
      } as Data);
    }

    if (intraday && prevClose != null) {
      out.push({
        type: "scatter",
        mode: "lines",
        x: [model.times[0], model.times[model.times.length - 1]],
        y: [prevClose, prevClose],
        name: "Prev close",
        line: { color: "rgba(157,174,209,.8)", width: 1.2, dash: "dot" },
        hoverinfo: "skip",
      } as Data);
    }

    if (showVolume) {
      out.push({
        type: "bar",
        x: model.times,
        y: model.volumes,
        yaxis: "y2",
        name: "Volume",
        marker: { color: "rgba(99,102,241,.45)", line: { width: 0 } },
        width: chartType === "candles" ? model.barWidthMs : undefined,
        hovertemplate: "Vol: %{y:,.0f}<extra></extra>",
        showlegend: false,
      } as Data);
    }

    return out;
  }, [model, chartType, intraday, prevClose, showVolume, name]);

  const layout = useMemo<Partial<Layout>>(() => {
    const volHeight = showVolume ? 0.24 : 0;
    return {
      uirevision: `${symbol}:${tf}:${chartType}:${showVolume}`,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#9daed1", size: 11 },
      margin: { t: 8, l: 58, r: 14, b: 36 },
      bargap: 0,
      dragmode: "pan",
      hovermode: "x unified",
      hoverlabel: { bgcolor: "#0d1424", bordercolor: "#31436d", font: { color: "#e6edf7", size: 11 } },
      xaxis: {
        gridcolor: "rgba(38,52,88,.5)",
        showgrid: false,
        tickfont: { size: 10 },
        showspikes: true,
        spikemode: "across",
        spikethickness: 1,
        spikedash: "solid",
        spikecolor: "rgba(157,174,209,.55)",
      },
      yaxis: {
        gridcolor: "rgba(38,52,88,.5)",
        tickfont: { size: 10 },
        domain: showVolume ? [volHeight + 0.04, 1] : [0, 1],
        showspikes: true,
        spikemode: "across",
        spikethickness: 1,
        spikedash: "solid",
        spikecolor: "rgba(157,174,209,.55)",
      },
      ...(showVolume
        ? {
            yaxis2: {
              domain: [0, volHeight],
              range: [0, (model?.maxVolume ?? 1) * 4],
              fixedsize: true,
              visible: false,
              type: "linear" as const,
            },
          }
        : {}),
    };
  }, [symbol, tf, chartType, showVolume, model]);

  return (
    <section className={`panel index-chart-panel${expanded ? " expanded" : ""}`}>
      <div className="index-chart-head">
        <div>
          <h2>{name}</h2>
          <span className="index-chart-tf-label">
            Timeframe · {tf} {intraday ? "· intraday" : "· daily"}
          </span>
        </div>
        <div className="index-chart-tabs">
          {TIMEFRAMES.map((t) => (
            <button key={t} className={t === tf ? "active" : ""} onClick={() => setTf(t)}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="index-chart-toolbar">
        <div className="index-chart-modes" role="group" aria-label="Chart type">
          {(["area", "line", "candles"] as ChartType[]).map((m) => (
            <button key={m} className={m === chartType ? "active" : ""} onClick={() => setChartType(m)}>
              {m === "area" ? "Area" : m === "line" ? "Line" : "Candles"}
            </button>
          ))}
        </div>
        <label className="index-chart-toggle">
          <input type="checkbox" checked={showVolume} onChange={(e) => setShowVolume(e.target.checked)} />
          Volume
        </label>
        <button className="index-chart-expand" onClick={() => setExpanded((v) => !v)} aria-pressed={expanded}>
          {expanded ? "Shrink" : "Expand"}
        </button>
      </div>

      {loading && <div className="skeleton skeleton-chart" style={{ height: expanded ? 560 : 380 }} />}

      {!loading && error && (
        <div className="market-state market-state-error">
          <strong>Chart unavailable</strong>
          <span>{error} — try another timeframe.</span>
        </div>
      )}

      {!loading && !error && (!points || points.length === 0) && (
        <div className="market-state">
          <strong>No data for {tf}</strong>
          <span>This timeframe has no historical points yet.</span>
        </div>
      )}

      {!loading && !error && model && stats && (
        <>
          <div className="index-chart-last">
            <span className="index-chart-last-label">Current value</span>
            <span className="index-chart-last-value">{fmtNum(lastClose ?? 0)}</span>
            {stats && (
              <span className={`index-chart-last-chg ${stats.change >= 0 ? "pos" : "neg"}`}>
                {stats.change >= 0 ? "▲ +" : "▼ "}
                {fmtNum(stats.change)} ({stats.change >= 0 ? "+" : ""}
                {stats.changePct.toFixed(2)}%) · {tf}
              </span>
            )}
            <span className="index-chart-count">{stats.points} points</span>
          </div>

          <div className="index-chart-stats">
            <span className="index-chart-stat">
              <em>Open</em>
              {fmtNum(stats.open)}
            </span>
            <span className="index-chart-stat">
              <em>High</em>
              {fmtNum(stats.high)}
            </span>
            <span className="index-chart-stat">
              <em>Low</em>
              {fmtNum(stats.low)}
            </span>
            <span className="index-chart-stat">
              <em>Prev close</em>
              {fmtNum(stats.prevClose)}
            </span>
            <span className="index-chart-stat">
              <em>Volume</em>
              {fmtCompact(stats.volume)}
            </span>
          </div>

          <Plot
            data={traces}
            layout={layout}
            config={{
              responsive: true,
              displaylogo: false,
              scrollZoom: true,
              modeBarButtonsToRemove: ["lasso2d", "select2d"],
            }}
            style={{ width: "100%", height: expanded ? 560 : 380 }}
            useResizeHandler
          />
        </>
      )}
    </section>
  );
}
