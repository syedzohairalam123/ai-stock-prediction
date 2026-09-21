/**
 * Phase 11 — dynamic N-panel grid.
 *
 * Checks the pure id/label helpers plus the store's panel lifecycle, which is
 * what the workspace bar drives: add a panel, close one, and never leave the
 * workspace in an impossible state (no panels, a stale active id, a grid with
 * an empty column).
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
    external: ["axios"],
    define: { "import.meta.env": "{}" },
  });
  return import(`file://${outfile}`);
}

// The store persists through `window.localStorage`; node has neither.
globalThis.window = globalThis;
globalThis.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {},
  key: () => null,
  length: 0,
};

const defaults = await bundle("src/lib/charting/defaults.ts", "chart-defaults.mjs");
const store = await bundle("src/store/useChartStore.ts", "chart-store-grid.mjs");
const { useChartStore } = store;

let passed = 0;
const assert = (label, condition) => {
  if (!condition) throw new Error(`FAIL: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
};

const ids = () => useChartStore.getState().charts.map((c) => c.id);

// `resetWorkspace` rebuilds the two seed panels, which `filter`-based state
// surgery cannot do once a seed panel has actually been closed.
function reset() {
  useChartStore.getState().resetWorkspace();
  useChartStore.setState({ gridColumns: 2 });
}

// --- labels ----------------------------------------------------------------

assert("chart-a is labelled", defaults.chartLabel("chart-a") === "Chart A");
assert("chart-b is labelled", defaults.chartLabel("chart-b") === "Chart B");
assert("a grid panel letter becomes a name", defaults.chartLabel("chart-c") === "Chart C");
assert("an unknown widget id passes through", defaults.chartLabel("chart-widget-9") === "chart-widget-9");

// --- id allocation ---------------------------------------------------------

assert("the first free panel is chart-c", defaults.nextPanelId([{ id: "chart-a" }, { id: "chart-b" }]) === "chart-c");
assert("ids fill gaps", defaults.nextPanelId([{ id: "chart-a" }, { id: "chart-b" }, { id: "chart-c" }]) === "chart-d");
assert(
  "a closed panel's id is reused, never aliased",
  defaults.nextPanelId([{ id: "chart-a" }, { id: "chart-b" }, { id: "chart-d" }]) === "chart-c"
);
assert(
  "the cap returns null",
  defaults.nextPanelId(["a", "b", "c", "d", "e", "f"].map((l) => ({ id: `chart-${l}` }))) === null
);

// --- store lifecycle -------------------------------------------------------

reset();
assert("the workspace starts on the two seed panels", ids().join(",") === "chart-a,chart-b");

const c = useChartStore.getState().addChart();
assert("addChart returns the new id", c === "chart-c");
assert("addChart appends the panel", ids().join(",") === "chart-a,chart-b,chart-c");
assert("a new panel starts on a real symbol", useChartStore.getState().charts[2].symbol.length > 0);

const d = useChartStore.getState().addChart("LUCK", "1Y");
assert("a second add continues the alphabet", d === "chart-d");
assert("addChart honours an explicit symbol", useChartStore.getState().charts[3].symbol === "LUCK");
assert("addChart honours an explicit timeframe", useChartStore.getState().charts[3].timeframe === "1Y");

// Closing the active neighbour must re-home `activeId`.
useChartStore.getState().setActiveChart("chart-c");
useChartStore.getState().removeChart("chart-c");
assert("removeChart drops the panel", ids().join(",") === "chart-a,chart-b,chart-d");
assert("removeChart re-homes the active panel", useChartStore.getState().activeId === "chart-d");
assert("the freed id is reusable", useChartStore.getState().addChart() === "chart-c");

// Removing the last panel exits the multi-panel layout.
reset();
useChartStore.setState({ layout: "grid" });
useChartStore.getState().addChart();
useChartStore.getState().setActiveChart("chart-a");
useChartStore.getState().removeChart("chart-c");
assert("removing back to two panels keeps the layout", ids().length === 2 && useChartStore.getState().layout === "grid");
useChartStore.getState().removeChart("chart-b");
assert("removing down to one panel exits grid", ids().join(",") === "chart-a" && useChartStore.getState().layout === "single");
assert("the last panel cannot be removed", (() => {
  useChartStore.getState().removeChart("chart-a");
  return ids().join(",") === "chart-a";
})());

// --- column clamping -------------------------------------------------------

useChartStore.getState().setGridColumns(3);
assert("columns accept 3", useChartStore.getState().gridColumns === 3);
useChartStore.getState().setGridColumns(9);
assert("columns clamp above", useChartStore.getState().gridColumns === 3);
useChartStore.getState().setGridColumns(1);
assert("columns accept 1", useChartStore.getState().gridColumns === 1);
useChartStore.getState().setGridColumns(2.7);
assert("columns floor to an integer", useChartStore.getState().gridColumns === 2);

// --- link group survives panel churn --------------------------------------

reset();
const c2 = useChartStore.getState().addChart();
useChartStore.getState().setPanelLink(c2, false);
assert("a new panel can leave the link group", store.isPanelLinked(useChartStore.getState(), c2) === false);
useChartStore.getState().removeChart(c2);
assert(
  "closing a panel clears its link flag",
  Object.prototype.hasOwnProperty.call(useChartStore.getState().panelLinked, c2) === false
);

// --- drag reorder ----------------------------------------------------------

reset();
useChartStore.getState().addChart();
assert("baseline before reordering", ids().join(",") === "chart-a,chart-b,chart-c");

useChartStore.getState().moveChart("chart-a", "chart-c", "after");
assert("moving the first panel to the end", ids().join(",") === "chart-b,chart-c,chart-a");

useChartStore.getState().moveChart("chart-a", "chart-b", "before");
assert("moving the last panel to the front", ids().join(",") === "chart-a,chart-b,chart-c");

useChartStore.getState().moveChart("chart-a", "chart-b", "after");
assert("moving one slot later", ids().join(",") === "chart-b,chart-a,chart-c");

useChartStore.getState().moveChart("chart-c", "chart-a");
assert("the default position is before", ids().join(",") === "chart-b,chart-c,chart-a");

useChartStore.getState().moveChart("chart-b", "chart-b", "after");
assert("dropping a panel on itself is a no-op", ids().join(",") === "chart-b,chart-c,chart-a");

useChartStore.getState().moveChart("chart-z", "chart-a", "before");
assert("an unknown source is a no-op", ids().join(",") === "chart-b,chart-c,chart-a");

useChartStore.getState().moveChart("chart-b", "chart-z", "after");
assert("an unknown target is a no-op", ids().join(",") === "chart-b,chart-c,chart-a");

useChartStore.getState().moveChart("chart-a", "chart-b", "after");
assert("reordering is a permutation, not a rebuild", ids().join(",") === "chart-b,chart-a,chart-c");
assert("reordering keeps every panel instance intact", useChartStore.getState().charts.every((c) => c.symbol.length > 0));

console.log(`chart-grid: ${passed} checks passed`);
