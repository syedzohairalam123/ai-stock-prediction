/*
 * Page audit harness (dev-only).
 *
 * Drives an already-running Chrome (launched with --remote-debugging-port=9222)
 * over the Chrome DevTools Protocol using Node's built-in WebSocket. Visits every
 * route in the app, then reports:
 *   - uncaught JS exceptions
 *   - console errors/warnings
 *   - failed requests (network error or HTTP >= 400)
 *   - pages that look empty / stuck on a skeleton / hit the error boundary
 *
 * Usage:
 *   # 1. start the app (backend on :8000, dev server on :5173)
 *   # 2. launch Chrome with a debug port
 *   chrome --remote-debugging-port=9222 http://localhost:5173
 *   # 3. run the audit
 *   node scripts/page-audit.mjs [baseUrl] [--only=<path substring>] [--full]
 *
 *   --only=stock      run just the routes whose path contains "stock"
 *   --full            dump each visited page's whole visible text
 *   AUDIT_MIN_SETTLE_MS / AUDIT_MAX_SETTLE_MS   per-page wait bounds
 *
 * Requires no dependencies (Node 22+ for the global WebSocket) and is not part
 * of the app bundle. Exit code 1 means at least one route needs attention.
 */

const CDP_HTTP = "http://127.0.0.1:9222";
const BASE = process.argv.find((a) => a.startsWith("http")) || "http://localhost:5173";
// A page is "settled" once its text stops growing and no loading affordance is
// visible. Slow pages (a screener scanning 30 tickers) just take longer; a page
// that never settles is a genuine problem.
const MIN_SETTLE_MS = Number(process.env.AUDIT_MIN_SETTLE_MS || 2500);
const MAX_SETTLE_MS = Number(process.env.AUDIT_MAX_SETTLE_MS || 45000);

// Every route defined in src/App.tsx, with the params each one needs.
// `click` names the primary action button on that page; the audit presses it and
// keeps watching for errors, because that is where runtime bugs actually surface.
const ROUTES = [
  { path: "/", label: "Home" },
  { path: "/stock/OGDC", label: "StockDashboard", click: "Check Now" },
  { path: "/index/KSE100", label: "IndexPage" },
  { path: "/market", label: "MarketPage" },
  { path: "/charts", label: "ChartWorkspacePage", click: "Split" },
  { path: "/news", label: "NewsPage" },
  { path: "/portfolio", label: "PortfolioPage" },
  { path: "/watchlist", label: "WatchlistPage" },
  { path: "/announcements", label: "AnnouncementsPage" },
  { path: "/alerts", label: "AlertsOverviewPage" },
  { path: "/compare", label: "ComparePage", click: "Compare" },
  { path: "/screener", label: "Screener", click: "Run scan" },
  { path: "/screener-classic", label: "ScreenerPage", click: "Scan Market" },
  { path: "/markets", label: "MarketsPage" },
  { path: "/analytics", label: "Analytics", click: "Detect regime" },
  { path: "/command-center", label: "CommandCenter" },
  { path: "/macro", label: "Macro" },
  { path: "/events", label: "Events", click: "Run study" },
  { path: "/company?ticker=OGDC", label: "Company" },
  { path: "/crypto", label: "Crypto" },
  { path: "/forex-commodities", label: "ForexCommoditiesPage", click: "Refresh rates" },
  { path: "/sentiment", label: "SentimentPage" },
  { path: "/login", label: "LoginPage" },
  { path: "/signup", label: "SignupPage" },
  { path: "/settings", label: "SettingsPage" },
];

// ---------------- CDP plumbing ----------------

