/*
 * Chart workspace audit (Phase 11, spec §30).
 *
 * Companion to `page-audit.mjs` and `assistant-audit.mjs`: those check that
 * every route renders and that the assistant behaves; this one drives the
 * charting workspace like a trader would — splitting the view, switching chart
 * styles, toggling every indicator, drawing all five primitives, placing and
 * dragging price levels, undoing, fullscreening and going mobile.
 *
 * It talks to an already-running Chrome over the DevTools Protocol using Node's
 * built-in WebSocket (no dependencies, never part of the app bundle) and uses
 * *input* events — not synthetic DOM events — so pointer capture, hover state
 * and fullscreen behave exactly as they do for a real user.
 *
 * Usage
 *   # 1. dev server on :5173 (a backend on :8000 is optional — the chart falls
 *   #    back to the Phase-5 sample history when the API is down, and that path
 *   #    is worth auditing too)
 *   # 2. chrome --remote-debugging-port=9222 --headless=new http://localhost:5173
 *   # 3. node scripts/chart-audit.mjs
 *
 * Env
 *   AUDIT_BASE  frontend base URL   (default http://localhost:5173)
 *   AUDIT_CDP   devtools endpoint   (default http://127.0.0.1:9222)
 *   SHOT_DIR    screenshot folder   (default system temp dir)
 *
 * Exit code 1 means at least one check failed.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CDP = process.env.AUDIT_CDP || "http://127.0.0.1:9222";
const BASE = process.env.AUDIT_BASE || "http://localhost:5173";
const SHOTS = process.env.SHOT_DIR || path.join(os.tmpdir(), "chart-audit");
const ROUTE = "/charts";

fs.mkdirSync(SHOTS, { recursive: true });

const runStart = Date.now() / 1000;
const results = [];
const consoleErrors = [];
const consoleWarnings = [];
const exceptions = [];
const failedRequests = [];
const inFlight = new Map();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const note = (message) => console.log(`      ${message}`);
const check = (name, ok, detail = "") => {
  results.push({ name, ok: Boolean(ok), detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
};

// ------------------------------------------------------------------ CDP setup

const targets = await (await fetch(`${CDP}/json/list`)).json();
const target = targets.find((t) => t.type === "page");
if (!target) throw new Error("no debuggable page target — is Chrome running with --remote-debugging-port=9222?");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});

let nextId = 0;
const pending = new Map();

socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
    return;
  }
  const { method, params } = message;
  if (method === "Runtime.consoleAPICalled") {
    const line = (params.args || []).map((arg) => arg.value ?? arg.description ?? arg.type).join(" ");
    if (params.type === "warning") consoleWarnings.push(line);
    else if (params.type === "error" || params.type === "assert") consoleErrors.push(line);
  } else if (method === "Runtime.exceptionThrown") {
    exceptions.push(params.exceptionDetails.exception?.description || params.exceptionDetails.text);
  } else if (method === "Log.entryAdded" && params.entry.level === "error") {
    if ((params.entry.timestamp || 0) < runStart - 1) return;
    if (/favicon/i.test(params.entry.text || "")) return;
    consoleErrors.push(`[log] ${params.entry.text} ${params.entry.url || ""}`);
  } else if (method === "Network.requestWillBeSent") {
    inFlight.set(params.requestId, params.request?.url || "");
  } else if (method === "Network.loadingFailed") {
    const url = inFlight.get(params.requestId) || "";
    inFlight.delete(params.requestId);
    if (!/ERR_ABORTED/.test(params.errorText || "")) failedRequests.push(`${params.errorText} ${url}`);
  }
};

const send = (method, params = {}) => {
  const id = ++nextId;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    socket.send(JSON.stringify({ id, method, params }));
  });
};

async function evaluate(expression) {
  const reply = await send("Runtime.evaluate", {
    expression: `(() => { ${expression} })()`,
    returnByValue: true,
    awaitPromise: true,
  });
  const { result, exceptionDetails } = reply.result || {};
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || "evaluate failed");
  return result?.value;
}

async function waitFor(expression, timeoutMs = 15000, label = "") {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(`return Boolean(${expression});`)) return true;
    await sleep(150);
  }
  note(`timed out waiting for: ${label || expression}`);
  return false;
}

async function shot(name) {
  const reply = await send("Page.captureScreenshot", { format: "png" });
  if (reply.result?.data) fs.writeFileSync(path.join(SHOTS, `${name}.png`), Buffer.from(reply.result.data, "base64"));
}

// --------------------------------------------------------------- page helpers

/** Run a snippet inside panel `index`, with `panel` bound to that element. */
const inPanel = (index, body) =>
  evaluate(`
    const panel = document.querySelectorAll('.chart-panel')[${index}];
    if (!panel) return null;
    ${body}
  `);

/** Click an element inside a panel (programmatic click is enough for React). */
const clickIn = (index, selector) =>
  inPanel(index, `
    const el = panel.querySelector(${JSON.stringify(selector)});
    if (!el) return false;
    el.click();
    return true;
  `);

/** Click by accessible name inside a panel. */
const clickLabel = (index, label) =>
  inPanel(index, `
    const el = [...panel.querySelectorAll('button')].find((b) => (b.getAttribute('aria-label') || '').trim() === ${JSON.stringify(label)});
    if (!el) return false;
    el.click();
    return true;
  `);

