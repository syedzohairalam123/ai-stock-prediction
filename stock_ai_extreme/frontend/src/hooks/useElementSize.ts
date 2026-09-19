/**
 * Phase 11 — element size hook.
 *
 * The annotation overlay has to agree with Plotly about the plot rectangle, so
 * the panel needs the container's live pixel size (not just its CSS width) and
 * must update on split/fullscreen/rotation. `ResizeObserver` is the only reliable
 * way to catch all of those; the returned value is rounded to whole pixels so a
 * sub-pixel layout jitter does not re-render the chart on every frame.
 */
import { useEffect, useRef, useState } from "react";

export interface ElementSize {
  width: number;
  height: number;
}

export function useElementSize<T extends HTMLElement = HTMLDivElement>(): {
  ref: React.RefObject<T>;
  size: ElementSize;
} {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 });

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const apply = () => {
      const rect = node.getBoundingClientRect();
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    };

    apply();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", apply);
      return () => window.removeEventListener("resize", apply);
    }
    const observer = new ResizeObserver(apply);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return { ref, size };
}