async function findPageTarget() {
  const res = await fetch(`${CDP_HTTP}/json/list`);
  const targets = await res.json();
  const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
  if (!page) throw new Error("No debuggable page target found. Is Chrome running with --remote-debugging-port=9222?");
  return page;
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let nextId = 1;
    const pending = new Map();
    const listeners = [];

    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && pending.has(msg.id)) {
        const { resolve: ok, reject: fail } = pending.get(msg.id);
        pending.delete(msg.id);
        msg.error ? fail(new Error(msg.error.message)) : ok(msg.result);
        return;
      }
      if (msg.method) listeners.forEach((fn) => fn(msg));
    });
    ws.addEventListener("error", reject);
    ws.addEventListener("open", () =>
      resolve({
        send(method, params = {}) {
          const id = nextId++;
          return new Promise((ok, fail) => {
            pending.set(id, { resolve: ok, reject: fail });
            ws.send(JSON.stringify({ id, method, params }));
          });
        },
        on(fn) {
          listeners.push(fn);
        },
        close() {
          ws.close();
        },
      })
    );
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Run in the page: describe what the user actually sees.
const PAGE_PROBE = `(() => {
  const main = document.querySelector("main") || document.body;
  const text = (main.innerText || "").trim();
  const bodyText = document.body.innerText || "";
  const visibles = (sel) => [...document.querySelectorAll(sel)].filter((el) => el.offsetParent !== null || el.getClientRects().length).length;
  const loadingTexts = (bodyText.match(/[^\\n]*(loading\\.\\.\\.|scanning\\.\\.\\.|please wait|fetching)[^\\n]*/gi) || []);
  return {
    path: location.pathname + location.search,
    title: document.title,
    textLen: text.length,
    head: text.slice(0, 180).replace(/\\n+/g, " | "),
    errorBoundary: /something went wrong|try again|unexpected error/i.test(bodyText),
    skeletons: visibles('[class*="skeleton"], [class*="Skeleton"], .animate-pulse'),
    spinners: visibles('[class*="spinner"], .loading, [role="progressbar"]'),
    loadingText: loadingTexts.length,
    // A page with form controls or an honest empty-state message is interactive,
    // not a broken/empty panel — only genuinely blank content is a defect.
    hasForm: document.querySelectorAll("input, select, textarea").length > 0,
    emptyState: /no active alerts|no tickers saved|nothing saved|yet —|yet -|add one|open a stock|no data|not set/i.test(bodyText),
    errorTexts: [...new Set((bodyText.match(/[^\\n]*(failed to fetch|network error|unavailable|is not a function|cannot read|undefined is not)[^\\n]*/gi) || []).map((s) => s.trim().slice(0, 120)))].slice(0, 5),
  };
})()`;

// ---------------- audit ----------------