const plotRect = (index) =>
  inPanel(index, `
    const plot = panel.querySelector('.chart-surface-plot');
    if (!plot) return null;
    const r = plot.getBoundingClientRect();
    return { left: r.left, top: r.top, width: r.width, height: r.height };
  `);

const countIn = (index, selector) =>
  inPanel(index, `return panel.querySelectorAll(${JSON.stringify(selector)}).length;`);

const textIn = (index, selector) =>
  inPanel(index, `
    const el = panel.querySelector(${JSON.stringify(selector)});
    return el ? el.textContent.trim() : null;
  `);

// ---------------------------------------------------- real mouse (CDP input)

/*
 * Popover helpers.
 *
 * A trigger click and the item click are deliberately separate round-trips: the
 * popover's contents do not exist in the DOM until React has re-rendered, and
 * combining both into one `evaluate` is exactly the race that makes a menu test
 * flaky.
 */
async function openMenu(ariaLabel) {
  // Always start from a closed state so `openMenu` can never toggle a menu shut.
  await closeMenus();
  await clickIn(0, `.chart-dd button[aria-label="${ariaLabel}"]`);
  return waitFor(`document.querySelector('.chart-pop')`, 6000, `menu "${ariaLabel}"`);
}

/** Click the first popover control whose text matches `pattern` (case-insensitive). */
async function clickPopControl(pattern) {
  const found = await waitFor(
    `[...document.querySelectorAll('.chart-pop button')].some((b) => new RegExp(${JSON.stringify(pattern)}, 'i').test(b.textContent || b.getAttribute('aria-label') || ''))`,
    6000,
    `popover control /${pattern}/i`
  );
  if (!found) return false;
  return evaluate(`
    const control = [...document.querySelectorAll('.chart-pop button')].find((b) =>
      new RegExp(${JSON.stringify(pattern)}, 'i').test(b.textContent || b.getAttribute('aria-label') || ''));
    if (!control) return false;
    control.click();
    return true;
  `);
}

/** Click a row control inside the currently open panel, scoped by its text. */
async function clickInRow(rowPattern, selector) {
  return evaluate(`
    const row = [...document.querySelectorAll('.chart-pop .chart-ind-row, .chart-pop .chart-level-row')].find((r) =>
      new RegExp(${JSON.stringify(rowPattern)}, 'i').test(r.textContent || ''));
    if (!row) return false;
    const target = row.querySelector(${JSON.stringify(selector)});
    if (!target) return false;
    target.click();
    return true;
  `);
}

/** The popovers close on an outside *pointerdown* — a plain click will not do. */
async function closeMenus() {
  await evaluate(`
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    return true;
  `);
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(200);
}

async function clickAt(x, y) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, buttons: 0 });
  await sleep(40);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1 });
  await sleep(30);
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1 });
  await sleep(90);
}

/** Two clicks: the first anchor, a preview move, then the second anchor. */
async function clickTwice(x1, y1, x2, y2) {
  await clickAt(x1, y1);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x2, y: y2, buttons: 0 });
  await sleep(60);
  await clickAt(x2, y2);
}

async function dragFromTo(x1, y1, x2, y2) {
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x1, y: y1, buttons: 0 });
  await sleep(40);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: x1, y: y1, button: "left", buttons: 1, clickCount: 1 });
  const steps = 6;
  for (let i = 1; i <= steps; i++) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: x1 + ((x2 - x1) * i) / steps,
      y: y1 + ((y2 - y1) * i) / steps,
      button: "left",
      buttons: 1,
    });
    await sleep(25);
  }
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x2, y: y2, button: "left", buttons: 0, clickCount: 1 });
  await sleep(120);
}

