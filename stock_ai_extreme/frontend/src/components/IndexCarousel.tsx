import { useCallback, useEffect, useRef, useState } from "react";
import type { IndexSnapshot } from "../lib/psxMarket";
import { fmtNum } from "../lib/psxMarket";
import LoadingSkeletonCard from "./MarketSkeletons";

interface Props {
  snapshots: IndexSnapshot[];
  selected: string;
  onSelect: (symbol: string) => void;
  loading?: boolean;
  error?: string | null;
}

/** Tiny inline SVG sparkline — no charting lib needed for the strip. */
function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  const w = 96;
  const h = 26;
  if (!data || data.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * w).toFixed(1)},${(h - ((v - min) / span) * (h - 4) - 2).toFixed(1)}`)
    .join(" ");
  const color = positive ? "#4ade80" : "#fb7185";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
      <polygon points={`0,${h} ${pts} ${w},${h}`} fill={color} opacity="0.12" />
    </svg>
  );
}

export default function IndexCarousel({ snapshots, selected, onSelect, loading, error }: Props) {
  const stripRef = useRef<HTMLDivElement>(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);

  // Drag-to-scroll (pointer) state.
  const drag = useRef({ active: false, startX: 0, startScroll: 0, moved: false });

  const updateArrows = useCallback(() => {
    const el = stripRef.current;
    if (!el) return;
    setCanLeft(el.scrollLeft > 4);
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
  }, []);

  useEffect(() => {
    updateArrows();
    const el = stripRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateArrows, { passive: true });
    window.addEventListener("resize", updateArrows);
    return () => {
      el.removeEventListener("scroll", updateArrows);
      window.removeEventListener("resize", updateArrows);
    };
  }, [updateArrows, snapshots.length]);

  const nudge = (dir: -1 | 1) => {
    const el = stripRef.current;
    if (!el) return;
    el.scrollBy({ left: dir * Math.max(220, el.clientWidth * 0.7), behavior: "smooth" });
  };

  const scrollSelectedIntoView = useCallback(() => {
    const el = stripRef.current;
    if (!el) return;
    const active = el.querySelector<HTMLElement>(".index-card.active");
    active?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, []);

  useEffect(() => {
    scrollSelectedIntoView();
  }, [selected, scrollSelectedIntoView]);

  if (loading)
    return (
      <div className="index-carousel">
        {Array.from({ length: 6 }).map((_, i) => (
          <LoadingSkeletonCard key={i} />
        ))}
      </div>
    );
  if (error) return <div className="index-carousel-error">Failed to load indices — {error}</div>;
  if (!snapshots.length) return <div className="index-carousel-error">No index data available.</div>;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    // Only left button; ignore drags that start on the cards' interactive area.
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const el = stripRef.current;
    if (!el) return;
    drag.current = { active: true, startX: e.clientX, startScroll: el.scrollLeft, moved: false };
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = stripRef.current;
    if (!el || !drag.current.active) return;
    const dx = e.clientX - drag.current.startX;
    if (Math.abs(dx) > 6) {
      drag.current.moved = true;
      el.setPointerCapture(e.pointerId);
    }
    if (drag.current.moved) el.scrollLeft = drag.current.startScroll - dx;
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = stripRef.current;
    if (el && drag.current.active && drag.current.moved) el.releasePointerCapture(e.pointerId);
    drag.current.active = false;
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const symbols = snapshots.map((s) => s.symbol);
    const idx = symbols.indexOf(selected);
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const dir = e.key === "ArrowRight" ? 1 : -1;
      const next = symbols[(idx + dir + symbols.length) % symbols.length];
      onSelect(next);
      requestAnimationFrame(scrollSelectedIntoView);
    } else if (e.key === "Home") {
      e.preventDefault();
      onSelect(symbols[0]);
    } else if (e.key === "End") {
      e.preventDefault();
      onSelect(symbols[symbols.length - 1]);
    }
  };

  return (
    <div className={`index-carousel-wrap${canLeft ? " has-left" : ""}${canRight ? " has-right" : ""}`}>
      {canLeft && (
        <button className="index-carousel-chevron left" aria-label="Scroll indices left" onClick={() => nudge(-1)}>
          ‹
        </button>
      )}
      <div
        className="index-carousel"
        ref={stripRef}
        role="listbox"
        aria-label="PSX indices"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={endDrag}
      >
        {snapshots.map((s) => {
          const up = s.change >= 0;
          const active = s.symbol === selected;
          return (
            <button
              key={s.symbol}
              role="option"
              className={`index-card ${active ? "active" : ""} ${up ? "up" : "down"}`}
              onClick={() => {
                if (!drag.current.moved) onSelect(s.symbol);
              }}
              aria-selected={active}
            >
              <div className="index-card-head">
                <span className="index-card-symbol">{s.symbol}</span>
                <span className={`index-card-change ${up ? "pos" : "neg"}`}>
                  {up ? "▲" : "▼"} {Math.abs(s.changePct).toFixed(2)}%
                </span>
              </div>
              <div className="index-card-value">{fmtNum(s.value)}</div>
              <div className="index-card-sub">
                <span className={up ? "pos" : "neg"}>
                  {up ? "+" : ""}
                  {fmtNum(s.change)}
                </span>
                <Sparkline data={s.sparkline} positive={up} />
              </div>
            </button>
          );
        })}
      </div>
      {canRight && (
        <button className="index-carousel-chevron right" aria-label="Scroll indices right" onClick={() => nudge(1)}>
          ›
        </button>
      )}
    </div>
  );
}
