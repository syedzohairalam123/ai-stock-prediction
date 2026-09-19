/**
 * Phase 11 — media-query hook (spec §28).
 *
 * The workspace needs to know *which* responsive mode it is in (not just how it
 * looks), because mobile shows one chart at a time instead of two panels, so the
 * breakpoint has to be readable from JavaScript. Uses `matchMedia` with a change
 * listener and is SSR-safe (no `window` → `false`).
 */
import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(list.matches);
    // `addEventListener` is unavailable in older Safari; the project targets
    // evergreen browsers but the fallback costs nothing.
    if (typeof list.addEventListener === "function") {
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    }
    list.addListener(onChange);
    return () => list.removeListener(onChange);
  }, [query]);

  return matches;
}

/** The workspace's single source of breakpoint truth. */
export const BREAKPOINTS = {
  mobile: "(max-width: 820px)",
  tablet: "(min-width: 821px) and (max-width: 1180px)",
};

export function useIsMobileChart(): boolean {
  return useMediaQuery(BREAKPOINTS.mobile);
}

export function useIsTabletChart(): boolean {
  return useMediaQuery(BREAKPOINTS.tablet);
}
