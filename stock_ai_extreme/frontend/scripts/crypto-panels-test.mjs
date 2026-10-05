/*
 * Phase 22D crypto panels test (dev-only).
 *
 * Drives an already-running Chrome (launched with --remote-debugging-port=9222)
 * over the Chrome DevTools Protocol and asserts that the crypto terminal renders
 * its panels — in particular the Phase 22D additions:
 *
 *   ALL      → micro-trend, volatility, MODELLED FORECAST, REALISED Forecast
 *              performance, STORED Forecast history
 *   TARGETS  → target ladder, target comparison (with FIRST REACHED), threshold
 *              analyzer, target event timeline
 *
 * It also fails on any uncaught JS exception or console error seen while the
 * page settles, so a broken panel cannot pass silently.
 *
 * Usage:
 *   # 1. backend on :8000, dev server on :5173
 *   # 2. chrome --remote-debugging-port=9222 about:blank
 *   # 3. node scripts/crypto-panels-test.mjs [baseUrl]
 *
 * Requires no dependencies (Node 22+ for the global WebSocket). Exit code 1
 * means at least one assertion failed.
 */

const CDP_HTTP = "http://127.0.0.1:9222";
const BASE = process.argv.find((a) => a.startsWith("http")) || "http://localhost:5173";
const URL = `${BASE}/crypto-terminal?symbol=BTC&timeframe=5m`;
const SETTLE_MS = Number(process.env.CRYPTO_TEST_SETTLE_MS || 18000);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function findPageTarget() {
  const targets = await (await fetch(`${CDP_HTTP}/json/list`)).json();
  const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
  if (!page) throw new Error("No debuggable page. Is Chrome running with --remote-debugging-port=9222?");
  return page;
}

function connect(url) {
  const ws = new WebSocket(url);
  let nextId = 1;
  const pending = new Map();
  const events = [];
  const ready = new Promise((resolve, reject) => {
    ws.addEventListener("open", () => resolve());
    ws.addEventListener("error", reject);
  });
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      return;
    }
    if (msg.method) events.push(msg);
  });
  return {
    ready,
    events,
    send(method, params = {}) {
      const id = nextId++;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
    },
    close: () => ws.close(),
  };
}

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

async function evaluate(cdp, expression) {
  const { result } = await cdp.send("Runtime.evaluate", { expression, returnByValue: true });
  return result.value;
}

const page = await findPageTarget();
const cdp = connect(page.webSocketDebuggerUrl);
await cdp.ready;
await cdp.send("Page.enable");
await cdp.send("Runtime.enable");
await cdp.send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
});
await cdp.send("Page.navigate", { url: URL });
await sleep(SETTLE_MS);

const ALL_PANELS = [
  "Micro trend",
  "Volatility",
  "MODELLED FORECAST",
  "Forecast performance",
  "Forecast history",
  "Live news",
];
const allText = await evaluate(cdp, `document.querySelector(".crypto-terminal-main").innerText`);
for (const panel of ALL_PANELS) {
  check(`ALL renders "${panel}"`, allText.includes(panel));
}
check(
  "ALL has real candle data (not empty)",
  await evaluate(cdp, `document.querySelectorAll(".crypto-terminal-foot").length > 0`)
);
check(
  "ALL news panel lists real attributed headlines",
  (await evaluate(cdp, `document.querySelectorAll(".crypto-news-item").length`)) > 0
);

// Switch to the TARGETS subcategory.
const clicked = await evaluate(
  cdp,
  `(() => {
    const btn = Array.from(document.querySelectorAll("button"))
      .find((b) => (b.innerText || "").trim().toUpperCase() === "TARGETS");
    if (!btn) return false;
    btn.click();
    return true;
  })()`
);
check("TARGETS tab is present and clickable", clicked === true);
await sleep(Math.max(6000, SETTLE_MS / 2));

const TARGET_PANELS = [
  "Target ladder",
  "Target comparison",
  "Threshold analyzer",
  "Target event timeline",
];
const targetText = await evaluate(cdp, `document.querySelector(".crypto-terminal-main").innerText`);
for (const panel of TARGET_PANELS) {
  check(`TARGETS renders "${panel}"`, targetText.includes(panel));
}
check(
  "Target comparison shows the FIRST REACHED column",
  targetText.includes("FIRST REACHED") || targetText.toUpperCase().includes("FIRST REACHED")
);
check(
  "Target event timeline has real rows",
  (await evaluate(
    cdp,
    `document.querySelectorAll(".crypto-target-history-panel table.crypto-table tbody tr").length`
  )) > 0
);

const exceptions = cdp.events
  .filter((e) => e.method === "Runtime.exceptionThrown")
  .map((e) => e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text);
const consoleErrors = cdp.events
  .filter((e) => e.method === "Runtime.consoleAPICalled" && e.params.type === "error")
  .map((e) => (e.params.args || []).map((a) => a.value || a.description).join(" "));
check("no uncaught JS exceptions", exceptions.length === 0, exceptions.join(" | "));
check("no console errors", consoleErrors.length === 0, consoleErrors.join(" | "));

cdp.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length === 0 ? 0 : 1);
