/**
 * Phase 11 — cross-panel linking semantics.
 *
 * The store is the single source of truth for the link group, so these checks
 * bundle it directly (no DOM) and drive it with `setState`, asserting only the
 * observable rule: a linked property broadcasts between the panels that joined
 * the group, and nowhere else.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const __dirname = fileURLToPath(new URL("..", import.meta.url));
const outDir = join(__dirname, "node_modules", ".cache", "neural-market-tests");
mkdirSync(outDir, { recursive: true });

async function bundle(relativePath, outName) {
  const outfile = join(outDir, outName);
  await build({
    entryPoints: [join(__dirname, relativePath)],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile,
    logLevel: "silent",
    // The store's symbol inference reaches the market services, which pull axios.
    // It is irrelevant to linked-panel semantics, so let node resolve it at
    // runtime instead of bundling its CommonJS dependency tree into ESM.
    external: ["axios"],
    // Vite injects `import.meta.env` at build time; the test runner is a plain
    // node process, so stand in an empty env (axios is external, so no request
    // is ever made from these semantics).
    define: { "import.meta.env": "{}" },
  });
  return import(`file://${outfile}`);
}

// The store persists through `window.localStorage`; node has neither, and
// zustand would warn on every write. A trivial in-memory shim keeps the run
// quiet without changing any of the semantics under test.
globalThis.window = globalThis;
globalThis.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
  key: () => null,
  length: 0,
};

const store = await bundle("src/store/useChartStore.ts", "chart-store.mjs");
const { useChartStore, isPanelLinked } = store;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

const chart = (id) => useChartStore.getState().charts.find((c) => c.id === id);

/** Restore a known baseline before each check. */
function reset({ linkEnabled = false, linkGroup = { symbol: true, timeframe: true, crosshair: true }, panelLinked = {} } = {}) {
  useChartStore.setState((s) => ({
    charts: s.charts.map((c) => ({ ...c, symbol: c.id === "chart-a" ? "OGDC" : "KSE100", timeframe: "6M", crosshairEnabled: true })),
    linkEnabled,
    linkGroup,
    panelLinked,
  }));
}

// --- link off (the default) ------------------------------------------------

reset();
useChartStore.getState().setSymbol("chart-a", "LUCK");
assert("link off: the edited panel changes", chart("chart-a").symbol === "LUCK");
assert("link off: the other panel is untouched", chart("chart-b").symbol === "KSE100");

// --- link on, both panels in the group -------------------------------------

reset({ linkEnabled: true });
useChartStore.getState().setSymbol("chart-a", "MCB");
assert("link on: the edited panel changes", chart("chart-a").symbol === "MCB");
assert("link on: the linked panel follows", chart("chart-b").symbol === "MCB");

useChartStore.getState().setTimeframe("chart-b", "1Y");
assert("link on: timeframe follows from the other direction", chart("chart-a").timeframe === "1Y");

useChartStore.getState().setCrosshairEnabled("chart-a", false);
assert("link on: crosshair follows", chart("chart-b").crosshairEnabled === false);

// --- per-panel opt-out -----------------------------------------------------

reset({ linkEnabled: true, panelLinked: { "chart-b": false } });
assert("opt-out panel reads as independent", isPanelLinked(useChartStore.getState(), "chart-b") === false);
useChartStore.getState().setSymbol("chart-a", "ENGRO");
assert("opt-out: the linked panel still changes", chart("chart-a").symbol === "ENGRO");
assert("opt-out: the independent panel does not follow", chart("chart-b").symbol === "KSE100");

// Editing the independent panel must not broadcast either.
useChartStore.getState().setSymbol("chart-b", "PSO");
assert("opt-out: the independent panel can still be edited locally", chart("chart-b").symbol === "PSO");
assert("opt-out: its edit does not leak into the group", chart("chart-a").symbol === "ENGRO");

// Re-joining restores propagation.
useChartStore.getState().togglePanelLink("chart-b");
assert("toggle: rejoining flips membership back", isPanelLinked(useChartStore.getState(), "chart-b") === true);
useChartStore.getState().setSymbol("chart-a", "HUBC");
assert("toggle: a rejoined panel follows again", chart("chart-b").symbol === "HUBC");

// --- per-property switches -------------------------------------------------

reset({ linkEnabled: true, linkGroup: { symbol: false, timeframe: true, crosshair: false } });
useChartStore.getState().setSymbol("chart-a", "FFC");
assert("property off: symbol does not broadcast", chart("chart-b").symbol === "KSE100");
useChartStore.getState().setCrosshairEnabled("chart-a", false);
assert("property off: crosshair does not broadcast", chart("chart-b").crosshairEnabled === true);
useChartStore.getState().setTimeframe("chart-a", "1M");
assert("property on: timeframe still broadcasts", chart("chart-b").timeframe === "1M");

// --- membership reads default-in -------------------------------------------

reset({ linkEnabled: true });
assert(
  "a panel with no stored flag is linked by default",
  isPanelLinked({ panelLinked: {} }, "chart-b") === true
);
assert(
  "only an explicit false excludes a panel",
  isPanelLinked({ panelLinked: { "chart-b": false } }, "chart-b") === false
);

// --- a linked change reaches every member panel ---------------------------

reset({ linkEnabled: true });
useChartStore.getState().setTimeframe("chart-a", "5Y");
assert("link on: a new timeframe lands on the whole group", chart("chart-b").timeframe === "5Y");

console.log(`chart-link: ${passed} checks passed`);
