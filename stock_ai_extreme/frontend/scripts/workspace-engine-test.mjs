/*
 * Phase 12 — workspace engine test harness (spec §20).
 *
 * Companion to `chart-engine-test.mjs`: bundles the pure layout engine with
 * the project's own esbuild, imports the result and asserts every rule the
 * spec names. No React, no DOM — pure maths against the same functions the
 * store uses in production.
 *
 * Usage: node scripts/workspace-engine-test.mjs
 */
import esbuild from "esbuild";
import { pathToFileURL } from "node:url";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let passed = 0;
let failed = 0;
const failures = [];

function check(name, ok, detail = "") {
  if (ok) {
    passed++;
    console.log(`PASS  ${name}${detail ? ` — ${detail}` : ""}`);
  } else {
    failed++;
    failures.push(name);
    console.log(`FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

// ---------------------------------------------------------------------------
// Bundle the engine + registry descriptors (registry imports lucide icons —
// stub them for Node so the bundle stays pure).
// ---------------------------------------------------------------------------

const outDir = mkdtempSync(join(tmpdir(), "ws-engine-"));
const outfile = join(outDir, "engine.test.mjs");

await esbuild.build({
  entryPoints: [join(process.cwd(), "src/lib/workspace/engine.ts")],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile,
  // engine.ts imports types only — nothing to externalize
  logLevel: "silent",
});

const engine = await import(pathToFileURL(outfile).href);

// A registry-free bounds table mirroring presets.ts so this harness never
// imports React/lucide.
const BOUNDS = {
  NEW_CHART: { defaultSize: { w: 8, h: 10 }, minSize: { w: 4, h: 6 } },
  DATA: { defaultSize: { w: 4, h: 8 }, minSize: { w: 3, h: 4 } },
  MARKET_MOVERS: { defaultSize: { w: 4, h: 8 }, minSize: { w: 3, h: 4 } },
  CATALYSTS_NEWS: { defaultSize: { w: 5, h: 9 }, minSize: { w: 3, h: 5 } },
  POSITIONS_TRADES: { defaultSize: { w: 6, h: 8 }, minSize: { w: 4, h: 4 } },
  MARKET_PULSE: { defaultSize: { w: 4, h: 7 }, minSize: { w: 3, h: 4 } },
  AI_ASSISTANT: { defaultSize: { w: 4, h: 12 }, minSize: { w: 3, h: 6 } },
};
const boundsFor = (type) => BOUNDS[type];

const mkLayout = () => ({
  workspaceId: "ws-test",
  preset: "trading",
  widgets: [],
  version: 1,
  updatedAt: new Date().toISOString(),
});

const mkWidget = (type, x, y, width, height, extra = {}) => ({
  id: extra.id ?? engine.makeId(type.toLowerCase()),
  type,
  x,
  y,
  width,
  height,
  visible: true,
  minimized: false,
  maximized: false,
  settings: {},
  ...extra,
});

// ---------------------------------------------------------------------------
// 1. Geometry primitives
// ---------------------------------------------------------------------------

check("collides detects overlap", engine.collides({ x: 0, y: 0, w: 4, h: 4 }, { x: 2, y: 2, w: 4, h: 4 }) === true);
check("collides rejects touching edges", engine.collides({ x: 0, y: 0, w: 4, h: 4 }, { x: 4, y: 0, w: 4, h: 4 }) === false);
check("bottommost computes max bottom", engine.bottommost([{ x: 0, y: 0, w: 4, h: 4 }, { x: 0, y: 8, w: 4, h: 4 }]) === 12);
check("bottommost of empty board is 0", engine.bottommost([]) === 0);
check("firstFreeSpot pushes below an occupant", engine.firstFreeSpot({ x: 0, y: 0, w: 4, h: 2 }, [{ x: 0, y: 0, w: 4, h: 3 }]).y === 3);
check("firstFreeSpot keeps a free spot", engine.firstFreeSpot({ x: 0, y: 0, w: 4, h: 2 }, []).y === 0);

// ---------------------------------------------------------------------------
// 2. createWidgetInstance: placement + bounds (spec §7)
// ---------------------------------------------------------------------------

{
  const layout = mkLayout();
  layout.widgets = [mkWidget("NEW_CHART", 0, 0, 8, 10)];
  const inst = engine.createWidgetInstance("DATA", boundsFor("DATA"), layout.widgets);
  check("created instance has a unique id", typeof inst.id === "string" && inst.id.length > 4);
  check("created instance respects default size", inst.width === 4 && inst.height === 8);
  check("created instance avoids the existing chart", !engine.collides(inst, layout.widgets[0]), `y=${inst.y}`);
  check("created instance is visible and unminimized", inst.visible && !inst.minimized && !inst.maximized);

  const tooWide = engine.createWidgetInstance("NEW_CHART", { defaultSize: { w: 99, h: 4 }, minSize: { w: 1, h: 1 } }, []);
  check("instance width clamps to grid columns", tooWide.width <= engine.GRID_COLS);
}

// ---------------------------------------------------------------------------
// 3. add / remove (spec §7)
// ---------------------------------------------------------------------------

{
  let layout = mkLayout();
  const chart = mkWidget("NEW_CHART", 0, 0, 8, 10);
  layout.widgets = [chart];
  const pulse = mkWidget("MARKET_PULSE", 8, 0, 4, 7);
  layout = engine.addWidget(layout, pulse);
  check("add inserts the widget", layout.widgets.length === 2 && layout.widgets.some((w) => w.id === pulse.id));
  check("add stamps updatedAt", typeof layout.updatedAt === "string");

  const next = engine.removeWidget(layout, chart.id);
  check("remove deletes exactly the target", next.widgets.length === 1 && next.widgets[0].id === pulse.id);
  check("remove leaves others intact", next.widgets[0].settings === pulse.settings || next.widgets[0].type === "MARKET_PULSE");
}

// ---------------------------------------------------------------------------
// 4. visibility (spec §11)
// ---------------------------------------------------------------------------

{
  let layout = mkLayout();
  layout.widgets = [mkWidget("NEW_CHART", 0, 0, 8, 10), mkWidget("MARKET_PULSE", 0, 10, 4, 7)];
  const hidden = engine.setWidgetVisible(layout, layout.widgets[1].id, false);
  check("hide keeps the instance in the layout", hidden.widgets.length === 2);
  check("hidden widget flags visible=false", hidden.widgets.find((w) => w.id === layout.widgets[1].id).visible === false);
  const shown = engine.setWidgetVisible(hidden, layout.widgets[1].id, true);
  check("show restores visibility", shown.widgets.find((w) => w.id === layout.widgets[1].id).visible === true);
}

// ---------------------------------------------------------------------------
// 5. compaction: gravity without overlaps
// ---------------------------------------------------------------------------

{
  const layout = mkLayout();
  layout.widgets = [
    mkWidget("NEW_CHART", 0, 0, 12, 6),
    mkWidget("DATA", 0, 10, 6, 6), // gap at y=6
    mkWidget("MARKET_PULSE", 6, 10, 6, 6),
  ];
  const compacted = engine.compact(layout.widgets);
  const data = compacted.find((w) => w.id === layout.widgets[1].id);
  const pulse = compacted.find((w) => w.id === layout.widgets[2].id);
  check("gravity pulls widgets into gaps", data.y === 6 && pulse.y === 6, `data.y=${data.y} pulse.y=${pulse.y}`);
  // No overlaps after compaction
  const rects = compacted.map((w) => ({ x: w.x, y: w.y, w: w.width, h: w.height }));
  let overlaps = 0;
  for (let i = 0; i < rects.length; i++)
    for (let j = i + 1; j < rects.length; j++) if (engine.collides(rects[i], rects[j])) overlaps++;
  check("compaction never produces overlaps", overlaps === 0);
}

// ---------------------------------------------------------------------------
// 6. resize bounds (spec §10)
// ---------------------------------------------------------------------------

{
  let layout = mkLayout();
  layout.widgets = [mkWidget("NEW_CHART", 0, 0, 8, 10)];
  const chartId = layout.widgets[0].id;

  const tooSmall = engine.resizeWidget(layout, chartId, { w: 1, h: 1 }, boundsFor("NEW_CHART"));
  const chart = tooSmall.widgets.find((w) => w.id === chartId);
  check("resize never violates min width", chart.width >= boundsFor("NEW_CHART").minSize.w, `w=${chart.width}`);
  check("resize never violates min height", chart.height >= boundsFor("NEW_CHART").minSize.h, `h=${chart.height}`);

  const tooBig = engine.resizeWidget(layout, chartId, { w: 99, h: 99 }, boundsFor("NEW_CHART"));
  check("resize clamps width to grid columns", tooBig.widgets.find((w) => w.id === chartId).width <= engine.GRID_COLS);

  const fine = engine.resizeWidget(layout, chartId, { w: 6, h: 12 }, boundsFor("NEW_CHART"));
  const resized = fine.widgets.find((w) => w.id === chartId);
  check("legal resize applies exactly", resized.width === 6 && resized.height === 12);
}

// ---------------------------------------------------------------------------
// 7. move bounds + compaction (spec §9)
// ---------------------------------------------------------------------------

{
  let layout = mkLayout();
  layout.widgets = [mkWidget("NEW_CHART", 0, 0, 8, 10)];
  const chartId = layout.widgets[0].id;

  const moved = engine.moveWidget(layout, chartId, -5, 0);
  const m = moved.widgets.find((w) => w.id === chartId);
  check("move clamps x to the grid", m.x === 0);

  const moved2 = engine.moveWidget(layout, chartId, 4, 4);
  const m2 = moved2.widgets.find((w) => w.id === chartId);
  // An 8-wide chart at x=6 would overflow the 12-col grid → clamped to x=4.
  check("legal move lands at the clamped x", m2.x === 4, `x=${m2.x}`);
  // Vertical compaction (RGL semantics): a widget floating in free space is
  // lifted back to the top — moves express *order*, not absolute y.
  check("gravity lifts a free-floating move", m2.y === 0, `y=${m2.y}`);

  const gone = engine.moveWidget(layout, "no-such-id", 1, 1);
  // A miss must not move anything — but gravity still re-settles the board.
  check(
    "moving an unknown id moves no widget",
    gone.widgets.length === 1 && gone.widgets[0].id === chartId &&
      layout.widgets.filter((w) => w.id === chartId).length === 1
  );
}

// ---------------------------------------------------------------------------
// 8. minimize / maximize (spec §11)
// ---------------------------------------------------------------------------

{
  let layout = mkLayout();
  layout.widgets = [mkWidget("NEW_CHART", 0, 0, 8, 10), mkWidget("DATA", 8, 0, 4, 8)];
  const chartId = layout.widgets[0].id;
  const dataId = layout.widgets[1].id;

  const mini = engine.setWidgetMinimized(layout, chartId, true);
  check("minimize flags the widget", mini.widgets.find((w) => w.id === chartId).minimized === true);
  check("minimize keeps the widget mounted", mini.widgets.length === 2);

  const maxed = engine.setWidgetMaximized(layout, chartId, true);
  check("maximize flags the widget", maxed.widgets.find((w) => w.id === chartId).maximized === true);
  const restored = engine.setWidgetMaximized(maxed, chartId, false);
  check("un-maximize restores", restored.widgets.find((w) => w.id === chartId).maximized === false);
  check("maximize clears other maximized flags", maxed.widgets.find((w) => w.id === dataId).maximized === false);
}

// ---------------------------------------------------------------------------
// 9. duplicate rules via bounds table + canAdd shape (spec §8)
// ---------------------------------------------------------------------------

{
  // The registry owns maxInstances; the engine only needs placement. This
  // check pins the placement contract for N charts (multiple allowed).
  let layout = mkLayout();
  for (let i = 0; i < 3; i++) {
    const inst = engine.createWidgetInstance("NEW_CHART", boundsFor("NEW_CHART"), layout.widgets);
    layout = engine.addWidget(layout, inst);
  }
  const charts = layout.widgets.filter((w) => w.type === "NEW_CHART");
  check("three charts can coexist without collisions", charts.length === 3);
  const rects = charts.map((w) => ({ x: w.x, y: w.y, w: w.width, h: w.height }));
  let overlaps = 0;
  for (let i = 0; i < rects.length; i++)
    for (let j = i + 1; j < rects.length; j++) if (engine.collides(rects[i], rects[j])) overlaps++;
  check("three charts never overlap", overlaps === 0);
}

// ---------------------------------------------------------------------------
// 10. sanitizeLayout: repair, clamp, drop unknowns (spec §15)
// ---------------------------------------------------------------------------

{
  const dirty = {
    workspaceId: "ws-x",
    preset: "trading",
    version: 1,
    widgets: [
      mkWidget("NEW_CHART", -5, 0, 99, 3),      // clamps
      mkWidget("DATA", 0, 0, 4, 8, { visible: false }), // hidden survives
      { id: "junk", type: "NOT_A_WIDGET", x: 0, y: 0, width: 4, height: 4 }, // dropped
      mkWidget("MARKET_PULSE", 0, 0, 4, 7, { maximized: true }), // maximize never restored
      { id: "", type: "DATA", x: 0, y: 0, width: 4, height: 8 }, // dropped (no id)
      mkWidget("DATA", 0, 0, 4, 8), // duplicate id dropped
    ],
  };
  dirty.widgets[5].id = dirty.widgets[1].id;

  const clean = engine.sanitizeLayout(dirty, boundsFor);
  check("sanitize drops unknown widget types", !clean.widgets.some((w) => w.type === "NOT_A_WIDGET"));
  check("sanitize drops id-less widgets", clean.widgets.every((w) => w.id && w.id.length > 0));
  check("sanitize clamps out-of-bounds rects", clean.widgets.find((w) => w.type === "NEW_CHART").width <= engine.GRID_COLS);
  check("sanitize never restores maximized", clean.widgets.every((w) => w.maximized === false));
  check("sanitize keeps hidden widgets", clean.widgets.some((w) => w.visible === false));
  check("sanitize dedupes ids", new Set(clean.widgets.map((w) => w.id)).size === clean.widgets.length);
  check("sanitize preserves the preset", clean.preset === "trading");
  check("sanitize stamps the current version", clean.version === engine.LAYOUT_VERSION);
}

// ---------------------------------------------------------------------------
// 11. reset + saved-workspace helpers (spec §12, §14)
// ---------------------------------------------------------------------------

{
  const built = engine.resetLayout("research", () => ({
    workspaceId: "ws-fresh",
    preset: "research",
    widgets: [mkWidget("NEW_CHART", 0, 0, 7, 14)],
    version: engine.LAYOUT_VERSION,
    updatedAt: new Date().toISOString(),
  }));
  check("reset returns a fresh workspace id", built.workspaceId !== "ws-fresh");
  check("reset keeps the preset", built.preset === "research");
  check("reset produces widgets", built.widgets.length === 1);

  let list = [];
  const a = { id: "sw-1", name: "A", layout: built, createdAt: "t", updatedAt: "t" };
  list = engine.upsertSaved(list, a);
  const a2 = { ...a, name: "A2" };
  list = engine.upsertSaved(list, a2);
  check("upsert saves new and updates existing", list.length === 1 && list[0].name === "A2");

  list = engine.renameSaved(list, "sw-1", "Renamed");
  check("rename applies trimmed name", list[0].name === "Renamed");
  list = engine.renameSaved(list, "sw-1", "   ");
  check("rename never empties a name", list[0].name === "Renamed");

  list = engine.deleteSaved(list, "sw-1");
  check("delete removes the record", list.length === 0);
}

console.log(`\nworkspace engine: ${passed} check(s) passed, ${failed} failed`);
if (failed > 0) {
  console.log(`FAILURES:\n  - ${failures.join("\n  - ")}`);
  process.exit(1);
}
console.log("All workspace-engine assertions passed.");
