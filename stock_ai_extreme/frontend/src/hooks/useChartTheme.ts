/**
 * Phase 11 — chart theming.
 *
 * Plotly needs concrete colours, but this terminal themes with CSS variables and
 * a `data-theme` attribute on `<html>`. Rather than hard-coding a dark palette
 * (which would leave the chart unreadable in light mode), the chart reads the
 * live design tokens and re-reads them whenever the theme attribute changes.
 *
 * The returned object is memoized on the theme name, so it is a stable prop for
 * the memoized Plotly surface.
 */
import { useEffect, useMemo, useState } from "react";
import { FALLBACK_THEME, type ChartTheme } from "../lib/charting/plotModel";

/** Pure mapping from resolved CSS values to the chart palette. */
export function themeFromTokens(tokens: Record<string, string>): ChartTheme {
  const token = (name: string, fallback: string) => {
    const value = tokens[name];
    return value && value.trim() ? value.trim() : fallback;
  };
  const blue = token("--blue", FALLBACK_THEME.line);
  const border = token("--border", "rgba(120,140,180,.22)");
  return {
    text: token("--text", FALLBACK_THEME.text),
    textDim: token("--text2", FALLBACK_THEME.textDim),
    grid: token("--chart-grid", border),
    spike: token("--border2", FALLBACK_THEME.spike),
    // Plotly renders tooltips in its own layer, so it needs opaque colours:
    // `--surface` / `--canvas` are exactly the right pairing.
    tooltipBg: token("--raised", FALLBACK_THEME.tooltipBg),
    tooltipBorder: token("--border2", FALLBACK_THEME.tooltipBorder),
    tooltipText: token("--text", FALLBACK_THEME.tooltipText),
    up: token("--green", FALLBACK_THEME.up),
    down: token("--red", FALLBACK_THEME.down),
    volume: token("--chart-volume", "rgba(94,159,232,.42)"),
    line: blue,
    accent: token("--accent", blue),
  };
}

function readTokens(): Record<string, string> {
  if (typeof window === "undefined" || typeof document === "undefined") return {};
  const styles = getComputedStyle(document.documentElement);
  const names = [
    "--text",
    "--text2",
    "--border",
    "--border2",
    "--surface",
    "--canvas",
    "--raised",
    "--green",
    "--red",
    "--blue",
    "--accent",
    "--chart-grid",
    "--chart-volume",
  ];
  const out: Record<string, string> = {};
  for (const name of names) out[name] = styles.getPropertyValue(name);
  return out;
}

export function useChartTheme(): ChartTheme {
  const [themeName, setThemeName] = useState<string>(() =>
    typeof document === "undefined" ? "dark" : document.documentElement.getAttribute("data-theme") || "dark"
  );
  const [tokens, setTokens] = useState<Record<string, string>>(() => readTokens());

  useEffect(() => {
    if (typeof document === "undefined" || typeof MutationObserver === "undefined") return;
    const observer = new MutationObserver(() => {
      setThemeName(document.documentElement.getAttribute("data-theme") || "dark");
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  // Tokens are re-read after the attribute change so the new theme's variables
  // are already applied (Layout sets the attribute in an effect).
  useEffect(() => {
    setTokens(readTokens());
  }, [themeName]);

  return useMemo(() => themeFromTokens(tokens), [tokens]);
}
