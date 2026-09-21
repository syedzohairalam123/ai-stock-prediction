/**
 * Phase 17 (spec §9) — impact sparkline.
 *
 * A small timeline of the **real** bars that bracket a story:
 *
 *     news published ── bar before ── movement ── current value
 *
 * Every x position is the bar's own timestamp, so the marker for publication
 * lands where the publisher's clock says it does. When a window has fewer than
 * two timestamped points, or the provider answered nothing, the component says
 * so instead of drawing a line through invented data.
 */
import { useMemo } from "react";
import type { ImpactSeriesPoint } from "../../lib/breakingNews";
import { formatClock } from "../../lib/breakingNews";

interface Props {
  points: ImpactSeriesPoint[];
  publishedAt: string;
  width?: number;
  height?: number;
  /** Positive-up colouring is derived from the first/last real close. */
  ariaLabel?: string;
  showAxisLabels?: boolean;
}

interface Plotted {
  x: number;
  y: number;
  close: number;
  timestamp: number;
}

const PAD = { top: 10, right: 10, bottom: 16, left: 10 };

export default function ImpactSparkline({
  points,
  publishedAt,
  width = 320,
  height = 84,
  ariaLabel,
  showAxisLabels = true,
}: Props) {
  const plotted = useMemo<{
    path: string;
    dots: Plotted[];
    markerX: number | null;
    change: number | null;
    changePercent: number | null;
    min: number;
    max: number;
  } | null>(() => {
    const usable = points
      .filter((p) => p.close !== null && p.close !== undefined && !Number.isNaN(Number(p.close)))
      .map((p) => ({ ts: new Date(p.timestamp).getTime(), close: Number(p.close) }))
      .filter((p) => !Number.isNaN(p.ts))
      .sort((a, b) => a.ts - b.ts);

    if (usable.length < 2) return null;

    const publishedTs = new Date(publishedAt).getTime();
    const times = usable.map((p) => p.ts);
    const closes = usable.map((p) => p.close);
    if (Number.isNaN(publishedTs)) times.push(publishedTs);

    const minT = Math.min(...times);
    const maxT = Math.max(...times);
    const minC = Math.min(...closes);
    const maxC = Math.max(...closes);
    const spanT = maxT - minT || 1;
    const spanC = maxC - minC || Math.abs(maxC) * 0.001 || 1;

    const innerW = width - PAD.left - PAD.right;
    const innerH = height - PAD.top - PAD.bottom;

    const dots: Plotted[] = usable.map((p) => ({
      x: PAD.left + ((p.ts - minT) / spanT) * innerW,
      y: PAD.top + innerH - ((p.close - minC) / spanC) * innerH,
      close: p.close,
      timestamp: p.ts,
    }));

    const markerX = publishedTs >= minT && publishedTs <= maxT
      ? PAD.left + ((publishedTs - minT) / spanT) * innerW
      : null;

    const first = usable[0].close;
    const last = usable[usable.length - 1].close;

    return {
      path: dots.map((d, i) => `${i === 0 ? "M" : "L"}${d.x.toFixed(1)},${d.y.toFixed(1)}`).join(" "),
      dots,
      markerX,
      change: last - first,
      changePercent: first !== 0 ? ((last - first) / Math.abs(first)) * 100 : null,
      min: minC,
      max: maxC,
    };
  }, [points, publishedAt, width, height]);

  if (!plotted) {
    return (
      <div className="bn-spark-empty" role="img" aria-label="Market series unavailable">
        Not enough timestamped bars to plot a series.
      </div>
    );
  }

  const rising = (plotted.change ?? 0) >= 0;
  const stroke = rising ? "var(--green)" : "var(--red)";
  const first = plotted.dots[0];
  const last = plotted.dots[plotted.dots.length - 1];

  return (
    <figure className="bn-spark">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={
          ariaLabel ??
          `Observed price series across ${plotted.dots.length} bars; change ${plotted.change?.toFixed(4)}`
        }
      >
        <line
          x1={PAD.left}
          y1={PAD.top + (height - PAD.top - PAD.bottom) / 2}
          x2={width - PAD.right}
          y2={PAD.top + (height - PAD.top - PAD.bottom) / 2}
          stroke="var(--border)"
          strokeWidth={1}
          strokeDasharray="2 4"
        />
        {/* Publication marker: the publisher's own timestamp, not render time. */}
        {plotted.markerX !== null && (
          <g>
            <line
              x1={plotted.markerX}
              y1={PAD.top - 4}
              x2={plotted.markerX}
              y2={height - PAD.bottom + 2}
              stroke="var(--orange)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text x={plotted.markerX + 3} y={PAD.top - 1} fontSize={9} fill="var(--orange)">
              news
            </text>
          </g>
        )}
        <path d={plotted.path} fill="none" stroke={stroke} strokeWidth={1.6} strokeLinejoin="round" />
        <circle cx={first.x} cy={first.y} r={2.4} fill="var(--text3)" />
        <circle cx={last.x} cy={last.y} r={2.8} fill={stroke} />
        {showAxisLabels && (
          <>
            <text x={PAD.left} y={height - 4} fontSize={9} fill="var(--text3)">
              {formatClock(new Date(plotted.dots[0].timestamp).toISOString())}
            </text>
            <text x={width - PAD.right} y={height - 4} fontSize={9} fill="var(--text3)" textAnchor="end">
              {formatClock(new Date(plotted.dots[plotted.dots.length - 1].timestamp).toISOString())}
            </text>
          </>
        )}
      </svg>
      <figcaption className="bn-spark-caption">
        <span>
          {plotted.dots.length} real bars · {plotted.min.toFixed(4)} – {plotted.max.toFixed(4)}
        </span>
        <span className={rising ? "bn-pos" : "bn-neg"}>
          {plotted.change !== null ? `${plotted.change > 0 ? "+" : ""}${plotted.change.toFixed(4)}` : "unavailable"}
          {plotted.changePercent !== null && ` (${plotted.changePercent > 0 ? "+" : ""}${plotted.changePercent.toFixed(2)}%)`}
        </span>
      </figcaption>
    </figure>
  );
}
