/**
 * Phase 19 §12 — a small sparkline drawn from *actual stored observations*.
 *
 * The backend returns the points and explainable analytics; this component
 * only renders them. With fewer than two observations it shows N/A instead of
 * a confident-looking line through a single dot — no path is ever invented.
 */
import { useMemo } from "react";
import { useTrendHistory } from "../../hooks/useDiscoveryQueries";

interface TrendSparklineProps {
  entityId: string;
  height?: number;
  /** Optional pre-fetched history (avoids a second request when available). */
  enabled?: boolean;
}

export default function TrendSparkline({ entityId, height = 34, enabled = true }: TrendSparklineProps) {
  const { data, isFetching, isError } = useTrendHistory(entityId, { enabled });

  const geometry = useMemo(() => {
    const series = (data?.analytics?.scoreSeries ?? []).filter(
      (v): v is number => typeof v === "number"
    );
    if (series.length < 2) return null;
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || 1;
    const width = 100;
    const points = series.map((value, index) => {
      const x = (index / (series.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return { polyline: points.join(" "), last: series[series.length - 1], first: series[0] };
  }, [data, height]);

  if (isError) {
    return (
      <span className="disc-spark disc-spark-na" title="Trend history could not be loaded.">
        N/A
      </span>
    );
  }

  if (!geometry) {
    return (
      <span
        className="disc-spark disc-spark-na"
        title={
          isFetching
            ? "Loading stored observations…"
            : "Fewer than two observations recorded yet — the sparkline draws real history only."
        }
      >
        {isFetching ? "…" : "N/A"}
      </span>
    );
  }

  const rising = geometry.last >= geometry.first;
  const direction = data?.analytics?.direction ?? "STABLE";

  return (
    <span
      className={`disc-spark ${rising ? "up" : "down"}`}
      title={`${data?.analytics?.count ?? 0} stored observations (${
        data?.seriesSource === "news_timeline" ? "news timeline" : "sampled"
      }) · trend ${direction.toLowerCase()}`}
    >
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" role="img" aria-label={`Trend sparkline, ${direction.toLowerCase()}`}>
        <polyline
          points={geometry.polyline}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="disc-spark-dir" aria-hidden="true">
        {direction === "RISING" ? "▲" : direction === "FALLING" ? "▼" : "–"}
      </span>
    </span>
  );
}