async function main() {
  const target = await findPageTarget();
  const cdp = await connect(target.webSocketDebuggerUrl);

  await cdp.send("Runtime.enable");
  await cdp.send("Page.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");

  let bucket = blank();
  const report = [];
  const inflight = new Map();

  function blank() {
    return { consoleErrors: [], exceptions: [], logErrors: [], failedRequests: [], api: [] };
  }

  cdp.on((msg) => {
    const p = msg.params || {};
    if (msg.method === "Network.requestWillBeSent") {
      const url = p.request?.url || "";
      if (url.includes("/api/") || url.includes("/ws/")) inflight.set(p.requestId, { url, at: Date.now() });
      return;
    }
    if (msg.method === "Network.loadingFinished" && inflight.has(p.requestId)) {
      const req = inflight.get(p.requestId);
      inflight.delete(p.requestId);
      bucket.api.push({ url: req.url.replace(BASE, ""), ms: Date.now() - req.at, status: req.status ?? "?" });
      return;
    }
    if (msg.method === "Runtime.exceptionThrown") {
      const d = p.exceptionDetails || {};
      bucket.exceptions.push((d.exception?.description || d.text || "unknown").split("\n").slice(0, 3).join(" ").slice(0, 300));
    } else if (msg.method === "Runtime.consoleAPICalled" && (p.type === "error" || p.type === "warning")) {
      const text = (p.args || []).map((a) => a.value ?? a.description ?? a.type).join(" ").slice(0, 300);
      // React DevTools suggestion is noise, not a defect.
      if (!/react devtools/i.test(text)) bucket.consoleErrors.push(`${p.type}: ${text}`);
    } else if (msg.method === "Log.entryAdded" && p.entry?.level === "error") {
      const text = `${p.entry.text || ""} ${p.entry.url || ""}`.trim();
      if (!/favicon/i.test(text)) bucket.logErrors.push(text.slice(0, 300));
    } else if (msg.method === "Network.loadingFailed") {
      const failed = inflight.get(p.requestId);
      inflight.delete(p.requestId);
      if (!/net::ERR_ABORTED/.test(p.errorText || "")) bucket.failedRequests.push(`${p.errorText} ${failed?.url || ""}`.trim());
    } else if (msg.method === "Network.responseReceived") {
      const r = p.response || {};
      if (inflight.has(p.requestId)) inflight.get(p.requestId).status = r.status;
      if (r.status >= 400) bucket.failedRequests.push(`${r.status} ${r.url}`);
    }
  });

  async function probe() {
    const { result } = await cdp.send("Runtime.evaluate", { expression: PAGE_PROBE, returnByValue: true, awaitPromise: false });
    return result.value;
  }

  // Poll the page until its text stops changing and nothing is loading.
  async function settleUntilQuiet() {
    let dom = await probe();
    let stable = 0;
    const deadline = Date.now() + MAX_SETTLE_MS;
    while (Date.now() < deadline) {
      await sleep(1000);
      const next = await probe();
      const quiet = next.textLen === dom.textLen && next.skeletons === 0 && next.spinners === 0 && !next.loadingText;
      stable = quiet ? stable + 1 : 0;
      dom = next;
      if (stable >= 2) break;
    }
    return { dom, settled: stable >= 2 };
  }

  // --only=<substring> runs a single route; --full dumps its whole visible text.
  const only = (process.argv.find((a) => a.startsWith("--only=")) || "").split("=")[1];
  const full = process.argv.includes("--full");
  const routes = only ? ROUTES.filter((r) => r.path.includes(only)) : ROUTES;

  for (const route of routes) {
    bucket = blank();
    inflight.clear();
    const started = Date.now();
    await cdp.send("Page.navigate", { url: BASE + route.path });
    await sleep(MIN_SETTLE_MS);

    let { dom, settled } = await settleUntilQuiet();

    // Press the page's primary action, then let it settle again.
    let click = null;
    if (route.click) {
      const expr = `(() => {
        const want = ${JSON.stringify(route.click.toLowerCase())};
        const b = [...document.querySelectorAll('button')].find((x) => (x.textContent || '').trim().toLowerCase().includes(want) && !x.disabled);
        if (!b) return 'button-not-found';
        b.click();
        return 'clicked';
      })()`;
      const { result: c } = await cdp.send("Runtime.evaluate", { expression: expr, returnByValue: true });
      click = c.value;
      if (click === "clicked") ({ dom, settled } = await settleUntilQuiet());
    }

    if (full) {
      const { result: t } = await cdp.send("Runtime.evaluate", { expression: "document.querySelector('main')?.innerText || document.body.innerText", returnByValue: true });
      console.log(`\n########## ${route.path} (${route.label}) ##########\n${t.value}\n`);
    }
    report.push({ ...route, ...bucket, dom, loadMs: Date.now() - started, settled, click });
  }

  cdp.close();

  // ---------------- summary ----------------
  const noContent = (r) => !r.dom || (r.dom.textLen < 300 && !r.dom.hasForm && !r.dom.emptyState);
  const problems = report.filter(
    (r) =>
      r.exceptions.length ||
      r.consoleErrors.length ||
      r.logErrors.length ||
      r.failedRequests.length ||
      !r.settled ||
      r.dom?.errorBoundary ||
      noContent(r) ||
      r.dom?.errorTexts.length ||
      r.dom?.loadingText
  );

  console.log(`\nAudited ${report.length} routes on ${BASE}\n`);
  for (const r of report) {
    const bad =
      r.exceptions.length ||
      r.consoleErrors.length ||
      r.logErrors.length ||
      r.failedRequests.length ||
      !r.settled ||
      r.dom?.errorBoundary ||
      r.dom?.errorTexts.length ||
      r.dom?.loadingText;
    console.log(
      `${bad ? "FAIL" : " ok "}  ${r.path.padEnd(26)} text=${String(r.dom?.textLen ?? 0).padStart(5)} load=${String(r.loadMs).padStart(6)}ms ${r.settled ? "settled" : "STUCK"} ${r.click ? `[${r.click}]` : ""} :: ${r.dom?.head?.slice(0, 55) || ""}`
    );
  }

  const slow = report
    .flatMap((r) => r.api.map((a) => ({ ...a, path: r.path })))
    .filter((a) => a.ms > 3000)
    .sort((a, b) => b.ms - a.ms)
    .slice(0, 15);
  if (slow.length) {
    console.log("\n=== slowest API calls (>3s) ===");
    slow.forEach((a) => console.log(`  ${String(a.ms).padStart(6)}ms  ${a.status}  ${a.url}   <- ${a.path}`));
  }

  console.log(`\n=== ${problems.length} route(s) need attention ===\n`);
  for (const r of problems) {
    console.log(`--- ${r.label} (${r.path})`);
    r.exceptions.slice(0, 4).forEach((e) => console.log(`    EXCEPTION: ${e}`));
    r.consoleErrors.slice(0, 4).forEach((e) => console.log(`    CONSOLE  : ${e}`));
    r.logErrors.slice(0, 4).forEach((e) => console.log(`    LOG      : ${e}`));
    [...new Set(r.failedRequests)].slice(0, 6).forEach((e) => console.log(`    REQUEST  : ${e}`));
    if (r.dom?.errorBoundary) console.log("    UI       : error boundary fallback rendered");
    if (!r.settled) console.log(`    UI       : never settled after ${r.loadMs}ms (still loading/skeletons)`);
    if (r.dom?.loadingText) console.log(`    UI       : still showing a loading state after ${r.loadMs}ms`);
    if (noContent(r)) console.log(`    UI       : only ${r.dom?.textLen ?? 0} chars of content`);
    (r.dom?.errorTexts || []).forEach((e) => console.log(`    UI-TEXT  : ${e}`));
    console.log();
  }

  process.exit(problems.length ? 1 : 0);
}

main().catch((err) => {
  console.error("audit failed:", err.message);
  process.exit(2);
});
