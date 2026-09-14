import { useMemo } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout } from "plotly.js";
import { SentimentPoint, getSentimentLabel, getSentimentColor } from "../lib/sentimentService";

interface SentimentTrendChartProps {
  trendData: SentimentPoint[];
  height?: number;
  showTooltip?: boolean;
}

export default function SentimentTrendChart({
  trendData,
  height = 200,
  showTooltip = true,
}: SentimentTrendChartProps) {
  const traces = useMemo<Data[]>(() => {
    if (!trendData || trendData.length === 0) return [];

    const dates = trendData.map((p) => p.date);
    const scores = trendData.map((p) => p.score);
    const labels = trendData.map((p) => getSentimentLabel(p.score));
    const colors = trendData.map((p) => getSentimentColor(p.score));

    // Create gradient fill based on sentiment
    const lastScore = scores[scores.length - 1];
    const lineColor = getSentimentColor(lastScore);
    const fillColor = lineColor.replace(")", ", 0.15)").replace("rgb", "rgba");

    return [
      {
        type: "scatter",
        mode: "lines",
        x: dates,
        y: scores,
        name: "Sentiment Score",
        line: {
          color: lineColor,
          width: 2.5,
          shape: "spline",
          smoothing: 0.8,
        },
        fill: "tozeroy",
        fillcolor: fillColor,
        customdata: trendData.map((p) => [
          p.date,
          p.score.toFixed(1),
          getSentimentLabel(p.score),
        ]),
        hovertemplate: showTooltip
          ? "<b>%{customdata[0]}</b><br>" +
            "Score: <b>%{customdata[1]}</b><br>" +
            "Sentiment: %{customdata[2]}" +
            "<extra></extra>"
          : "<extra></extra>",
        hoverlabel: {
          bgcolor: "#0d1424",
          bordercolor: "#31436d",
          font: { color: "#e6edf7", size: 11 },
        },
      } as Data,
    ];
  }, [trendData, showTooltip]);

  const layout = useMemo<Partial<Layout>>(() => {
    return {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: "#9daed1", size: 11 },
      margin: { t: 10, l: 40, r: 10, b: 30 },
      dragmode: "pan",
      hovermode: "x unified",
      hoverlabel: { bgcolor: "#0d1424", bordercolor: "#31436d", font: { color: "#e6edf7", size: 11 } },
      xaxis: {
        gridcolor: "rgba(38,52,88,.5)",
        showgrid: false,
        tickfont: { size: 9 },
        showspikes: true,
        spikemode: "across",
        spikethickness: 1,
        spikedash: "solid",
        spikecolor: "rgba(157,174,209,.55)",
        type: "date",
      },
      yaxis: {
        gridcolor: "rgba(38,52,88,.5)",
        tickfont: { size: 10 },
        range: [0, 100],
        fixedrange: true,
        showspikes: true,
        spikemode: "across",
        spikethickness: 1,
        spikedash: "solid",
        spikecolor: "rgba(157,174,209,.55)",
      },
      showlegend: false,
    };
  }, []);

  if (!trendData || trendData.length === 0) {
    return (
      <div className="sentiment-chart-empty">
        <span>No trend data available</span>
      </div>
    );
  }

  return (
    <div className="sentiment-trend-chart">
      <Plot
        data={traces}
        layout={layout}
        config={{
          responsive: true,
          displaylogo: false,
          scrollZoom: true,
          modeBarButtonsToRemove: ["lasso2d", "select2d"],
        }}
        style={{ width: "100%", height }}
        useResizeHandler
      />
    </div>
  );
}