/**
 * Phase 11 — fullscreen mode (spec §25).
 *
 * Uses the real Fullscreen API on the chart panel element, so the browser's own
 * chrome gets out of the way and the panel keeps its state (nothing unmounts —
 * that is the whole point of fullscreening the *element* rather than routing to
 * a new view).
 *
 * When the API is unavailable or refuses (an iframe without `allowfullscreen`,
 * a browser policy, a permission prompt dismissed by the user) the hook falls
 * back to a maximised in-page mode so the button never becomes a no-op and never
 * throws into React's render path.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface FullscreenApi<T extends HTMLElement> {
  /** Attach to the element that should be able to go fullscreen. */
  ref: React.RefObject<T>;
  isFullscreen: boolean;
  /** `true` when the in-page fallback is active instead of the real API. */
  isFallback: boolean;
  toggle: () => void;
  exit: () => void;
  supported: boolean;
}

export function useFullscreen<T extends HTMLElement = HTMLDivElement>(): FullscreenApi<T> {
  const ref = useRef<T>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isFallback, setIsFallback] = useState(false);

  useEffect(() => {
    const onChange = () => {
      const node = ref.current;
      const active = node ? document.fullscreenElement === node : Boolean(document.fullscreenElement);
      setIsFullscreen(active);
      if (!active) setIsFallback(false);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  // Leaving the page (or the whole document) while maximised must not leave the
  // body locked behind the fallback overlay.
  useEffect(
    () => () => {
      document.body.classList.remove("chart-fs-fallback");
    },
    []
  );

  const enter = useCallback(() => {
    const node = ref.current;
    if (!node) return;
    const request = node.requestFullscreen?.bind(node);
    if (!request) {
      setIsFallback(true);
      setIsFullscreen(true);
      document.body.classList.add("chart-fs-fallback");
      return;
    }
    request({ navigationUI: "hide" }).catch(() => {
      // Refused (policy / iframe / user gesture lost): degrade to in-page mode.
      setIsFallback(true);
      setIsFullscreen(true);
      document.body.classList.add("chart-fs-fallback");
    });
  }, []);

  const exit = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen?.().catch(() => {
        /* nothing to recover — the change event will resync the flag */
      });
    }
    setIsFallback(false);
    setIsFullscreen(false);
    document.body.classList.remove("chart-fs-fallback");
  }, []);

  const toggle = useCallback(() => {
    if (isFullscreen) exit();
    else enter();
  }, [enter, exit, isFullscreen]);

  // Escape exits the fallback too — a maximised panel must never trap the user.
  useEffect(() => {
    if (!isFallback) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") exit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isFallback, exit]);

  return {
    ref,
    isFullscreen,
    isFallback,
    toggle,
    exit,
    supported: typeof document !== "undefined",
  };
}