/** Pick a symbol through the panel's combobox. */
async function setSymbol(index, symbol) {
  await inPanel(index, `
    const input = panel.querySelector('.chart-symbol-box input');
    if (!input) return false;
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, ${JSON.stringify(symbol)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  await sleep(250);
  await inPanel(index, `
    const input = panel.querySelector('.chart-symbol-box input');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    return true;
  `);
  await sleep(700);
}

// -------------------------------------------------------------------- run-time

await send("Runtime.enable");
await send("Page.enable");
await send("Log.enable");
await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });

// Always start from a first-time visitor so persisted drawings from an earlier
// run cannot make a check pass on its own.
await send("Storage.clearDataForOrigin", { origin: new URL(BASE).origin, storageTypes: "local_storage" });
await send("Page.navigate", { url: `${BASE}${ROUTE}` });
await sleep(1500);

// ------------------------------------------------------------ 1. one chart

check("workspace route mounts", await waitFor(`document.querySelector('.chart-workspace')`, 45000, "workspace"));
check("workspace toolbar offers a layout switch", await evaluate(`return Boolean(document.querySelector('.chart-layout-switch'));`));
check(
  "workspace explains that panels are independent",
  await evaluate(`return /own symbol|independent/i.test(document.querySelector('.chart-workspace-meta')?.getAttribute('title') || '');`),
  await evaluate(`return document.querySelector('.chart-workspace-meta')?.getAttribute('title') || 'no title';`)
);

check("a single chart panel renders by default", (await countIn(0, ".chart-panel")) || (await evaluate(`return document.querySelectorAll('.chart-panel').length;`)) === 1);
check("chart data loads (candles are on screen)", await waitFor(`document.querySelectorAll('.js-plotly-plot .cartesianlayer').length >= 1`, 30000, "plotly layer"));
check("the OHLCV readout reports a real bar", await waitFor(`/bar \\d+\\/\\d+/.test(document.querySelector('.chart-hud-count')?.textContent || '')`, 15000, "HUD count"));
check(
  "indicator legend shows SMA 20 and SMA 50 with values",
  await evaluate(`
    const rows = [...document.querySelectorAll('.chart-hud-legend-row')].map((r) => r.textContent.trim());
    return rows.length >= 2 && rows.some((r) => /SMA 20/.test(r)) && rows.some((r) => /SMA 50/.test(r)) && rows.every((r) => /[\\d,]{4,}|insufficient/.test(r));
  `)
);
check(
  "the toolbar exposes every control the spec asks for",
  await evaluate(`
    const labels = [...document.querySelectorAll('.chart-toolbar button')].map((b) => b.getAttribute('aria-label') || b.textContent || '');
    const has = (re) => labels.some((l) => re.test(l));
    return has(/Chart style/i) && has(/Timeframe/i) === false && has(/Indicators/i) && has(/Price level tools/i) && has(/fullscreen/i) && has(/Chart settings/i) && has(/Undo/i) && has(/Redo/i);
  `)
);
check("timeframe buttons cover 1D→5Y", (await evaluate(`return document.querySelectorAll('.chart-panel .chart-tf button').length;`)) === 7);
check(
  "the time axis is labelled with dates, not epoch numbers",
  await evaluate(`
    const labels = [...document.querySelectorAll('.js-plotly-plot .xtick text, .js-plotly-plot .xtick tspan')].map((t) => t.textContent.trim());
    return labels.length > 0 && labels.every((l) => !/^\d{10,}$/.test(l)) && labels.some((l) => /[A-Za-z]/.test(l));
  `),
  (await evaluate(`return [...document.querySelectorAll('.js-plotly-plot .xtick text, .js-plotly-plot .xtick tspan')].map((t) => t.textContent).slice(0, 3).join(' | ');`))
);
check(
  "a fresh chart has no undo history to replay",
  await inPanel(0, `
    return panel.querySelector('button[aria-label="Undo annotation change"]').disabled &&
           panel.querySelector('button[aria-label="Redo annotation change"]').disabled;
  `)
);
await shot("01-single-chart");

// ------------------------------------------------------- 2. chart styles

{
  const beforeCandle = await evaluate(`return document.querySelectorAll('.js-plotly-plot .boxlayer, .js-plotly-plot .candlesticklayer').length;`);
  check("chart style menu opens", await openMenu("Chart style"));
  const styleItems = await evaluate(`return [...document.querySelectorAll('.chart-pop-item-label')].map((n) => n.textContent.trim());`);
  check(
    "style menu lists Candlestick, Volume Candles and Line",
    styleItems.length === 3 && /Candlestick/.test(styleItems[0]) && /Volume/.test(styleItems[1]) && /Line/.test(styleItems[2]),
    styleItems.join(" | ")
  );
  await clickPopControl("^LineClosing");
  await sleep(900);
  const afterLine = await evaluate(`return document.querySelectorAll('.js-plotly-plot .scatterlayer .trace').length;`);
  check("switching to Line re-renders the price series", afterLine >= 1, `${beforeCandle} candle layer(s) → ${afterLine} line trace(s)`);

  // Switching style must not wipe annotations (spec §5) — verified later once a
  // drawing exists; here we confirm the indicator legend survived the switch.
  check(
    "chart-style switch preserves indicator state",
    await evaluate(`return /SMA 20/.test(document.querySelector('.chart-hud-legend')?.textContent || '');`)
  );
  check("chart style menu reopens", await openMenu("Chart style"));
  await clickPopControl("^Candlestick");
  await sleep(800);
  check(
    "switching back to Candlestick restores the candles",
    (await evaluate(`return document.querySelectorAll('.js-plotly-plot .boxlayer, .js-plotly-plot .candlesticklayer').length;`)) >= 1
  );
}

// ---------------------------------------------------------- 3. indicators

{
  const legendBefore = await evaluate(`return document.querySelectorAll('.chart-hud-legend-row').length;`);
  check("indicators panel opens with the full catalog", (await openMenu("Indicators")) && (await waitFor(`document.querySelector('.chart-ind-list')`, 4000, "indicator list")));
  const rows = await evaluate(`return [...document.querySelectorAll('.chart-ind-name')].map((n) => n.textContent.trim());`);
  check(
    "catalog lists SMA 20, SMA 50, EMA 20, VWAP, Bollinger Bands",
    rows.join(",") === "SMA 20,SMA 50,EMA 20,VWAP,BB 20 / 2",
    rows.join(" | ")
  );
  const checked = await evaluate(`return [...document.querySelectorAll('.chart-ind-row')].map((r) => r.querySelector('input[type=checkbox]').checked);`);
  check("defaults match the spec: SMA 20 / SMA 50 on, the rest off", JSON.stringify(checked) === JSON.stringify([true, true, false, false, false]), JSON.stringify(checked));

  // EMA 20
  await clickInRow("EMA 20", "input[type=checkbox]");
  await sleep(600);
  check(
    "toggling EMA 20 updates the chart immediately",
    (await evaluate(`return document.querySelectorAll('.chart-hud-legend-row').length;`)) === legendBefore + 1 &&
      (await evaluate(`return /EMA 20/.test(document.querySelector('.chart-hud-legend').textContent);`))
  );

  // Bollinger Bands — three plot traces
  const tracesBefore = await evaluate(`return document.querySelectorAll('.js-plotly-plot .scatterlayer .trace').length;`);
  await clickInRow("BB 20", "input[type=checkbox]");
  await sleep(900);
  const tracesAfter = await evaluate(`return document.querySelectorAll('.js-plotly-plot .scatterlayer .trace').length;`);
  check("Bollinger Bands add three plot traces", tracesAfter - tracesBefore === 3, `${tracesBefore} → ${tracesAfter}`);

  // VWAP on daily bars must say why it cannot be drawn
  await clickInRow("VWAP", "input[type=checkbox]");
  await sleep(600);
  check(
    "VWAP on a daily dataset reports the honest reason",
    await evaluate(`return /VWAP unavailable for this dataset/.test(document.querySelector('.chart-ind-note')?.textContent || '');`),
    await evaluate(`return document.querySelector('.chart-ind-note')?.textContent || 'no note';`)
  );

  // Period retuning
  await evaluate(`
    const row = [...document.querySelectorAll('.chart-ind-row')].find((r) => /EMA 20/.test(r.textContent));
    const input = row.querySelector('input[type=number]');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, '34');
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  `);
  await sleep(500);
  check("EMA period is configurable from the panel", await evaluate(`return /EMA 34/.test(document.querySelector('.chart-hud-legend').textContent);`));

  // Restore: EMA off, BB on is fine to keep for the rest of the run.
  await clickInRow("EMA 34", "input[type=checkbox]");
  await sleep(400);
  await shot("02-indicators");
  await closeMenus();
}

// ------------------------------------------------------------- 4. split view

{
  await evaluate(`
    const btn = [...document.querySelectorAll('.chart-layout-switch button')].find((b) => /Split/.test(b.textContent));
    btn.click();
    return true;
  `);
  await sleep(900);
  check("split layout shows two panels", (await evaluate(`return document.querySelectorAll('.chart-panel').length;`)) === 2);
  check("panel B is labelled and independent", await waitFor(`document.querySelectorAll('.chart-panel')[1]?.getAttribute('aria-label')`, 10000, "panel B"));

  const labelsBefore = await evaluate(`return [...document.querySelectorAll('.chart-panel')].map((p) => p.getAttribute('aria-label'));`);
  await setSymbol(1, "LUCK");
  await sleep(400);
  await clickIn(1, '.chart-tf button:last-child');
  await sleep(900);
  const labelsAfter = await evaluate(`return [...document.querySelectorAll('.chart-panel')].map((p) => p.getAttribute('aria-label'));`);
  check("panel B symbol can differ from panel A", /LUCK/.test(labelsAfter[1]) && !/LUCK/.test(labelsAfter[0]), labelsAfter.join(" || "));
  check("panel B timeframe can differ from panel A", labelsAfter[0] !== labelsAfter[1] && labelsAfter[1] !== labelsBefore[1], labelsAfter.join(" || "));
  check("changing panel B left panel A alone", labelsAfter[0] === labelsBefore[0], `${labelsBefore[0]} → ${labelsAfter[0]}`);
  // Panel B re-fetches on every symbol/timeframe change, and the plot only
  // mounts once that dataset is ready — so wait for it instead of assuming a
  // fixed sleep is long enough.
  check("each panel renders its own plot", await waitFor(`document.querySelectorAll('.js-plotly-plot').length === 2`, 20000, "two plots"));
  check("each panel keeps its own legend", await waitFor(`
    document.querySelectorAll('.chart-panel').length === 2 &&
    Boolean(document.querySelectorAll('.chart-panel')[0].querySelector('.chart-hud-legend')) &&
    Boolean(document.querySelectorAll('.chart-panel')[1].querySelector('.chart-hud-legend'))
  `, 20000, "both legends"));
  await shot("03-split");
}

// ------------------------------------------------------- 5. drawing tools

{
  // Collapse the open menus first.
  await closeMenus();
  const rect = await plotRect(0);
  check("plot rectangle is measurable", Boolean(rect && rect.width > 200 && rect.height > 100), rect ? `${Math.round(rect.width)}×${Math.round(rect.height)}` : "none");

  const cx = rect.left + rect.width * 0.5;
  const cy = rect.top + rect.height * 0.5;

  const tools = [
    { label: "Trend Line", a: [-140, 60], b: [120, -40] },
    { label: "Rectangle", a: [-90, 30], b: [90, -60] },
    { label: "Circle", a: [-70, -20], b: [70, 40] },
    { label: "Parabola", a: [-60, 40], b: [80, -30] },
    { label: "Semicircle", a: [-100, 20], b: [60, 20] },
  ];

  for (const tool of tools) {
    await clickLabel(0, tool.label);
    await sleep(150);
    const armed = await inPanel(0, `
      const el = panel.querySelector('button[aria-pressed="true"][aria-label="${tool.label}"]');
      return Boolean(el);
    `);
    check(`${tool.label} tool arms with a visible active state`, armed);
    await clickTwice(cx + tool.a[0], cy + tool.a[1], cx + tool.b[0], cy + tool.b[1]);
    await sleep(250);
  }

  const drawn = await countIn(0, ".chart-svg-drawing");
  check("all five drawing primitives render on the chart", drawn === 5, `${drawn} drawings`);
  check("drawings are real paths, not HTML overlays", await inPanel(0, `
    const paths = [...panel.querySelectorAll('.chart-svg-drawing path')];
    return paths.length >= 5 && paths.every((p) => (p.getAttribute('d') || '').startsWith('M '));
  `));
  check("the chart meta strip counts the drawings", await inPanel(0, `return /5 drawings/.test(panel.querySelector('.chart-panel-meta').textContent);`));
  check("undo becomes available after drawing", await inPanel(0, `return !panel.querySelector('button[aria-label="Undo annotation change"]').disabled;`));
  await shot("04-drawings");

  // Style + lock controls for the selected drawing
  check("the selected drawing exposes style controls", await countIn(0, ".chart-swatches .chart-swatch") >= 4);
  await clickLabel(0, "Lock annotation");
  check("a locked drawing reports its state", await inPanel(0, `return Boolean(panel.querySelector('button[aria-label="Unlock annotation"][aria-pressed="true"]'));`));
  await clickLabel(0, "Unlock annotation");
  await clickLabel(0, "Hide annotation");
  check("a hidden drawing leaves the chart but keeps its data", (await countIn(0, ".chart-svg-drawing")) === 4 && (await inPanel(0, `return /5 drawings/.test(panel.querySelector('.chart-panel-meta').textContent);`)));
  await clickLabel(0, "Show annotation");
  check("showing it again restores the chart", (await countIn(0, ".chart-svg-drawing")) === 5);
}

// ------------------------------------------------------------ 6. undo / redo

{
  // Reset to an exact, known baseline: with five drawings already on the chart
  // an off-by-one in the history stack would be impossible to spot.
  await clickLabel(0, "Clear all drawings");
  await sleep(400);
  check("clear removes every drawing", (await countIn(0, ".chart-svg-drawing")) === 0);

  const plot = await plotRect(0);
  const cx = plot.left + plot.width * 0.5;
  const cy = plot.top + plot.height * 0.5;
  await clickLabel(0, "Trend Line");
  await clickTwice(cx - 150, cy + 40, cx + 110, cy - 30);
  await clickLabel(0, "Rectangle");
  await clickTwice(cx - 90, cy + 25, cx + 70, cy - 45);
  await sleep(350);
  check("two fresh drawings are on the chart", (await countIn(0, ".chart-svg-drawing")) === 2, `${await countIn(0, ".chart-svg-drawing")} drawing(s)`);

  await clickLabel(0, "Undo annotation change");
  await sleep(300);
  check("undo removes exactly the last drawing", (await countIn(0, ".chart-svg-drawing")) === 1);
  await clickLabel(0, "Undo annotation change");
  await sleep(300);
  check("undo again returns to an empty chart", (await countIn(0, ".chart-svg-drawing")) === 0);
  check(
    "undoing past the visible chart keeps redo available",
    await inPanel(0, `
      return !panel.querySelector('button[aria-label="Redo annotation change"]').disabled &&
             Boolean(panel.querySelector('button[aria-label="Undo annotation change"]'));
    `)
  );

  await clickLabel(0, "Redo annotation change");
  await sleep(300);
  check("redo restores the first drawing", (await countIn(0, ".chart-svg-drawing")) === 1);
  await clickLabel(0, "Redo annotation change");
  await sleep(300);
  check("redo restores the second drawing", (await countIn(0, ".chart-svg-drawing")) === 2);
  check("redo disables itself at the end of history", await inPanel(0, `return panel.querySelector('button[aria-label="Redo annotation change"]').disabled;`));

  // Selecting on the chart and deleting with the keyboard is the fast path a
  // trader actually uses, so it gets its own check.
  await clickAt(cx - 150, cy + 40);
  await sleep(250);
  check("clicking a drawing selects it", await inPanel(0, `return !panel.querySelector('button[aria-label="Delete selected annotation"]').disabled;`));
  await inPanel(0, `panel.querySelector('.chart-panel-tag').focus(); return true;`);
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Delete", code: "Delete", windowsVirtualKeyCode: 46 });
  await sleep(400);
  check("the Delete key removes the selected annotation", (await countIn(0, ".chart-svg-drawing")) === 1, `${await countIn(0, ".chart-svg-drawing")} drawing(s)`);

  await clickLabel(0, "Clear all drawings");
  await sleep(400);
  check("clear removes every drawing again", (await countIn(0, ".chart-svg-drawing")) === 0);
}

// ----------------------------------------------------------- 7. price levels

{
  await openMenu("Price level tools");
  check("price-level menu lists the five tools", await waitFor(`document.querySelectorAll('.chart-level-tool').length === 5`, 4000, "level tools"));
  const toolLabels = await evaluate(`return [...document.querySelectorAll('.chart-level-tool')].map((b) => b.textContent.trim());`);
  check("tools are Support, Resistance, Entry, Stop Loss, Target", toolLabels.join(",") === "Support,Resistance,Entry,Stop Loss,Target", toolLabels.join(" | "));

  await clickPopControl("Support");
  check("arming a level tool shows the placement hint", await waitFor(`document.querySelector('.chart-armed-hint')`, 4000, "armed hint"));
  await shot("05-level-armed");

  const rect = await plotRect(0);
  await clickAt(rect.left + rect.width * 0.6, rect.top + rect.height * 0.62);
  await sleep(600);
  check("clicking the chart places a support level", (await countIn(0, ".chart-svg-level")) === 1);
  check("the armed tool stays armed for repeat placements", /support/i.test((await textIn(0, ".chart-armed-hint")) || ""));

  // The toolbar promises Escape disarms the tool; that promise is a check.
  await inPanel(0, `panel.querySelector('.chart-panel-tag').focus(); return true;`);
  let disarmed = false;
  for (let attempt = 0; attempt < 3 && !disarmed; attempt++) {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await sleep(300);
    disarmed = await evaluate(`return !document.querySelector('.chart-armed-hint');`);
  }
  check("Escape returns the cursor to neutral (disarms the level tool)", disarmed);

  // The label carries the price, so the label is the honest thing to assert —
  // it stays on the chart even while the popover is closed.
  const labelBefore = (await textIn(0, ".chart-svg-level text")) || "";
  check("the level is labelled with its price", /Support\s[\d,]+\.\d\d/.test(labelBefore), labelBefore);

  const levelY = () =>
    inPanel(0, `
      const line = panel.querySelector('.chart-svg-level line');
      return line ? line.getBoundingClientRect().top + line.getBoundingClientRect().height / 2 : null;
    `);
  const yBefore = await levelY();
  // Drag from a point well inside the price pane: a price level is hit-tested on
  // its row, so any x inside the plot works — and an x inside the axis gutter
  // would (correctly) be ignored as "outside the chart".
  const dragX = rect.left + rect.width * 0.3;
  await dragFromTo(dragX, yBefore, dragX, yBefore - 60);
  await sleep(500);
  const yAfter = await levelY();
  const labelAfter = (await textIn(0, ".chart-svg-level text")) || "";
  check(
    "dragging a level moves it to a new price",
    yAfter !== null && yBefore !== null && yAfter < yBefore - 20 && labelAfter !== labelBefore,
    `${labelBefore} → ${labelAfter}`
  );

  // The list must agree with what is drawn (two views of one state).
  await openMenu("Price level tools");
  check(
    "the level list shows the same price the chart draws",
    await evaluate(`
      const row = document.querySelector('.chart-level-row');
      if (!row) return false;
      const listed = Number(row.querySelector('.chart-level-price').value);
      const drawn = Number(((document.querySelector('.chart-svg-level text') || {}).textContent || '').replace(/[^0-9.]/g, ''));
      return Number.isFinite(listed) && Number.isFinite(drawn) && Math.abs(listed - drawn) < 0.02;
    `)
  );
  check("the level can be renamed from the list", await evaluate(`
    const input = document.querySelector('.chart-level-input');
    return Boolean(input) && input.value.length > 0;
  `));

  // Locking must stop a drag from moving it again.
  check("the level can be locked from the list", await clickPopControl("Lock Support"));
  await sleep(300);
  const yLocked = await levelY();
  await dragFromTo(dragX, yLocked, dragX, yLocked - 45);
  await sleep(400);
  check("a locked level cannot be dragged", (await levelY()) === yLocked, `${yLocked} → ${await levelY()}`);

  await openMenu("Price level tools");
  await clickPopControl("Clear all levels");
  await sleep(400);
  check("clear removes every price level", (await countIn(0, ".chart-svg-level")) === 0);
  await closeMenus();
}

// ------------------------------------------------------- 8. crosshair / hover

{
  const rect = await plotRect(0);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: rect.left + rect.width * 0.4, y: rect.top + rect.height * 0.45, buttons: 0 });
  await sleep(500);
  const hover = await evaluate(`
    const el = document.querySelector('.chart-hud');
    return el ? { text: el.textContent, latest: Boolean(el.querySelector('.chart-hud-latest')) } : null;
  `);
  check("hovering the plot reports an OHLCV readout", Boolean(hover && /O\s/.test(hover.text) && /H\s/.test(hover.text) && /L\s/.test(hover.text) && /C\s/.test(hover.text) && /V\s/.test(hover.text)), hover?.text?.slice(0, 80));
  check("the readout follows the hovered bar instead of the last one", Boolean(hover && !hover.latest));
  check("indicator values are shown for the hovered bar", await evaluate(`
    const rows = [...document.querySelectorAll('.chart-hud-legend-row')];
    return rows.length >= 2 && rows.some((r) => /BB 20/.test(r.textContent));
  `));
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 10, y: 10, buttons: 0 });
  await sleep(300);
}

// ---------------------------------------------------------- 9. fullscreen

{
  await clickLabel(0, "Enter fullscreen");
  await sleep(900);
  check(
    "fullscreen expands the chart",
    await evaluate(`return Boolean(document.fullscreenElement) || Boolean(document.querySelector('.chart-panel.fs-fallback'));`)
  );
  check("fullscreen keeps the chart rendered", await evaluate(`return document.querySelectorAll('.js-plotly-plot .cartesianlayer').length >= 1;`));
  check("fullscreen keeps indicator state", await evaluate(`return /SMA 20/.test(document.querySelector('.chart-hud-legend')?.textContent || '');`));
  await shot("06-fullscreen");
  await clickLabel(0, "Exit fullscreen");
  await sleep(700);
  check("leaving fullscreen restores the workspace", await evaluate(`return !document.fullscreenElement && !document.querySelector('.chart-panel.fs-fallback');`));
}

// ----------------------------------------------------------- 10. persistence

{
  // Leave a drawing + a level behind, then reload.
  const rect = await plotRect(0);
  await clickLabel(0, "Trend Line");
  await clickTwice(rect.left + rect.width * 0.3, rect.top + rect.height * 0.3, rect.left + rect.width * 0.7, rect.top + rect.height * 0.6);
  await sleep(300);
  await openMenu("Price level tools");
  await clickPopControl("Target");
  await clickAt(rect.left + rect.width * 0.5, rect.top + rect.height * 0.35);
  await sleep(500);
  await closeMenus();

  const beforeReload = {
    drawings: await countIn(0, ".chart-svg-drawing"),
    levels: await countIn(0, ".chart-svg-level"),
  };

  // Zoom with a real wheel event. The write is debounced (one per gesture), so
  // give it a beat, then assert the window landed in the persisted store.
  await send("Input.dispatchMouseEvent", {
    type: "mouseWheel",
    x: rect.left + rect.width * 0.5,
    y: rect.top + rect.height * 0.3,
    deltaX: 0,
    deltaY: -240,
  });
  await sleep(1600);
  const savedViewport = await evaluate(`
    const raw = JSON.parse(localStorage.getItem('neural-market-chart-workspace') || '{}');
    const v = raw.state && raw.state.charts && raw.state.charts[0] ? raw.state.charts[0].viewport : null;
    return v ? { x0: v.xRange[0], x1: v.xRange[1] } : null;
  `);
  check("zooming the chart persists a viewport", Boolean(savedViewport), savedViewport ? `${new Date(savedViewport.x0).toISOString().slice(0, 10)} → ${new Date(savedViewport.x1).toISOString().slice(0, 10)}` : "nothing saved");
  check(
    "the persisted viewport is the window the user zoomed to (not the default fit)",
    Boolean(savedViewport) && savedViewport.x1 - savedViewport.x0 < 190 * 24 * 3600 * 1000
  );

  await send("Page.navigate", { url: `${BASE}${ROUTE}` });
  await waitFor(`document.querySelector('.chart-workspace')`, 45000, "workspace after reload");
  await waitFor(`document.querySelectorAll('.js-plotly-plot .cartesianlayer').length >= 1`, 30000, "plot after reload");
  await sleep(1200);

  check(
    "drawings survive a reload",
    (await countIn(0, ".chart-svg-drawing")) === beforeReload.drawings,
    `${beforeReload.drawings} before → ${await countIn(0, ".chart-svg-drawing")} after`
  );
  check(
    "price levels survive a reload",
    (await countIn(0, ".chart-svg-level")) === beforeReload.levels,
    `${beforeReload.levels} before → ${await countIn(0, ".chart-svg-level")} after`
  );
  check("indicator toggles survive a reload", await waitFor(`/BB 20/.test(document.querySelector('.chart-hud-legend')?.textContent || '')`, 10000, "BB after reload"));
  check("the split layout survives a reload", (await evaluate(`return document.querySelectorAll('.chart-panel').length;`)) === 2);

  const restoredWindow = await evaluate(`
    const gd = document.querySelector('.js-plotly-plot');
    const range = gd && gd._fullLayout && gd._fullLayout.xaxis ? gd._fullLayout.xaxis.range : null;
    return range ? { x0: Date.parse(range[0]), x1: Date.parse(range[1]) } : null;
  `);
  const restoredOk =
    Boolean(savedViewport && restoredWindow) &&
    Math.abs(restoredWindow.x0 - savedViewport.x0) < 60_000 &&
    Math.abs(restoredWindow.x1 - savedViewport.x1) < 60_000;
  check(
    "the zoom window is restored after a reload",
    restoredOk,
    restoredWindow ? `restored ${new Date(restoredWindow.x0).toISOString().slice(0, 10)} → ${new Date(restoredWindow.x1).toISOString().slice(0, 10)}` : "no axis range"
  );
}

// --------------------------------------------------------------- 11. mobile

{
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await sleep(1200);
  check("mobile shows one chart at a time with a switcher", (await evaluate(`return Boolean(document.querySelector('.chart-switcher'));`)) && (await evaluate(`return document.querySelectorAll('.chart-panel').length;`)) === 1);
  check("mobile has no horizontal overflow", await evaluate(`return document.documentElement.scrollWidth <= 391;`), `scrollWidth=${await evaluate("return document.documentElement.scrollWidth;")}`);

  const activeBefore = await evaluate(`return document.querySelector('.chart-panel').getAttribute('aria-label');`);
  await evaluate(`
    const btn = [...document.querySelectorAll('.chart-switcher button')].find((b) => /Chart B/.test(b.textContent));
    btn.click();
    return true;
  `);
  await sleep(900);
  const activeAfter = await evaluate(`return document.querySelector('.chart-panel')?.getAttribute('aria-label');`);
  check("the chart switcher swaps the visible panel", activeAfter !== activeBefore, `${activeBefore} → ${activeAfter}`);
  check("mobile keeps the toolbars usable", await evaluate(`return document.querySelectorAll('.chart-toolbar .chart-icon-btn').length >= 8;`));

  // The switched-to panel fetches its own series; wait for it to be drawable
  // before tapping, otherwise the drawing toolbar is still disabled.
  await waitFor(`!document.querySelector('.chart-panel .chart-skeleton')`, 25000, "mobile panel ready");
  await inPanel(0, `panel.scrollIntoView({ block: 'center' }); return true;`);
  await sleep(400);

  const rect = await plotRect(0);
  note(`mobile plot rect: ${Math.round(rect.left)},${Math.round(rect.top)} ${Math.round(rect.width)}×${Math.round(rect.height)}`);
  await clickLabel(0, "Trend Line");
  await sleep(200);
  check(
    "the mobile drawing toolbar arms a tool",
    await inPanel(0, `return Boolean(panel.querySelector('button[aria-label="Trend Line"][aria-pressed="true"]'));`)
  );

  const tapA = [rect.left + rect.width * 0.3, rect.top + rect.height * 0.35];
  const tapB = [rect.left + rect.width * 0.75, rect.top + rect.height * 0.6];
  check(
    "both tap targets are inside the mobile viewport",
    tapA.every((v) => v > 0) && tapB[0] < 390 && tapB[1] < 844,
    `${tapA.map(Math.round).join(",")} → ${tapB.map(Math.round).join(",")}`
  );
  await clickTwice(tapA[0], tapA[1], tapB[0], tapB[1]);
  await sleep(500);
  check("drawing works on the mobile layout", (await countIn(0, ".chart-svg-drawing")) >= 1, `${await countIn(0, ".chart-svg-drawing")} drawing(s)`);
  await shot("07-mobile");

  await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await sleep(600);
}

// -------------------------------------------------------------- 12. hygiene

{
  // The market-data API on :8000 is *optional* for this page — the chart is
  // documented to fall back to the Phase-5 sample history when it is down — so
  // network-level failures are reported separately instead of being counted as
  // defects in the charting code.
  const networkNoise = (line) => /Failed to load resource|net::ERR_|ERR_CONNECTION|ERR_NAME_NOT_RESOLVED/i.test(line);
  const codeErrors = consoleErrors.filter((line) => !/favicon/i.test(line) && !networkNoise(line));
  const networkErrors = consoleErrors.filter(networkNoise);
  const codeExceptions = exceptions.filter((line) => !/ResizeObserver loop/i.test(line));
  const apiFailures = failedRequests.filter((url) => /\/api\/|\/ws\//.test(url));
  const otherFailures = failedRequests.filter((url) => !/\/api\/|\/ws\//.test(url));

  check("no uncaught exceptions", codeExceptions.length === 0, codeExceptions.slice(0, 2).join(" || ") || "none");
  check("no console errors from the charting code", codeErrors.length === 0, codeErrors.slice(0, 3).join(" || ") || "none");
  check("no failed non-API requests", otherFailures.length === 0, [...new Set(otherFailures)].slice(0, 3).join(" || ") || "none");
  check(
    "the panel states where its data came from",
    await evaluate(`return /Market history API|PSX index series/.test(document.querySelector('.chart-panel-meta')?.textContent || '');`),
    (await textIn(0, ".chart-panel-meta"))?.slice(0, 90)
  );
  check(
    "the panel states how fresh that data is",
    await evaluate(`return /LIVE|RECENT|CACHED|STALE|UNAVAILABLE/.test(document.querySelector('.chart-panel-meta')?.textContent || '');`)
  );
  if (networkErrors.length || apiFailures.length) {
    note(`${networkErrors.length + apiFailures.length} network error(s) ignored — the backend on :8000 is not running`);
  }
  if (consoleWarnings.length) note(`${consoleWarnings.length} console warning(s): ${[...new Set(consoleWarnings)][0]?.slice(0, 120)}`);
}

console.log("\n--- diagnostics ---------------------------------------------------");
console.log(`console errors (${consoleErrors.length}):`);
[...new Set(consoleErrors)].slice(0, 8).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));
console.log(`console warnings (${consoleWarnings.length}):`);
[...new Set(consoleWarnings)].slice(0, 5).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));
console.log(`failed requests (${failedRequests.length}):`);
[...new Set(failedRequests)].slice(0, 5).forEach((line) => console.log(`   - ${line.slice(0, 180)}`));

const failed = results.filter((r) => !r.ok);
console.log("\n--- summary -------------------------------------------------------");
console.log(`${results.length - failed.length}/${results.length} checks passed`);
console.log(`screenshots: ${SHOTS}`);
if (failed.length) {
  console.log("FAILED:");
  failed.forEach((f) => console.log(`   - ${f.name}${f.detail ? ` (${f.detail})` : ""}`));
}
process.exit(failed.length ? 1 : 0);
